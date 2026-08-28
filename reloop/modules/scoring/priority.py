"""触达优先级综合评分(兼容门面, 蓝图 R1 2026-08-28)。

实现已原样搬迁至 `reloop/core/scoring.py`(纯算法, 零 IO);
本文件仅为兼容旧 import 路径保留转发。
"""

from reloop.core.scoring import (  # noqa: F401
    FactorScores,
    ScoreResult,
    rank_candidates,
    rank_score,
    top_n,
    weighted_product,
)

__all__ = [
    "FactorScores", "ScoreResult", "rank_candidates",
    "rank_score", "top_n", "weighted_product",
]
