"""公司人才库补充(v2.2): 看 Reloop 人才信息时, 拉公司共享池上同人的最新信息作为补充展示。

- 快照持久化在 company_pool_snapshot 表(整表同批替换), TTL 30 分钟自动重拉
- 快照按 source_id(TTC 人才 ID)索引; 内存视图以 MAX(fetched_at) 为版本, 变了才重建
- supplement = 公司库最新档案(备注/求职状态/薪资/活跃时间...)
- diff = 公司库最新值 与 Reloop 本地副本 的差异清单(本地落后了什么一目了然)

除快照表外不写业务数据。数据源: gateway.ttcadvisory.com 共享池(公司人才库, 只读凭据)。
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from reloop.db.engine import SessionLocal
from reloop.db.models import CompanyPoolSnapshot
from reloop.modules.sync.client import TTCClient

logger = logging.getLogger(__name__)

_SNAPSHOT_TTL = dt.timedelta(minutes=30)

_snapshot_lock = threading.Lock()
# 内存视图以 MAX(fetched_at) 为版本: 每次调用一次轻量 MAX 查询,
# 版本未变直接复用 by_sid, 变了才从表里重建(读多写少)。
_mem_view: dict = {"fetched_at": None, "by_sid": {}, "total": 0}

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


def _refresh_snapshot(db: Session, client: TTCClient) -> None:
    """实时拉共享池并整表替换(同事务先清后插, 快照天然一致)。

    拉取为空视为异常(共享池不可能真空), 保留旧快照不覆盖。
    """
    talents = client.fetch_talents(source="shared")
    if not talents:
        logger.warning("[company-pool] fetch returned 0 talents, keep old snapshot")
        return
    now = dt.datetime.now()
    rows = []
    for item in talents:
        sid = str(item.get("source_id") or "").strip()
        if not sid:
            continue
        compact = {k: _iso(v) if k in ("last_active_at", "resume_updated_at") else v
                   for k, v in item.items() if k in _SUPPLEMENT_FIELDS}
        rows.append(CompanyPoolSnapshot(source_id=sid, payload=compact, fetched_at=now))
    db.query(CompanyPoolSnapshot).delete(synchronize_session=False)
    db.add_all(rows)
    db.commit()
    logger.info("[company-pool] snapshot persisted: %s rows", len(rows))


def get_shared_snapshot(client: Optional[TTCClient] = None,
                        force: bool = False,
                        db: Optional[Session] = None) -> dict:
    """获取公司共享池快照(DB 持久化 + TTL 自动刷新)。

    存储: company_pool_snapshot 表(整表同批替换, 重启/多进程均可读)。
    读路径: MAX(fetched_at) 新鲜(< 30min) -> 表读; 否则实时重拉共享池 -> 整表替换。
    返回 {fetched_at, by_sid, total}(与 v2.1 内存版同构, 调用方零改动)。
    """
    global _mem_view
    with _snapshot_lock:
        own_session = db is None
        db = db or SessionLocal()
        try:
            fresh_at = db.query(func.max(CompanyPoolSnapshot.fetched_at)).scalar()
            if force or fresh_at is None or (dt.datetime.now() - fresh_at) >= _SNAPSHOT_TTL:
                _refresh_snapshot(db, client or TTCClient())
                fresh_at = db.query(func.max(CompanyPoolSnapshot.fetched_at)).scalar()
            if _mem_view.get("fetched_at") != fresh_at:
                rows = db.query(CompanyPoolSnapshot).all()
                _mem_view = {
                    "fetched_at": fresh_at,
                    "by_sid": {r.source_id: (r.payload or {}) for r in rows},
                    "total": len(rows),
                }
            return _mem_view
        finally:
            if own_session:
                db.close()


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
