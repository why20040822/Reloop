"""JD 匹配评分（demo 版：大模型实现 + 5 因子加权乘法占位）。

占位设计（对齐《Reloop技术方案》rev 82 的触达优先级公式）：

    Score = 活跃度^0.3 × 匹配度^0.4 × 人才价值^0.15 × 历史关系^0.1 × 求职倾向^0.05

demo 阶段只有「匹配度」由大模型实时给出，其余 4 个因子固定中性分 0.5
（NEUTRAL_FACTOR），加权乘法公式本身是真的——触达引擎落地时只需把
``placeholder_factors`` 换成真实因子来源，不动公式和调用方。
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from reloop.utils.llm_client import complete, parse_json_safe

logger = logging.getLogger(__name__)

#: 5 因子权重（rev 82 定版，触达引擎落地时复用同一组权重）
FACTOR_WEIGHTS: dict[str, float] = {
    "activity": 0.3,       # 活跃度
    "match": 0.4,          # 岗位匹配度
    "value": 0.15,         # 人才价值
    "relationship": 0.1,   # 历史关系
    "intent": 0.05,        # 求职倾向
}

#: 占位因子的中性分：无数据时的约定值（rev 82：求职倾向无记录默认 0.5）
NEUTRAL_FACTOR = 0.5

#: 传给大模型的简历正文截断长度
_RAW_TEXT_LIMIT = 2000

_PROMPT_TEMPLATE = """你是猎头匹配专家。根据岗位 JD 和候选人简历，评估匹配度并给出触达理由。

输出且仅输出 JSON：{{"match": <0.0 到 1.0 的匹配度>, "reason": "<30 字内的触达破冰理由>"}}

岗位 JD：
{jd_text}

候选人：{name}，{company}，{title}
简历摘要：
{raw_text}"""


@dataclass(frozen=True)
class JdMatchResult:
    """One candidate's JD-match score with factor breakdown."""

    candidate_id: Any
    name: str
    score: float                     # 0-100 加权乘法总分
    match_score: float               # 大模型给出的匹配度 0-1
    reason: str                      # 大模型生成的触达理由
    factors: dict[str, float | None] = field(default_factory=dict)


def placeholder_factors() -> dict[str, float | None]:
    """Factor slots for the weighted product. None = 占位（按 NEUTRAL_FACTOR 计）。

    触达引擎落地后，activity/value/relationship/intent 由信号层和画像库填充。
    """

    return {"activity": None, "match": None, "value": None, "relationship": None, "intent": None}


def weighted_product(factors: dict[str, float | None]) -> float:
    """5 因子加权乘法（0-1）。None 因子按 NEUTRAL_FACTOR 代入。"""

    score = 1.0
    for name, weight in FACTOR_WEIGHTS.items():
        value = factors.get(name)
        score *= (NEUTRAL_FACTOR if value is None else max(0.0, min(1.0, value))) ** weight
    return score


def _llm_match(jd_text: str, candidate: dict[str, Any]) -> tuple[float, str] | None:
    """Score one candidate against the JD with the LLM. None when unavailable."""

    prompt = _PROMPT_TEMPLATE.format(
        jd_text=jd_text[:4000],
        name=candidate.get("name") or "未知",
        company=candidate.get("current_company") or "未知公司",
        title=candidate.get("current_role") or "未知职位",
        raw_text=(candidate.get("raw_text") or "")[:_RAW_TEXT_LIMIT],
    )
    try:
        parsed = parse_json_safe(complete(prompt, json_mode=True, temperature=0.2))
    except Exception:
        logger.warning("LLM JD match failed for candidate %s", candidate.get("id"), exc_info=True)
        return None
    if not parsed:
        return None
    try:
        match = max(0.0, min(1.0, float(parsed.get("match"))))
    except (TypeError, ValueError):
        return None
    reason = str(parsed.get("reason") or "").strip()[:80]
    return match, reason


def score_candidate(jd_text: str, candidate: dict[str, Any]) -> JdMatchResult | None:
    """Score one candidate: LLM 匹配度 + 占位因子走加权乘法。"""

    llm = _llm_match(jd_text, candidate)
    if llm is None:
        return None
    match, reason = llm
    factors = placeholder_factors()
    factors["match"] = match
    return JdMatchResult(
        candidate_id=candidate.get("id"),
        name=candidate.get("name") or "未知",
        score=round(100 * weighted_product(factors), 1),
        match_score=round(match, 3),
        reason=reason,
        factors=factors,
    )


def _keyword_prefilter(jd_text: str, candidates: list[dict[str, Any]], keep: int) -> list[dict[str, Any]]:
    """Cheap keyword-overlap pre-filter so the LLM only sees the best pool."""

    tokens = {t.lower() for t in re.split(r"[^\w一-鿿]+", jd_text) if len(t) >= 2}
    if not tokens:
        return candidates[:keep]

    def overlap(candidate: dict[str, Any]) -> int:
        text = (candidate.get("raw_text") or "").lower()
        return sum(1 for token in tokens if token in text)

    ranked = sorted(candidates, key=overlap, reverse=True)
    return ranked[:keep]


def rank_candidates(
    jd_text: str,
    candidates: list[dict[str, Any]],
    *,
    limit: int = 5,
    llm_pool_size: int = 20,
    max_workers: int = 5,
) -> list[JdMatchResult]:
    """Pre-filter by keyword overlap, LLM-score the pool, return Top N by score."""

    pool = _keyword_prefilter(jd_text, candidates, keep=max(1, llm_pool_size))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(lambda c: score_candidate(jd_text, c), pool))
    scored = [r for r in results if r is not None]
    scored.sort(key=lambda r: r.score, reverse=True)
    return scored[: max(1, limit)]


__all__ = [
    "FACTOR_WEIGHTS",
    "JdMatchResult",
    "NEUTRAL_FACTOR",
    "placeholder_factors",
    "rank_candidates",
    "score_candidate",
    "weighted_product",
]
