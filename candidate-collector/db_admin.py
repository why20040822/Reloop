"""云端 RDS 数据库管理面板 API。

只读接口，供 /db-admin 页面使用。云端不可用时返回错误字段，绝不影响本地服务。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/db", tags=["db-admin"])

# 允许浏览的表白名单（防注入，不开放任意 SQL）
TABLES = {
    "cloud_candidates",
    "memories",
    "candidate_resume_files",
    "plugin_activity_events",
    "plugin_sessions",
    "plugin_users",
}

# 大字段不在列表接口返回
HEAVY_COLS = {"raw_text", "parsed_json", "experiences_json", "education_json",
              "keywords_json", "embedding", "content_text", "file_blob"}


def _query(sql: str, args: tuple = ()) -> list[dict[str, Any]]:
    from cloud_sync.client import get_conn  # 延迟导入，云端不可用时仅本模块报错
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, args)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _scalar(sql: str, args: tuple = ()) -> Any:
    rows = _query(sql, args)
    return list(rows[0].values())[0] if rows else None


@router.get("/overview")
def overview() -> dict[str, Any]:
    try:
        counts = {t: _scalar(f"SELECT COUNT(*) FROM {t}") for t in sorted(TABLES)}
        cand = _query(
            "SELECT COUNT(*) total,"
            " SUM(phone IS NOT NULL AND phone!='') with_phone,"
            " SUM(name IS NULL OR name='' OR name IN ('全文','打招呼','在线简历')) junk_name,"
            " MAX(created_at) last_created, MAX(updated_at) last_updated"
            " FROM cloud_candidates"
        )[0]
        mem = _query(
            "SELECT COUNT(*) total, SUM(embedding IS NOT NULL) with_embedding,"
            " MAX(created_at) last_created FROM memories"
        )[0]
        platform = _query(
            "SELECT platform, COUNT(*) n FROM cloud_candidates GROUP BY platform ORDER BY n DESC"
        )
        mem_source = _query(
            "SELECT source, COUNT(*) n FROM memories GROUP BY source ORDER BY n DESC LIMIT 12"
        )
        return {
            "ok": True,
            "tables": counts,
            "candidates": cand,
            "memories": mem,
            "platform_dist": platform,
            "memory_source_dist": mem_source,
        }
    except Exception as exc:  # noqa: BLE001 - 面板接口必须兜底
        return {"ok": False, "error": str(exc)}


@router.get("/ingestion-daily")
def ingestion_daily(days: int = Query(default=14, ge=1, le=90)) -> dict[str, Any]:
    try:
        cand = _query(
            "SELECT DATE(created_at) d, COUNT(*) n FROM cloud_candidates"
            " WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL %s DAY)"
            " GROUP BY d ORDER BY d", (days,))
        events = _query(
            "SELECT DATE(created_at) d, COUNT(*) n FROM plugin_activity_events"
            " WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL %s DAY)"
            " GROUP BY d ORDER BY d", (days,))
        mem = _query(
            "SELECT DATE(created_at) d, COUNT(*) n FROM memories"
            " WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL %s DAY)"
            " GROUP BY d ORDER BY d", (days,))
        for rows in (cand, events, mem):
            for r in rows:
                r["d"] = str(r["d"])
        return {"ok": True, "candidates": cand, "plugin_events": events, "memories": mem}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


@router.get("/candidates/recent")
def recent_candidates(limit: int = Query(default=50, ge=1, le=200),
                      q: str = Query(default="", max_length=100)) -> dict[str, Any]:
    try:
        sql = ("SELECT id, fingerprint, name, platform, current_company, current_role,"
               " phone, email, location, review_status, created_at, updated_at"
               " FROM cloud_candidates")
        args: tuple = ()
        if q:
            sql += " WHERE name LIKE %s OR current_company LIKE %s OR raw_text LIKE %s"
            term = f"%{q}%"
            args = (term, term, term)
        sql += " ORDER BY updated_at DESC LIMIT %s"
        args += (limit,)
        rows = _query(sql, args)
        for r in rows:
            for k in ("created_at", "updated_at"):
                if r.get(k) is not None:
                    r[k] = str(r[k])
        return {"ok": True, "rows": rows}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


@router.get("/table/{name}")
def table_rows(name: str, limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    if name not in TABLES:
        raise HTTPException(404, f"表 {name} 不在白名单内")
    try:
        cur_cols = _query(f"SHOW COLUMNS FROM {name}")
        light = [c["Field"] for c in cur_cols if c["Field"] not in HEAVY_COLS]
        col_list = ", ".join(f"`{c}`" for c in light)
        rows = _query(f"SELECT {col_list} FROM {name} ORDER BY id DESC LIMIT %s", (limit,))
        for r in rows:
            for k, v in r.items():
                if v is not None and not isinstance(v, (int, float, str)):
                    r[k] = str(v)
                elif isinstance(v, str) and len(v) > 300:
                    r[k] = v[:300] + "…"
        return {"ok": True, "columns": light, "rows": rows}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
