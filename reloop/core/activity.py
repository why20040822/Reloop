"""活跃度因子(纯算法, 零 IO)。

蓝图 R1(2026-08-28) 自 modules/scoring/factors.py 原样搬入;
factors.py 保留同名 re-export, 旧 import 路径完全兼容。

v3(2026-08-28): 纯绝对衰减 + 活跃门禁。分事件半衰期牛顿冷却;
批内相对归一化已废除(它是"全员活跃"假分布的算法级放大器)。
"""

import datetime as dt
import math
from typing import Iterable, Optional, Sequence

from reloop.config import settings


# =====================================================================
# 因子 1: 活跃度 —— 分事件半衰期的牛顿冷却 + 纯绝对衰减 (v3)
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
ACTIVITY_ABS_WINDOW = 180.0  # 已弃用: 窗口改由 settings.activity_abs_window 控制(默认 90), 常量保留兼容
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
                      window: Optional[float] = None) -> float:
    """纯绝对活跃分 ∈ [FACTOR_FLOOR, 1]: 距最近事件越近分越高, 超窗口触底。

    v3(2026-08-28): 窗口默认改由配置 BRAINX_ACTIVITY_ABS_WINDOW 控制(默认 90 天)。
    days_since_latest=None(无任何可信时间信号) -> FACTOR_FLOOR, 不冒充活跃。
    """
    if window is None:
        window = settings.activity_abs_window
    if days_since_latest is None:
        return FACTOR_FLOOR
    return max(FACTOR_FLOOR, min(1.0, 1.0 - days_since_latest / window))


def hybrid_activity_normalize(raws: Sequence[float],
                              latest_days: Sequence[Optional[float]],
                              alpha: Optional[float] = None) -> list[float]:
    """活跃度归一化(v3): 纯绝对衰减。

    批内 min-max 相对归一化已废除(2026-08-28): 它保证池内必然有人得 1.0,
    即使全员都不活跃也会造出"活跃分布", 是"全员活跃"失真的算法级放大器。
    保留函数名与签名以兼容旧调用方; raws 参数已不参与计算。
    """
    return [absolute_activity(d) for d in latest_days]


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
