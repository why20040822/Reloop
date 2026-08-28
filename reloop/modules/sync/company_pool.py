"""公司人才库补充(v2.1): 看 Reloop 人才信息时, 实时拉公司共享池上同人的最新信息作为补充展示。

- 共享池快照带 TTL 缓存(默认 30 分钟), 避免每次查看都全量拉取
- 快照按 source_id(TTC 人才 ID)索引
- supplement = 公司库最新档案(备注/求职状态/薪资/活跃时间...)
- diff = 公司库最新值 与 Reloop 本地副本 的差异清单(本地落后了什么一目了然)

全程只读, 不写库。数据源: gateway.ttcadvisory.com 共享池(公司人才库, 只读凭据)。
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
from typing import Optional

from reloop.modules.sync.client import TTCClient

logger = logging.getLogger(__name__)

_SNAPSHOT_TTL = dt.timedelta(minutes=30)

_snapshot_lock = threading.Lock()
_snapshot: dict = {"fetched_at": None, "by_sid": {}, "total": 0}

# 补充面板关注的字段(与 TalentProfile 本地字段同名, 便于对比)
_SUPPLEMENT_FIELDS = (
    "notes", "seek_status", "contact_status", "company", "position",
    "current_salary", "expected_salary", "base_location", "skills",
    "last_active_at", "resume_updated_at", "work_years", "education",
)

_DIFF_FIELDS = ("notes", "seek_status", "contact_status", "company", "position",
                "current_salary", "expected_salary")


def _iso(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, dt.datetime | dt.date):
        return value.isoformat()
    return str(value)


def get_shared_snapshot(client: Optional[TTCClient] = None, force: bool = False) -> dict:
    """获取公司共享池快照(带 TTL 缓存)。返回 {fetched_at, by_sid, total}。"""
    global _snapshot
    with _snapshot_lock:
        fresh_at = _snapshot.get("fetched_at")
        if not force and fresh_at and (dt.datetime.now() - fresh_at) < _SNAPSHOT_TTL:
            return _snapshot
        c = client or TTCClient()
        talents = c.fetch_talents(source="shared")
        by_sid: dict[str, dict] = {}
        for item in talents:
            sid = str(item.get("source_id") or "").strip()
            if sid:
                compact = {k: _iso(v) if k in ("last_active_at", "resume_updated_at") else v
                           for k, v in item.items() if k in _SUPPLEMENT_FIELDS}
                by_sid[sid] = compact
        _snapshot = {
            "fetched_at": dt.datetime.now(),
            "by_sid": by_sid,
            "total": len(talents),
        }
        logger.info("[company-pool] snapshot refreshed: %s talents, %s mapped", len(talents), len(by_sid))
        return _snapshot


def get_company_supplement(talent, client: Optional[TTCClient] = None, force: bool = False) -> dict:
    """给定 Reloop 本地人才行, 返回公司库补充信息 + 本地/公司库差异清单。

    返回结构:
      {found, fetched_at, pool_total, supplement, diff, message}
      - found=False 时 supplement 为 None, message 说明原因
    """
    snap = get_shared_snapshot(client, force=force)
    sid = (talent.source_id or "").strip()
    if not sid:
        return {"found": False, "fetched_at": _iso(snap.get("fetched_at")),
                "pool_total": snap.get("total", 0), "supplement": None,
                "diff": [], "message": "该人才无公司库映射（source_id 缺失）"}
    sup = snap["by_sid"].get(sid)
    if not sup:
        return {"found": False, "fetched_at": _iso(snap.get("fetched_at")),
                "pool_total": snap.get("total", 0), "supplement": None,
                "diff": [], "message": "公司共享池中未找到该人才（source_id: " + sid + "）"}

    diff = []
    for f in _DIFF_FIELDS:
        remote = sup.get(f)
        local = getattr(talent, f, None)
        local_s = _iso(local) if isinstance(local, dt.datetime | dt.date) else local
        if remote and (local_s or None) != remote:
            diff.append({"field": f, "local": local_s, "company": remote})

    return {
        "found": True,
        "fetched_at": _iso(snap.get("fetched_at")),
        "pool_total": snap.get("total", 0),
        "supplement": sup,
        "diff": diff,
        "message": None,
    }
