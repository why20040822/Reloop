"""岗位匹配度: 结构化五维(纯算法, 零 IO)。

蓝图 R1(2026-08-28) 自 modules/scoring/factors.py 原样搬入;
factors.py 保留同名 re-export, 旧 import 路径完全兼容。
"""

import math
from typing import Optional, Sequence


MATCH_WEIGHTS = {
    "title": 0.25,
    "skill": 0.30,
    "semantic": 0.35,
    "years": 0.05,
    "edu": 0.05,
}

# 结构化匹配保底分(框架改造①评估项): 0 匹配也有 0.3, 经 0.4 权重混入后
# 全员兜底 +0.12, 压缩区分度。暂保持 0.3 不动(避免与旧缓存分数断裂),
# skill 维换成"覆盖率"后建议复测区分度, 视情调低至 0.1~0.15。
MATCH_BASE_SCORE = 0.3

_EDU_LEVELS = ["大专", "本科", "硕士", "博士"]

# 改造①: 技能别名归一(人才侧 skills 与 JD 侧解析词表对齐)
SKILL_ALIASES = {
    "js": "javascript", "ts": "typescript", "golang": "go",
    "k8s": "kubernetes", "vuejs": "vue", "vue.js": "vue",
    "reactjs": "react", "react.js": "react", "nodejs": "node",
    "node.js": "node", "postgres": "postgresql", "postgresdb": "postgresql",
    "es": "elasticsearch", "springboot": "spring-boot",
}
_SKILL_SUFFIXES = ("开发", "工程师", "相关", "方向", "岗")


def normalize_skill(s: Optional[str]) -> str:
    """单个技能名归一: 小写/去空白/剥常见中文后缀/别名映射。"""
    t = (s or "").strip().lower().replace(" ", "")
    if not t:
        return ""
    for suf in _SKILL_SUFFIXES:
        if len(t) > len(suf) and t.endswith(suf):
            t = t[: -len(suf)]
    return SKILL_ALIASES.get(t, t)


def normalize_skills(items: Optional[Sequence[str]]) -> list[str]:
    """技能列表归一并去重(保序)。"""
    out: list[str] = []
    seen: set[str] = set()
    for s in items or []:
        n = normalize_skill(s)
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    """余弦相似度 ∈ [0,1]; 输入缺失或**维度失配返回 None**(缺失维, 由权重归一
    跳过), 不再返回 0.0 —— 改造②防护: 否则单侧重算后另一侧会被静默清零。"""
    if not a or not b:
        return None
    if len(a) != len(b):
        return None
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na < 1e-9 or nb < 1e-9:
        return None
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

    [旧实现保留] 改造①后主链路改用 skill_coverage_detail(覆盖率+命中清单);
    本函数仅为兼容保留。
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


def skill_coverage_detail(jd_skills: Sequence[str],
                          talent_skills: Sequence[str],
                          ) -> tuple[Optional[float], list[str]]:
    """技能覆盖度(改造①): 覆盖率 = 命中项数 / JD 要求项数, 附命中清单。

    Jaccard 时代的前提(防长 JD 惩罚)在有解析短清单后消失: coverage 更可解释,
    且天然产出"命中 4/6 项: Python、SQL…"。两侧均经 normalize_skills 归一。
    返回 (score, hits); JD 无技能要求时返回 (None, []) —— 视为缺失维,
    由五维权重归一跳过, 而非强行 0 分。
    """
    jd_set = {s for s in normalize_skills(jd_skills) if s}
    tal_set = {s for s in normalize_skills(talent_skills) if s}
    if not jd_set:
        return None, []
    hits = sorted(jd_set & tal_set)
    return len(hits) / len(jd_set), hits


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
    jd_skills: Optional[Sequence[str]] = None,
    years_min: Optional[float] = None,
    edu_min: Optional[str] = None,
) -> float:
    """岗位匹配度结构化五维(降级通道) ∈ [0,1]。

    改造①(2026-08-28): 新增 jd_skills/years_min/edu_min 三个可选入参 ——
    AI 解析产物(jd_analysis)经 core/jd_features 规范化后直通, 不再从原文
    正则重抽; 未提供时保留原文兜底路径。
    """
    return match_score_structured_detail(
        position_name, jd_text, jd_keywords,
        talent_position, talent_skills, talent_tags,
        talent_work_years, talent_education,
        jd_embedding=jd_embedding, resume_embedding=resume_embedding,
        title_semantic=title_semantic,
        jd_skills=jd_skills, years_min=years_min, edu_min=edu_min,
    )["score"]


def match_score_structured_detail(
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
    jd_skills: Optional[Sequence[str]] = None,
    years_min: Optional[float] = None,
    edu_min: Optional[str] = None,
) -> dict:
    """同 match_score_structured, 另返回分维度明细与技能命中清单(可解释性)。"""
    if title_semantic is not None:
        title_sub = max(0.0, min(1.0, title_semantic))
    else:
        title_sub = bigram_dice_similarity(position_name, talent_position)

    # skill 维: 有解析技能清单用覆盖率; 否则退回原文关键词(Jaccard 兼容路径)
    if jd_skills is not None and normalize_skills(jd_skills):
        skill_sub, skill_hits = skill_coverage_detail(
            jd_skills, list(talent_skills or []) + list(talent_tags or []))
    else:
        skill_sub = skill_coverage(
            jd_keywords or [], list(talent_skills or []) + list(talent_tags or []))
        skill_hits = []

    subs: dict[str, Optional[float]] = {
        "title": title_sub,
        "skill": skill_sub,
        "semantic": None,
        # years/edu: 解析字段优先, 原文正则兜底
        "years": years_fit(talent_work_years,
                           years_min if years_min is not None
                           else extract_years_requirement(jd_text)),
        "edu": edu_fit(talent_education,
                       edu_min if edu_min is not None
                       else extract_edu_requirement(jd_text)),
    }
    if jd_embedding and resume_embedding:
        subs["semantic"] = cosine_similarity(jd_embedding, resume_embedding)
        if subs["semantic"] is not None:
            subs["semantic"] = max(0.0, min(1.0, subs["semantic"]))

    # 权重自动归一：即使部分维度缺失，剩余维度权重也会按比例放大，
    # 避免"缺一个维度就整体打折"的问题。
    total_w, total = 0.0, 0.0
    for dim, sub in subs.items():
        if sub is None:
            continue
        w = MATCH_WEIGHTS.get(dim, 0.0)
        total_w += w
        total += w * sub

    # 基础分 + 加权子维度，确保分布均匀 ∈ [0,1]
    # 基础分 0.3 保证无任何匹配时也有合理分数，0.7 为子维度贡献
    if total_w <= 1e-9:
        score = 0.5
    else:
        weighted = total / total_w  # ∈ [0,1]
        score = max(0.0, min(
            1.0, MATCH_BASE_SCORE + (1 - MATCH_BASE_SCORE) * weighted))

    return {
        "score": score,
        "dims": {k: (round(v, 4) if v is not None else None)
                 for k, v in subs.items()},
        "skill_hits": skill_hits,
        "skill_jd_count": len(normalize_skills(jd_skills)) if jd_skills is not None else None,
    }
