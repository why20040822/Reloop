"""触达优先级综合评分: 双因子加权乘法模型(Weighted Product Model)。

   Score = 活跃度^w1 × 岗位匹配度^w2

权重默认(可在 .env 调节):
    w1(活跃度)=0.3  w2(岗位匹配度)=0.4

排序时用户可选择按单一指标 100% 排序, 另一指标仅展示不参与排序。
"""

from dataclasses import dataclass, field
from typing import Optional

from reloop.config import settings


@dataclass
class FactorScores:
    """双因子归一化分值(均 ∈ [0,1])。

    activity_status(v3 活跃门禁 2026-08-28):
      active   = 距最近事件 <= activity_inactive_days
      inactive = 超过门禁天数, 活跃分已乘 activity_gate_penalty 软降权
      unknown  = 无任何可信时间信号, 活跃分触底 FACTOR_FLOOR
    """
    activity: float = 0.0
    match: float = 0.0
    activity_status: str = "active"
    # 改造①可解释性(2026-08-28): 分维度明细+技能命中清单; None 时序列化不含此键
    match_detail: Optional[dict] = None

    def as_dict(self) -> dict:
        d = {
            "activity": round(self.activity, 4),
            "match": round(self.match, 4),
            "activity_status": self.activity_status,
        }
        if self.match_detail:
            d["match_detail"] = self.match_detail
        return d


@dataclass
class ScoreResult:
    talent_id: int
    rank_score: float
    sort_by: str = "match"
    breakdown: FactorScores = field(default_factory=FactorScores)


def weighted_product(f: FactorScores) -> float:
    """双因子加权乘法模型核心公式(用于 ring 展示分)。"""
    return (
        (max(f.activity, 1e-6) ** settings.score_w_activity)
        * (max(f.match, 1e-6) ** settings.score_w_match)
    )


def rank_score(f: FactorScores, sort_by: str = "match",
               w_activity: Optional[float] = None, w_match: Optional[float] = None) -> float:
    """排序用分:
    - sort_by="activity" -> 100% 活跃度
    - sort_by="match" -> 100% 岗位匹配度
    - sort_by="custom" -> w_activity * activity + w_match * match (权重和应为 1)
    """
    if sort_by == "activity":
        return f.activity
    if sort_by == "match":
        return f.match
    if sort_by == "custom":
        wa = w_activity if w_activity is not None else 0.5
        wm = w_match if w_match is not None else 0.5
        return wa * f.activity + wm * f.match
    return f.match


def rank_candidates(candidates: list[tuple[int, FactorScores]],
                    sort_by: str = "match",
                    w_activity: Optional[float] = None,
                    w_match: Optional[float] = None) -> list[ScoreResult]:
    """对一批候选人计算综合分并排序, 剔除低于噪声阈值的。

    candidates: [(talent_id, FactorScores), ...]
    sort_by: "activity" | "match" | "custom"
    w_activity / w_match: custom 模式下的权重(和应为 1)。
    """
    results = [
        ScoreResult(
            talent_id=tid,
            rank_score=rank_score(fs, sort_by, w_activity, w_match),
            sort_by=sort_by,
            breakdown=fs,
        )
        for tid, fs in candidates
    ]
    results = [r for r in results if r.rank_score >= settings.score_noise_threshold]
    results.sort(key=lambda r: r.rank_score, reverse=True)
    return results


def top_n(candidates: list[tuple[int, FactorScores]],
          n: Optional[int] = None,
          sort_by: str = "match") -> list[ScoreResult]:
    if n is None:
        n = settings.recommend_top_n
    return rank_candidates(candidates, sort_by=sort_by)[:n]
