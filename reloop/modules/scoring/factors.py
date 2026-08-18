"""触达优先级五因子量化算法。

公式: 触达优先级 = 活跃度 × 岗位匹配度 × 人才价值 × 历史关系 × 求职可能性
每个因子归一化到 [0,1], 再进入加权乘法模型(见 priority.py)。

外部活跃信号(飞书在线/简历平台浏览等)已移除——
活跃度因子现在只来自两类站内可得信号:
  1. TTC 平台上人才的最近活跃/更新时间 (talent_profiles.last_active_at)
  2. 顾问在 Reloop 内与人才的互动记录 (interaction_records)
"""

import datetime as dt
import math
from typing import Iterable, Optional, Sequence

from reloop.config import settings


# =====================================================================
# 因子 1: 活跃度 —— 牛顿冷却定律
#   Score = Σ( 事件权重 * e^(-λ * 距今天数) ),  λ 默认 0.1
#   事件权重: 平台活跃=6, 档案更新=10, 面试=8, 通话=5, 消息=2
#   批量 Min-Max 归一化到 [0,1]
# =====================================================================
EVENT_WEIGHTS = {
    "platform_active": 6.0,   # TTC 平台最近活跃
    "profile_update": 10.0,   # 档案/简历更新
    "interview": 8.0,         # 站内记录的面试互动
    "call": 5.0,              # 站内记录的通话互动
    "message": 2.0,           # 站内记录的消息互动
}

# 批量归一化因子的下限(活跃度/历史关系), 防止小样本下乘法模型误杀
FACTOR_FLOOR = 0.05


def activity_score(events: Iterable[dict], now: Optional[dt.datetime] = None,
                   decay: Optional[float] = None) -> float:
    """计算单人才的原始活跃度(冷却前)。

    events: [{"event_type": "profile_update", "weight": 10(可选),
              "occurred_at": datetime}, ...]
    返回原始分(未归一化); 调用方对一批人才做 min-max 归一化。
    """
    if now is None:
        now = dt.datetime.now()
    if decay is None:
        decay = settings.activity_decay

    total = 0.0
    for ev in events:
        w = ev.get("weight") or EVENT_WEIGHTS.get(ev.get("event_type", ""), 1.0)
        occurred = ev.get("occurred_at")
        if occurred is None:
            continue
        if isinstance(occurred, str):
            occurred = dt.datetime.fromisoformat(occurred)
        days = max((now - occurred).total_seconds() / 86400.0, 0.0)
        total += w * math.exp(-decay * days)
    return total


def build_activity_events(last_active_at=None,
                          interactions: Iterable[dict] = ()) -> list[dict]:
    """把画像的活跃来源拼成事件列表。

    last_active_at: TTC 平台最近活跃时间 -> platform_active 事件
    interactions:   [{"interaction_type": "call", "occurred_at": date/datetime}, ...]
    """
    events = []
    if last_active_at is not None:
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
    """Min-Max 归一化到 [FACTOR_FLOOR,1]。

    边界处理(修复冷启动白送分):
      - 全部为 0(真的没有活跃/没有关系, 冷启动最常见): 返回全 FACTOR_FLOOR,
        不再当成"中等 0.5"给所有人白送分, 保留区分度。
      - 全部相等但非 0(都有相同强度的信号): 返回全 0.5(中性)。
      - 其余: 正常 min-max, 且下限抬到 FACTOR_FLOOR 避免乘法模型误杀。
    """
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        # 全相等: 区分"全为 0"与"全为相同非零值"
        if hi < 1e-9:
            return [FACTOR_FLOOR] * len(values)  # 全 0 -> 不白送分
        return [0.5] * len(values)               # 全相等非 0 -> 中性
    return [max(FACTOR_FLOOR, (v - lo) / (hi - lo)) for v in values]


# =====================================================================
# 因子 2: 岗位匹配度 —— 余弦相似度
#   Cosine(JD_embedding, Resume_embedding) ∈ [-1,1] -> 线性映射到 [0,1]
#   向量以 JSON 存 MySQL, 相似度在应用层计算(RDS 无向量类型)
# =====================================================================
def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na < 1e-9 or nb < 1e-9:
        return 0.0
    return dot / (na * nb)


def match_score(jd_embedding: Sequence[float],
                resume_embedding: Sequence[float]) -> float:
    """岗位匹配度 ∈ [0,1]。

    改进(修复离线哈希向量把最高权重因子退化成常数 0.5):
    改用 max(0, cos) 而非线性 (cos+1)/2 ——
      - 离线哈希向量非负, cos∈[0,1]: 无共同词 -> cos≈0 -> match≈0(不匹配就该低分),
        有共同词 -> match 随重叠度上升, 区分度真实。
      - 真实 embedding cos∈[-1,1]: 负相关(不相关)截断为 0, 语义上也正确。
    这样"活跃但与岗位不匹配"的噪声候选人会被乘法模型真正压低, 而不是恒得 0.5。
    """
    cos = cosine_similarity(jd_embedding, resume_embedding)
    return max(0.0, min(1.0, cos))


# =====================================================================
# 因子 3: 人才价值 —— 静态分(公司等级 + 学历 + 稀缺技能) -> 归一化到 [0,1]
# =====================================================================
COMPANY_TIER = {
    "大厂": 10.0,
    "独角兽": 8.0,
    "上市公司": 7.0,
    "一般": 5.0,
}
EDUCATION_TIER = {
    "博士": 10.0,
    "硕士": 8.0,
    "本科": 6.0,
    "大专": 4.0,
}
# 稀缺技能加分(可按行业扩展)
SCARCE_SKILLS = {"AI训练师": 2.0, "大模型": 2.0, "量化": 1.5, "算法": 1.0}


def raw_value_score(company_tier: str = "一般", education: str = "本科",
                    skills: Optional[Sequence[str]] = None) -> float:
    """原始人才价值分(0~22 区间); 调用方做归一化。"""
    base = COMPANY_TIER.get(company_tier, 5.0)
    base += EDUCATION_TIER.get(education, 6.0)
    if skills:
        base += sum(SCARCE_SKILLS.get(s, 0.0) for s in skills)
    return base


def normalize_value(raw: float, lo: float = 0.0, hi: float = 22.0) -> float:
    return max(0.0, min(1.0, (raw - lo) / (hi - lo)))


# =====================================================================
# 因子 4: 历史关系 —— 近 3 个月互动频次加权后批量 Min-Max 归一化
#   频次 = 面试次数×3 + 通话次数×2 + 消息条数×0.5
# =====================================================================
INTERACTION_WEIGHTS = {"interview": 3.0, "call": 2.0, "message": 0.5, "note": 0.0}


def raw_relationship_score(interactions: Iterable[dict]) -> float:
    total = 0.0
    for it in interactions:
        w = INTERACTION_WEIGHTS.get(it.get("interaction_type", ""), 0.0)
        total += w * (it.get("count") or 0)
    return total


# =====================================================================
# 因子 5: 求职可能性 —— LLM 文本分析输出 [0,1]; 无记录默认 0.5 中性
# =====================================================================
def tendency_score(llm_score: Optional[float]) -> float:
    if llm_score is None:
        return 0.5
    return max(0.0, min(1.0, float(llm_score)))
