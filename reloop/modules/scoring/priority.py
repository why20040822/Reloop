"""触达优先级综合评分: 加权乘法模型(Weighted Product Model)。

   Score = 活跃度^w1 × 岗位匹配度^w2 × 人才价值^w3 × 历史关系^w4 × 求职可能性^w5

权重默认(可在 .env 调节):
    w1(活跃度)=0.3  w2(岗位匹配度)=0.4  w3(人才价值)=0.15
    w4(历史关系)=0.1 w5(求职可能性)=0.05

乘法模型特性: 任一关键因子趋 0 会显著拉低总分,
"活跃但与岗位不匹配"的噪声候选人会被自然抑制(再配合噪声阈值剔除)。
"""

from dataclasses import dataclass, field
from typing import Optional

from reloop.config import settings


@dataclass
class FactorScores:
    """五因子归一化分值(均 ∈ [0,1])。"""

    activity: float = 0.0
    match: float = 0.0
    value: float = 0.0
    relationship: float = 0.0
    tendency: float = 0.5

    def as_dict(self) -> dict:
        return {
            "activity": round(self.activity, 4),
            "match": round(self.match, 4),
            "value": round(self.value, 4),
            "relationship": round(self.relationship, 4),
            "tendency": round(self.tendency, 4),
        }


@dataclass
class ScoreResult:
    talent_id: int
    score: float
    breakdown: FactorScores = field(default_factory=FactorScores)


def weighted_product(f: FactorScores) -> float:
    """加权乘法模型核心公式。"""
    return (
        (max(f.activity, 1e-6) ** settings.score_w_activity)
        * (max(f.match, 1e-6) ** settings.score_w_match)
        * (max(f.value, 1e-6) ** settings.score_w_value)
        * (max(f.relationship, 1e-6) ** settings.score_w_relation)
        * (max(f.tendency, 1e-6) ** settings.score_w_tendency)
    )


def rank_candidates(candidates: list[tuple[int, FactorScores]]) -> list[ScoreResult]:
    """对一批候选人计算综合分并排序, 剔除低于噪声阈值的。

    candidates: [(talent_id, FactorScores), ...]
    """
    results = [
        ScoreResult(talent_id=tid, score=weighted_product(fs), breakdown=fs)
        for tid, fs in candidates
    ]
    results = [r for r in results if r.score >= settings.score_noise_threshold]
    results.sort(key=lambda r: r.score, reverse=True)
    return results


def top_n(candidates: list[tuple[int, FactorScores]],
          n: Optional[int] = None) -> list[ScoreResult]:
    if n is None:
        n = settings.recommend_top_n
    return rank_candidates(candidates)[:n]
