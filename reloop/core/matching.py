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

_EDU_LEVELS = ["大专", "本科", "硕士", "博士"]


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
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
