"""简历评估打分引擎（黑客松 R3 · Shanon 规则）。

输入：简历文本 + JD 文本（可选维度权重配置）
输出：100 分制逐维度打分（折算为 X.X/10）、封顶规则、分档、推荐语。

设计原则：
- 确定性规则优先（关键词 / 正则 / 证据表），不依赖外部 LLM API。
- 预留可选 LLM 增强钩子（``llm_enhancer``），默认关闭。
- 可独立 import / CLI 使用，不依赖 FastAPI。

维度权重来源（优先级从高到低）：
1. 调用方显式传入 ``weights_config``（[{"name","weight","keywords","core"}]）。
2. JD 文本中显式写出的权重行，如「供应链业财 40」/「硬件行业：20分」。
3. 内置主题库匹配 JD：按主题关键词命中数取 Top5 维度，权重按命中占比归一。
4. 通用兜底模板（核心技能 40 / 行业背景 20 / 管理能力 15 / 教育背景 15 / 稳定性 10）。

封顶规则：任何核心维度（core=True，默认权重最高维度）得分 < 4.0/10
视为「缺核心经验证据」，总分封顶 6.0——光环背景（名校/名企）不能替代核心能力。

CLI：
    PYTHONPATH=candidate-collector .venv/bin/python -m resume_scorer resume.txt jd.txt
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Callable


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class Dimension:
    name: str
    weight: float                      # 0-100，各维度合计 100
    keywords: list[str] = field(default_factory=list)
    core: bool = False                 # 核心维度：缺证据时触发总分封顶
    strong_keywords: list[str] = field(default_factory=list)  # 强匹配关键词（双倍权重）


@dataclass
class DimScore:
    name: str
    weight: float
    score: float                       # 0-10
    weighted: float                    # score/10 * weight
    hits: list[str]
    evidence: list[str]
    core: bool


# 分档
TIER_KEY = "key"          # ≥8.5 重点推荐
TIER_RECOMMEND = "recommend"   # 7.0–8.4 可推荐
TIER_BORDERLINE = "borderline" # 6.0–6.9 临界
TIER_REJECT = "reject"         # <6 不推荐

TIER_LABELS = {
    TIER_KEY: "重点推荐",
    TIER_RECOMMEND: "可推荐",
    TIER_BORDERLINE: "临界·不主动推荐",
    TIER_REJECT: "不推荐",
}

CORE_CAP = 6.0            # 缺核心经验证据时总分封顶
CORE_MIN_SCORE = 4.0      # 核心维度低于该分（/10）视为缺证据


# ---------------------------------------------------------------------------
# 主题库：JD 自动推维度用
# ---------------------------------------------------------------------------

THEME_LIBRARY: dict[str, dict[str, Any]] = {
    "供应链业财": {
        "keywords": ["供应链", "业财", "采购", "物流", "库存", "成本核算", "进销存", "仓储", "计划"],
        "strong": ["供应链财务", "业财融合", "业财一体"],
    },
    "硬件行业经验": {
        "keywords": ["硬件", "电子", "半导体", "芯片", "消费电子", "智能硬件", "制造业", "工厂", "IoT", "物联网"],
        "strong": ["硬件行业", "消费电子", "半导体"],
    },
    "预算与经营管理": {
        "keywords": ["预算", "经营分析", "经营计划", "滚动预测", "forecast", "损益", "P&L", "财务分析", "FP&A", "费用管控"],
        "strong": ["全面预算", "预算管理", "经营管理"],
    },
    "海外财务": {
        "keywords": ["海外", "跨境", "国际", "外汇", "境外", "出海", "英文", "英语", "US GAAP", "IFRS", "转移定价"],
        "strong": ["海外财务", "跨境业务", "国际准则"],
    },
    "一号位/管理能力": {
        "keywords": ["财务负责人", "CFO", "财务总监", "一号位", "团队管理", "搭建团队", "从0到1", "0-1", "体系搭建", "直接向CEO"],
        "strong": ["财务一号位", "财务负责人", "CFO"],
    },
    "财务专业资质": {
        "keywords": ["CPA", "注册会计师", "ACCA", "中级会计师", "高级会计师", "税务师", "CMA", "审计", "四大", "普华永道", "德勤", "安永", "毕马威"],
        "strong": ["CPA", "ACCA"],
    },
    "战略咨询经验": {
        "keywords": ["战略", "咨询", "行业研究", "商业分析", "市场研究", "麦肯锡", "贝恩", "BCG", "罗兰贝格"],
        "strong": ["战略咨询", "管理咨询"],
    },
    "消费/零售行业": {
        "keywords": ["消费", "零售", "电商", "品牌", "快消", "食品饮料", "美妆", "门店", "渠道"],
        "strong": ["消费品", "新零售"],
    },
    "互联网/技术背景": {
        "keywords": ["互联网", "产品", "算法", "数据", "增长", "研发", "工程", "AI", "机器学习", "SaaS"],
        "strong": ["大厂", "头部互联网"],
    },
    "教育背景": {
        "keywords": ["本科", "硕士", "MBA", "博士", "985", "211", "双一流", "留学", "名校", "学历"],
        "strong": ["985", "MBA"],
    },
}

# 通用兜底模板
GENERIC_TEMPLATE: list[dict[str, Any]] = [
    {"name": "核心技能经验", "weight": 40, "core": True},
    {"name": "行业背景匹配", "weight": 20, "core": False},
    {"name": "管理与协作能力", "weight": 15, "core": False},
    {"name": "教育背景与资质", "weight": 15, "core": False},
    {"name": "稳定性与软素质", "weight": 10, "core": False},
]

# 财务负责人样例模板（需求文档 R3 样例，JD 命中财务负责人/CFO 时启用）
FINANCE_HEAD_TEMPLATE: list[dict[str, Any]] = [
    {"name": "供应链业财", "weight": 40, "core": True,
     "keywords": THEME_LIBRARY["供应链业财"]["keywords"], "strong_keywords": THEME_LIBRARY["供应链业财"]["strong"]},
    {"name": "硬件行业经验", "weight": 20, "core": False,
     "keywords": THEME_LIBRARY["硬件行业经验"]["keywords"], "strong_keywords": THEME_LIBRARY["硬件行业经验"]["strong"]},
    {"name": "预算与经营管理", "weight": 15, "core": False,
     "keywords": THEME_LIBRARY["预算与经营管理"]["keywords"], "strong_keywords": THEME_LIBRARY["预算与经营管理"]["strong"]},
    {"name": "海外财务", "weight": 15, "core": False,
     "keywords": THEME_LIBRARY["海外财务"]["keywords"], "strong_keywords": THEME_LIBRARY["海外财务"]["strong"]},
    {"name": "一号位/管理能力", "weight": 10, "core": False,
     "keywords": THEME_LIBRARY["一号位/管理能力"]["keywords"], "strong_keywords": THEME_LIBRARY["一号位/管理能力"]["strong"]},
]

# 光环背景（只加分，不能替代核心能力）
HALO_COMPANIES = [
    "华为", "腾讯", "阿里巴巴", "字节跳动", "苹果", "小米", "美的", "海尔", "大疆",
    "宝洁", "联合利华", "麦肯锡", "贝恩", "波士顿咨询", "BCG", "高盛", "中金",
    "普华永道", "德勤", "安永", "毕马威",
]
HALO_SCHOOLS = ["清华", "北大", "复旦", "交通大学", "浙江大学", "中国人民大学", "985", "常春藤", "牛津", "剑桥", "斯坦福"]

# 低匹配信号
LOW_SIGNAL_RULES: list[tuple[str, str]] = [
    (r"(?:\d{4}[./年-]\s*){4,}", "工作经历碎片化，疑似频繁跳槽"),
    (r"待业|空窗|自由职业", "存在职业空窗/自由职业经历"),
    (r"应届|实习生", "应届/实习背景，经验年限可能不足"),
]

ACTION_VERBS = ["负责", "主导", "搭建", "推动", "管理", "完成", "实现", "落地", "牵头", "建立", "优化", "带领", "统筹"]
RESULT_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:万|亿|%|元|人|倍)|增长|提升|下降|节约|达成|降低|缩短|扭亏")

MAX_EVIDENCE_PER_DIM = 3
RECOMMEND_MAX_CHARS = 300


# ---------------------------------------------------------------------------
# JD 解析 → 维度权重
# ---------------------------------------------------------------------------

def _parse_explicit_weight_lines(jd_text: str) -> list[dict[str, Any]]:
    """解析 JD 中显式写出的权重行，如「供应链业财 40」「硬件行业：20分」「预算经营 15%」。"""
    dims: list[dict[str, Any]] = []
    for line in jd_text.splitlines():
        match = re.match(
            r"^\s*(?:[-*•·\d.、]+\s*)?([^\s:：，,。；;（(]{2,20})\s*[:：]?\s*(\d{1,3})\s*(?:分|%|权重)?\s*$",
            line.strip(),
        )
        if not match:
            continue
        name, weight = match.group(1), int(match.group(2))
        if weight <= 0 or weight > 100:
            continue
        dims.append({"name": name, "weight": weight})
    total = sum(d["weight"] for d in dims)
    if len(dims) >= 2 and 60 <= total <= 140:
        # 归一到 100
        for d in dims:
            d["weight"] = round(d["weight"] * 100 / total, 1)
        return dims
    return []


def _extract_jd_terms(jd_text: str, limit: int = 12) -> list[str]:
    """从 JD 中抽取候选关键词：顿号/斜杠分隔的术语、引号内术语、高频 2-6 字词。"""
    terms: list[str] = []

    def add(term: str) -> None:
        term = term.strip(" ，,。；;：:、（）()【】[]\"'“”")
        if 2 <= len(term) <= 8 and term not in terms and not re.fullmatch(r"[\d.]+", term):
            terms.append(term)

    for quoted in re.findall(r"[「\"'“]([^「」\"'“”]{2,8})[」\"'”]", jd_text):
        add(quoted)
    for line in jd_text.splitlines():
        if any(marker in line for marker in ("经验", "优先", "熟练", "熟悉", "要求", "具备")):
            for chunk in re.split(r"[、/，,。；;：:（）()\s]+", line):
                add(chunk)
    # 高频中文术语
    freq: dict[str, int] = {}
    for token in re.findall(r"[一-龥]{2,6}", jd_text):
        freq[token] = freq.get(token, 0) + 1
    for token, count in sorted(freq.items(), key=lambda kv: -kv[1]):
        if count >= 2:
            add(token)
        if len(terms) >= limit * 2:
            break
    return terms[:limit]


def _theme_dims_from_jd(jd_text: str) -> list[dict[str, Any]]:
    """用主题库匹配 JD，取 Top5 主题作为维度，权重按命中占比归一。"""
    scored: list[tuple[str, int]] = []
    for theme, spec in THEME_LIBRARY.items():
        hits = sum(1 for kw in spec["keywords"] + spec["strong"] if kw.lower() in jd_text.lower())
        if hits:
            scored.append((theme, hits))
    scored.sort(key=lambda kv: -kv[1])
    if not scored:
        return []
    top = scored[:5]
    total = sum(h for _, h in top)
    dims: list[dict[str, Any]] = []
    for index, (theme, hits) in enumerate(top):
        weight = max(5, round(hits * 100 / total / 5) * 5)
        dims.append({
            "name": theme,
            "weight": weight,
            "core": index == 0,
            "keywords": THEME_LIBRARY[theme]["keywords"],
            "strong_keywords": THEME_LIBRARY[theme]["strong"],
        })
    _normalize_weights(dims)
    return dims


def _normalize_weights(dims: list[dict[str, Any]]) -> None:
    total = sum(d["weight"] for d in dims) or 1
    factor = 100 / total
    for d in dims:
        d["weight"] = round(d["weight"] * factor, 1)
    drift = round(100 - sum(d["weight"] for d in dims), 1)
    if dims:
        dims[0]["weight"] = round(dims[0]["weight"] + drift, 1)


def _theme_keywords_for(name: str) -> tuple[list[str], list[str]]:
    """维度名命中主题库（精确或互相包含）时，返回该主题的关键词与强关键词。"""
    if name in THEME_LIBRARY:
        spec = THEME_LIBRARY[name]
        return list(spec["keywords"]), list(spec["strong"])
    for theme, spec in THEME_LIBRARY.items():
        if theme in name or name in theme:
            return list(spec["keywords"]), list(spec["strong"])
    return [], []


def build_dimensions(
    jd_text: str,
    weights_config: list[dict[str, Any]] | None = None,
) -> tuple[list[Dimension], str]:
    """从 JD 推出维度权重。返回 (维度列表, 来源说明)。"""
    raw: list[dict[str, Any]]
    source: str

    if weights_config:
        raw = [dict(d) for d in weights_config]
        source = "用户显式权重配置"
        _normalize_weights(raw)
    else:
        raw = _parse_explicit_weight_lines(jd_text)
        if raw:
            source = "JD 中显式权重行"
        elif re.search(r"财务负责人|财务总监|CFO|财务一号位", jd_text, re.I):
            raw = [dict(d) for d in FINANCE_HEAD_TEMPLATE]
            source = "内置模板：财务负责人样例（供应链业财40/硬件20/预算15/海外15/一号位10）"
        else:
            raw = _theme_dims_from_jd(jd_text)
            if raw:
                source = "主题库自动匹配 JD"
            else:
                raw = [dict(d) for d in GENERIC_TEMPLATE]
                source = "通用兜底模板"

    jd_terms = _extract_jd_terms(jd_text)
    dims: list[Dimension] = []
    has_core = any(d.get("core") for d in raw)
    for index, d in enumerate(raw):
        keywords = list(d.get("keywords") or [])
        strong = list(d.get("strong_keywords") or d.get("strong") or [])
        # 维度名命中主题库时补充主题关键词，避免 JD 显式权重行只认维度名精确串
        theme_kw, theme_strong = _theme_keywords_for(d["name"])
        for kw in theme_kw:
            if kw not in keywords:
                keywords.append(kw)
        for kw in theme_strong:
            if kw not in strong:
                strong.append(kw)
        if not keywords:
            # 维度名本身 + 与维度名相关的 JD 术语
            keywords = [t for t in jd_terms if t != d["name"]][:6]
        if d["name"] not in keywords:
            keywords.insert(0, d["name"])
        core = bool(d.get("core")) if has_core else index == 0
        dims.append(Dimension(
            name=d["name"],
            weight=float(d["weight"]),
            keywords=keywords,
            core=core,
            strong_keywords=strong,
        ))
    return dims, source


# ---------------------------------------------------------------------------
# 打分
# ---------------------------------------------------------------------------

def _evidence_lines(text: str, keywords: list[str], limit: int = MAX_EVIDENCE_PER_DIM) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if 6 <= len(line.strip()) <= 300]
    matches: list[str] = []
    for line in lines:
        lower = line.lower()
        if any(kw.lower() in lower for kw in keywords):
            matches.append(line)
            if len(matches) >= limit:
                break
    return matches


def _score_dimension(text: str, dim: Dimension) -> DimScore:
    lower = text.lower()
    normal_hits = [kw for kw in dim.keywords if kw.lower() in lower]
    strong_hits = [kw for kw in dim.strong_keywords if kw.lower() in lower]
    effective = len(normal_hits) + 2 * len(strong_hits)
    if effective == 0:
        score = 0.0
    else:
        score = min(10.0, 2.5 + 1.5 * effective)
    evidence = _evidence_lines(text, dim.keywords + dim.strong_keywords)
    weighted = round(score / 10 * dim.weight, 2)
    return DimScore(
        name=dim.name,
        weight=dim.weight,
        score=round(score, 1),
        weighted=weighted,
        hits=normal_hits + strong_hits,
        evidence=evidence,
        core=dim.core,
    )


def _halo_signals(text: str) -> list[str]:
    signals = [f"光环公司：{name}" for name in HALO_COMPANIES if name in text]
    signals += [f"光环院校：{name}" for name in HALO_SCHOOLS if name in text]
    return signals


def _low_signals(text: str) -> list[str]:
    signals: list[str] = []
    for pattern, label in LOW_SIGNAL_RULES:
        if re.search(pattern, text):
            signals.append(label)
            break
    return signals


def _experience_years_gap(resume_text: str, jd_text: str) -> str | None:
    req = re.search(r"(\d{1,2})\s*年以上", jd_text)
    have = re.search(r"(\d{1,2}(?:\.\d+)?)\s*年(?:工作|相关)?经验", resume_text)
    if req and have and float(have.group(1)) < int(req.group(1)):
        return f"JD 要求 {req.group(1)} 年以上，简历标注 {have.group(1)} 年经验"
    return None


def _tier(overall: float) -> str:
    if overall >= 8.5:
        return TIER_KEY
    if overall >= 7.0:
        return TIER_RECOMMEND
    if overall >= 6.0:
        return TIER_BORDERLINE
    return TIER_REJECT


def _strengths_and_gaps(dim_scores: list[DimScore]) -> tuple[list[str], list[str], list[str]]:
    strengths, gaps, questions = [], [], []
    for ds in dim_scores:
        if ds.score >= 7.0:
            strengths.append(f"{ds.name}（{ds.score}/10）：{ds.evidence[0] if ds.evidence else '、'.join(ds.hits[:3])}")
        elif ds.score < 4.0:
            gaps.append(f"{ds.name}：简历中未找到有效证据")
            questions.append(f"{ds.name}经验是否属实？请面试核实具体项目与结果")
        elif ds.score < 7.0:
            questions.append(f"{ds.name}证据不够充分（{ds.score}/10），建议核实深度")
    return strengths, gaps, questions


def _recommendation_text(
    resume_text: str,
    dim_scores: list[DimScore],
    candidate_name: str = "",
) -> str:
    """规则生成推荐语：3-4 条、≤300 字、「亮点背景+关键动作+具体结果」。"""
    lines = [line.strip() for line in resume_text.splitlines() if 8 <= len(line.strip()) <= 120]

    background = ""
    for line in lines:
        if re.search(r"(公司|集团|科技|有限)", line) and re.search(
            r"(总监|负责人|经理|CFO|VP|主管|顾问|工程师|分析师)", line
        ):
            background = line
            break
    if not background and lines:
        background = lines[0]

    actions = [line for line in lines if any(v in line for v in ACTION_VERBS)]
    results = [line for line in lines if RESULT_RE.search(line)]

    bullets: list[str] = []
    if background:
        bullets.append(f"背景亮点：{background}")
    for line in actions[:2]:
        if line != background:
            bullets.append(f"关键动作：{line}")
    for line in results[:2]:
        if line != background and line not in actions[:2]:
            bullets.append(f"具体结果：{line}")

    # 补充高得分维度作为兜底
    for ds in sorted(dim_scores, key=lambda d: -d.weighted):
        if len(bullets) >= 3:
            break
        if ds.score >= 7 and ds.evidence and not any(ds.evidence[0] in b for b in bullets):
            bullets.append(f"{ds.name}：{ds.evidence[0]}")

    bullets = bullets[:4]
    text = "\n".join(f"{i}. {b}" for i, b in enumerate(bullets, 1))
    if len(text) > RECOMMEND_MAX_CHARS:
        text = text[: RECOMMEND_MAX_CHARS - 1].rstrip("，,。；; ") + "…"
    prefix = f"推荐语（{candidate_name}）：\n" if candidate_name else "推荐语：\n"
    return prefix + text


def _relative_position(overall: float, history: list[float]) -> str:
    if not history:
        return "本次第 1 份评估，暂无相对位置"
    below = sum(1 for h in history if h < overall)
    pct = round(below / len(history) * 100)
    rank = sum(1 for h in history if h > overall) + 1
    return f"在已评 {len(history) + 1} 份简历中排第 {rank}，超过 {pct}% 人选"


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def score_resume(
    resume_text: str,
    jd_text: str,
    weights_config: list[dict[str, Any]] | None = None,
    candidate_name: str = "",
    history: list[float] | None = None,
    llm_enhancer: Callable[[dict[str, Any], str, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """对一份简历按 JD 打分。返回结构化结果（见 format_text 可生成可读文本）。

    ``llm_enhancer``：可选 LLM 增强钩子，签名 (result, resume_text, jd_text) -> result，
    默认 None（关闭），传入时其返回值替换规则结果。
    """
    if not resume_text or len(resume_text.strip()) < 10:
        raise ValueError("简历文本过短，无法评估")
    dims, dim_source = build_dimensions(jd_text, weights_config)
    dim_scores = [_score_dimension(resume_text, dim) for dim in dims]

    raw_total = sum(ds.weighted for ds in dim_scores)  # 0-100
    overall = raw_total / 10                            # 折算为 X.X/10

    # 光环加分：名校/名企背景加分，但受封顶规则约束，不能替代核心能力
    halo = _halo_signals(resume_text)
    halo_bonus = round(min(1.5, 0.5 * len(halo)), 1)
    overall += halo_bonus

    # 封顶规则：缺核心经验证据 → 总分封顶 CORE_CAP
    core_dims = [ds for ds in dim_scores if ds.core]
    weak_cores = [ds for ds in core_dims if ds.score < CORE_MIN_SCORE]
    cap_applied = bool(weak_cores)
    if cap_applied:
        overall = min(overall, CORE_CAP)
    overall = round(max(0.0, min(10.0, overall)), 1)

    tier = _tier(overall)
    strengths, gaps, questions = _strengths_and_gaps(dim_scores)
    low = _low_signals(resume_text)
    gap_note = _experience_years_gap(resume_text, jd_text)
    if gap_note:
        low.append(gap_note)

    strong_keywords = sorted({kw for ds in dim_scores for kw in ds.hits if ds.score >= 6})
    priority_backgrounds = halo[:6]

    if cap_applied:
        gaps.insert(0, "缺核心经验证据，触发总分封顶（≤6.0）：光环背景不能替代核心能力")

    recommendation = _recommendation_text(resume_text, dim_scores, candidate_name) if overall >= 7.0 else ""
    if overall < 6.0:
        mismatch = "；".join(g.name + "不匹配" for g in dim_scores if g.score < 4.0) or "综合匹配度不足"
    else:
        mismatch = ""

    hist = list(history or [])
    relative = _relative_position(overall, hist)

    result: dict[str, Any] = {
        "overall": overall,
        "overall_100": round(raw_total, 1),
        "tier": tier,
        "tier_label": TIER_LABELS[tier],
        "conclusion": _conclusion(overall, tier, cap_applied),
        "cap_applied": cap_applied,
        "cap_rule": f"核心维度得分<{CORE_MIN_SCORE}/10 时总分封顶 {CORE_CAP}",
        "halo_bonus": halo_bonus,
        "dimension_source": dim_source,
        "dimensions": [
            {
                "name": ds.name,
                "weight": ds.weight,
                "score": ds.score,
                "weighted": ds.weighted,
                "core": ds.core,
                "hits": ds.hits,
                "evidence": ds.evidence,
            }
            for ds in dim_scores
        ],
        "strong_keywords": strong_keywords,
        "priority_backgrounds": priority_backgrounds,
        "low_match_signals": low,
        "strengths": strengths,
        "gaps": gaps,
        "open_questions": questions,
        "mismatch_reason": mismatch,
        "relative_position": relative,
        "recommendation": recommendation,
        "candidate_name": candidate_name,
    }
    result["report"] = format_text(result)

    if llm_enhancer is not None:
        enhanced = llm_enhancer(result, resume_text, jd_text)
        if isinstance(enhanced, dict):
            enhanced.setdefault("report", format_text(enhanced))
            return enhanced
    return result


def _conclusion(overall: float, tier: str, cap_applied: bool) -> str:
    if tier == TIER_KEY:
        return "综合匹配度高，重点推荐，建议尽快安排客户面试"
    if tier == TIER_RECOMMEND:
        return "综合匹配度良好，可推荐给客户"
    if tier == TIER_BORDERLINE:
        note = "（核心经验证据不足，已触发封顶）" if cap_applied else ""
        return f"临界人选{note}，不主动推荐，列出缺口供顾问判断"
    return "匹配度不足，暂不推荐"


def format_text(result: dict[str, Any]) -> str:
    """生成固定格式的可读报告。"""
    lines: list[str] = []
    name = result.get("candidate_name") or "该候选人"
    lines.append(f"===== 简历评估报告 · {name} =====")
    lines.append(f"综合匹配度：{result['overall']}/10 —— {result['tier_label']}")
    lines.append(f"结论：{result['conclusion']}")
    if result.get("cap_applied"):
        lines.append(f"⚠ 已触发封顶规则：{result['cap_rule']}")
    lines.append(f"维度权重来源：{result.get('dimension_source', '')}")
    lines.append("")
    lines.append("【各维度得分及简历证据】")
    for d in result["dimensions"]:
        core_mark = "（核心）" if d.get("core") else ""
        lines.append(f"· {d['name']}{core_mark} 权重{d['weight']}：{d['score']}/10")
        for ev in d.get("evidence", []):
            lines.append(f"    证据：{ev}")
        if not d.get("evidence"):
            lines.append("    证据：未找到")
    lines.append("")
    lines.append("【核心优势】")
    strengths = result.get("strengths", [])
    lines.extend([f"· {s}" for s in strengths] or ["· 无突出优势"])
    lines.append("【关键缺口】")
    gaps = result.get("gaps", [])
    lines.extend([f"· {g}" for g in gaps] or ["· 无明显缺口"])
    lines.append("【待验证问题】")
    questions = result.get("open_questions", [])
    lines.extend([f"· {q}" for q in questions] or ["· 无"])
    lines.append("")
    lines.append("【一眼识别】")
    if result.get("strong_keywords"):
        lines.append("强匹配关键词：" + "、".join(result["strong_keywords"]))
    if result.get("priority_backgrounds"):
        lines.append("优先公司/背景：" + "、".join(result["priority_backgrounds"]))
    if result.get("low_match_signals"):
        lines.append("低匹配信号：" + "、".join(result["low_match_signals"]))
    lines.append("")
    lines.append(f"【相对位置】{result.get('relative_position', '')}")
    if result.get("recommendation"):
        lines.append("")
        lines.append("【推荐语】")
        lines.append(result["recommendation"])
    elif result.get("mismatch_reason"):
        lines.append("")
        lines.append(f"【不匹配原因】{result['mismatch_reason']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="简历评估打分（黑客松 R3）")
    parser.add_argument("resume", help="简历文本文件路径")
    parser.add_argument("jd", help="JD 文本文件路径")
    parser.add_argument("--weights", help="维度权重 JSON 文件（可选）")
    parser.add_argument("--json", action="store_true", help="输出 JSON 而非可读报告")
    args = parser.parse_args(argv)

    resume_text = open(args.resume, encoding="utf-8").read()
    jd_text = open(args.jd, encoding="utf-8").read()
    weights = json.load(open(args.weights, encoding="utf-8")) if args.weights else None
    result = score_resume(resume_text, jd_text, weights_config=weights)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result["report"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
