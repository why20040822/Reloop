"""触达优先级双因子量化算法（v3: 活跃度 + 岗位匹配度）。

公式:
  综合分 = 活跃度^w_activity × 岗位匹配度^w_match

每个因子归一化到 [0,1], 权重在 .env 的 BRAINX_SCORE_W_ACTIVITY / BRAINX_SCORE_W_MATCH。
排序时用户可选择按活跃度或匹配度 100% 权重排序, 另一指标仅展示不参与排序。

活跃度因子来源:
  1. TTC 平台最近活跃/更新时间 (talent_profiles.last_active_at)
  2. 顾问在 Reloop 内与人才的互动记录 (interaction_records)

岗位匹配度因子:
  - 主通道: LLM 批量推理(JD vs 简历综合评分, 0~1)
  - 降级通道: 结构化多维(title/skill/semantic/years/edu, 缺失维度权重重归一)
"""

import datetime as dt
import math
from typing import Iterable, Optional, Sequence

from reloop.config import settings


# =====================================================================
# 因子 1: 活跃度 —— 分事件半衰期的牛顿冷却 + 绝对/相对混合归一化 (v2)
# =====================================================================
EVENT_WEIGHTS = {
    "platform_active": 6.0,
    "profile_update": 10.0,
    "interview": 8.0,
    "call": 5.0,
    "message": 2.0,
}

EVENT_HALF_LIVES = {
    "platform_active": 14.0,
    "profile_update": 21.0,
    "interview": 30.0,
    "call": 45.0,
    "message": 45.0,
}
DEFAULT_HALF_LIFE = 45.0
ACTIVITY_ABS_WINDOW = 180.0
FACTOR_FLOOR = 0.05


def activity_score(events: Iterable[dict], now: Optional[dt.datetime] = None,
                   decay: Optional[float] = None) -> float:
    if now is None:
        now = _utcnow_naive()
    else:
        now = _to_naive_utc(now)

    total = 0.0
    for ev in events:
        etype = ev.get("event_type", "")
        w = ev.get("weight") or EVENT_WEIGHTS.get(etype, 1.0)
        occurred = ev.get("occurred_at")
        if occurred is None:
            continue
        if isinstance(occurred, str):
            occurred = dt.datetime.fromisoformat(occurred)
        occurred = _to_naive_utc(occurred)
        days = max((now - occurred).total_seconds() / 86400.0, 0.0)
        if decay is not None:
            lam = decay
        else:
            lam = math.log(2.0) / EVENT_HALF_LIVES.get(etype, DEFAULT_HALF_LIFE)
        total += w * math.exp(-lam * days)
    return total


def days_since_latest_event(events: Iterable[dict],
                            now: Optional[dt.datetime] = None) -> Optional[float]:
    if now is None:
        now = _utcnow_naive()
    else:
        now = _to_naive_utc(now)
    latest: Optional[dt.datetime] = None
    for ev in events:
        occurred = ev.get("occurred_at")
        if occurred is None:
            continue
        if isinstance(occurred, str):
            occurred = dt.datetime.fromisoformat(occurred)
        occurred = _to_naive_utc(occurred)
        if latest is None or occurred > latest:
            latest = occurred
    if latest is None:
        return None
    return max((now - latest).total_seconds() / 86400.0, 0.0)


def absolute_activity(days_since_latest: Optional[float],
                      window: float = ACTIVITY_ABS_WINDOW) -> float:
    if days_since_latest is None:
        return FACTOR_FLOOR
    return max(FACTOR_FLOOR, min(1.0, 1.0 - days_since_latest / window))


def hybrid_activity_normalize(raws: Sequence[float],
                              latest_days: Sequence[Optional[float]],
                              alpha: Optional[float] = None) -> list[float]:
    if alpha is None:
        alpha = settings.activity_absolute_weight
    absolutes = [absolute_activity(d) for d in latest_days]
    relatives = min_max_normalize(list(raws))
    return [
        max(FACTOR_FLOOR, min(1.0, alpha * a + (1.0 - alpha) * r))
        for a, r in zip(absolutes, relatives)
    ]


def _utcnow_naive() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def _to_naive_utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is not None:
        return value.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return value


def build_activity_events(last_active_at=None,
                          resume_updated_at=None,
                          interactions: Iterable[dict] = ()) -> list[dict]:
    events = []
    # 简历更新时间作为最高权重活动信号（反映人才近期主动更新资料）
    if resume_updated_at is not None:
        events.append(
            {"event_type": "profile_update", "occurred_at": resume_updated_at}
        )
    # 若 last_active_at 与 resume_updated_at 同源(都来自 TTC last_updated_at),
    # 视为同一事件, 不再重复计数(避免等效双倍权重虚高活跃度)。
    if last_active_at is not None and last_active_at != resume_updated_at:
        events.append(
            {"event_type": "platform_active", "occurred_at": last_active_at}
        )
    for it in interactions:
        occ = it.get("occurred_at")
        if occ is None:
            continue
        if isinstance(occ, dt.date) and not isinstance(occ, dt.datetime):
            occ = dt.datetime.combine(occ, dt.time())
        events.append(
            {"event_type": it.get("interaction_type", "note"), "occurred_at": occ}
        )
    return events


def min_max_normalize(values: Sequence[float]) -> list[float]:
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        if hi < 1e-9:
            return [FACTOR_FLOOR] * len(values)
        return [0.5] * len(values)
    return [max(FACTOR_FLOOR, (v - lo) / (hi - lo)) for v in values]


# =====================================================================
# 遗留: 人才价值静态分 (已从核心评分移除, 仅 structuing.py 写入 DB 用)
# =====================================================================

def raw_value_score(company_tier: str = "一般", education: str = "本科", skills: list = None) -> float:
    """人才价值静态分(0~1) —— 仅用于落库, 不参与核心评分。"""
    skills = skills or []
    tier_score = {"头部": 0.9, "中腰部": 0.7, "一般": 0.5}.get(company_tier, 0.5)
    edu_score = {"博士": 0.95, "硕士": 0.8, "本科": 0.6, "大专": 0.4}.get(education or "本科", 0.5)
    skill_bonus = min(0.2, len(skills) * 0.02)
    return min(1.0, max(0.0, 0.4 * tier_score + 0.4 * edu_score + 0.2 + skill_bonus))


def normalize_value(raw: float) -> float:
    """将原始价值分归一化到 [0,1]。"""
    return max(0.0, min(1.0, raw))


# =====================================================================
# 因子 2: 岗位匹配度 —— 结构化多维(降级用)
# =====================================================================
MATCH_WEIGHTS = {
    "title": 0.25,
    "skill": 0.30,
    "semantic": 0.35,
    "years": 0.05,
    "edu": 0.05,
}

_EDU_LEVELS = ["大专", "本科", "硕士", "博士"]


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na < 1e-9 or nb < 1e-9:
        return 0.0
    return dot / (na * nb)


def bigram_dice_similarity(a: Optional[str], b: Optional[str]) -> Optional[float]:
    a = (a or "").strip().lower()
    b = (b or "").strip().lower()
    if not a or not b:
        return None
    if len(a) < 2 or len(b) < 2:
        return 1.0 if a == b else 0.0
    sa = {a[i:i + 2] for i in range(len(a) - 1)}
    sb = {b[i:i + 2] for i in range(len(b) - 1)}
    inter = len(sa & sb)
    if inter == 0:
        return 0.0
    return 2.0 * inter / (len(sa) + len(sb))


def skill_coverage(jd_keywords: Sequence[str],
                   talent_keywords: Sequence[str]) -> float:
    """技能匹配度(0~1): Jaccard 相似度，避免长 JD 惩罚。

    旧实现是 covered_jd_keywords / len(jd_keywords)，JD 越长分母越大，
    导致大部分人才分数被压到 0.05 以下。改为双向 Jaccard：
      score = |intersection| / |union|
    只要人才有任意技能命中 JD，就能拿到合理分数，且天然 ∈ [0,1]。
    """
    jd_set = {k.strip().lower() for k in jd_keywords if k and len(k.strip()) >= 2}
    talent_set = {k.strip().lower() for k in talent_keywords if k and k.strip()}
    if not jd_set and not talent_set:
        return 0.5
    if not jd_set or not talent_set:
        return 0.0
    inter = jd_set & talent_set
    union = jd_set | talent_set
    if not union:
        return 0.5
    return len(inter) / len(union)


def extract_years_requirement(jd_text: Optional[str]) -> Optional[float]:
    import re
    if not jd_text:
        return None
    m = re.search(r"(\d+)\s*年(?:以上)?", jd_text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def extract_edu_requirement(jd_text: Optional[str]) -> Optional[str]:
    if not jd_text:
        return None
    for edu in _EDU_LEVELS:
        if edu in jd_text:
            return edu
    return None


def years_fit(talent_work_years: Optional[float],
              jd_years: Optional[float]) -> Optional[float]:
    if jd_years is None or jd_years <= 0:
        return None
    if talent_work_years is None:
        return 0.9
    if talent_work_years >= jd_years:
        return 1.0
    return max(0.2, min(0.9, talent_work_years / jd_years))


def edu_fit(talent_education: Optional[str],
            jd_edu: Optional[str]) -> Optional[float]:
    if jd_edu is None:
        return None
    if jd_edu not in _EDU_LEVELS:
        return None
    if not talent_education:
        return 0.9
    talent_lvl = None
    for i, edu in enumerate(_EDU_LEVELS):
        if edu in talent_education:
            talent_lvl = i
            break
    if talent_lvl is None:
        return 0.9
    gap = _EDU_LEVELS.index(jd_edu) - talent_lvl
    if gap <= 0:
        return 1.0
    return max(0.4, 1.0 - 0.2 * gap)


def match_score_structured(
    position_name: Optional[str],
    jd_text: Optional[str],
    jd_keywords: Optional[Sequence[str]],
    talent_position: Optional[str],
    talent_skills: Optional[Sequence[str]],
    talent_tags: Optional[Sequence[str]],
    talent_work_years: Optional[float],
    talent_education: Optional[str],
    jd_embedding: Optional[Sequence[float]] = None,
    resume_embedding: Optional[Sequence[float]] = None,
    title_semantic: Optional[float] = None,
) -> float:
    """岗位匹配度结构化五维(降级通道) ∈ [0,1]。"""
    if title_semantic is not None:
        title_sub = max(0.0, min(1.0, title_semantic))
    else:
        title_sub = bigram_dice_similarity(position_name, talent_position)

    subs: dict[str, Optional[float]] = {
        "title": title_sub,
        "skill": skill_coverage(
            jd_keywords or [], list(talent_skills or []) + list(talent_tags or [])
        ),
        "semantic": None,
        "years": years_fit(talent_work_years, extract_years_requirement(jd_text)),
        "edu": edu_fit(talent_education, extract_edu_requirement(jd_text)),
    }
    if jd_embedding and resume_embedding:
        subs["semantic"] = max(0.0, min(
            1.0, cosine_similarity(jd_embedding, resume_embedding)))

    # 权重自动归一：即使部分维度缺失，剩余维度权重也会按比例放大，
    # 避免"缺一个维度就整体打折"的问题。
    total_w, total = 0.0, 0.0
    for dim, sub in subs.items():
        if sub is None:
            continue
        w = MATCH_WEIGHTS.get(dim, 0.0)
        total_w += w
        total += w * sub
    if total_w <= 1e-9:
        return 0.5

    # 基础分 + 加权子维度，确保分布均匀 ∈ [0,1]
    # 基础分 0.3 保证无任何匹配时也有合理分数，0.7 为子维度贡献
    base = 0.3
    weighted = total / total_w  # ∈ [0,1]
    return max(0.0, min(1.0, base + 0.7 * weighted))
