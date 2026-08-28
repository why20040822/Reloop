"""触达优先级量化因子(兼容门面)。

蓝图 R1(2026-08-28): 纯算法已搬至 `reloop/core/`(activity / matching / scoring);
本模块保留 人才价值静态分(structuring 落库用, 非核心评分) 并 re-export 原有
全部公开名 —— 旧 import 路径(reloop.modules.scoring.factors)完全兼容。
"""

from typing import Optional

from reloop.config import settings  # noqa: F401  (兼容旧 `from factors import settings` 用法)
from reloop.core.activity import (  # noqa: F401
    ACTIVITY_ABS_WINDOW,
    DEFAULT_HALF_LIFE,
    EVENT_HALF_LIVES,
    EVENT_WEIGHTS,
    FACTOR_FLOOR,
    absolute_activity,
    activity_score,
    build_activity_events,
    days_since_latest_event,
    hybrid_activity_normalize,
    min_max_normalize,
)
from reloop.core.matching import (  # noqa: F401
    MATCH_WEIGHTS,
    bigram_dice_similarity,
    cosine_similarity,
    edu_fit,
    extract_edu_requirement,
    extract_years_requirement,
    match_score_structured,
    skill_coverage,
    years_fit,
)


# =====================================================================
# 遗留: 人才价值静态分 (已从核心评分移除, 仅 structuring.py 写入 DB 用)
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
