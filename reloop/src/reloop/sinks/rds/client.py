"""The only RDS write boundary in Reloop.

Credentials are read at call time from environment variables.  No caller may
construct a PyMySQL connection or RDS SQL outside this module.
"""

from __future__ import annotations

import json
import os
from contextlib import closing
from typing import Any

from reloop.domain.models import CandidateRecord


class RdsConfigurationError(RuntimeError):
    """Raised when the RDS boundary is invoked without complete configuration."""


def _connection():
    try:
        import pymysql
    except ImportError as exc:
        raise RdsConfigurationError("pymysql is required for RDS delivery") from exc

    required = {key: os.getenv(key, "").strip() for key in ("RDS_HOST", "RDS_USER", "RDS_PASSWORD", "RDS_DATABASE")}
    missing = [key for key, value in required.items() if not value]
    if missing:
        raise RdsConfigurationError(f"missing RDS configuration: {', '.join(missing)}")
    return pymysql.connect(
        host=required["RDS_HOST"],
        user=required["RDS_USER"],
        password=required["RDS_PASSWORD"],
        database=required["RDS_DATABASE"],
        port=int(os.getenv("RDS_PORT", "3306")),
        charset="utf8mb4",
        autocommit=False,
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=int(os.getenv("RDS_CONNECT_TIMEOUT", "10")),
    )


def upsert_candidate(record: CandidateRecord) -> dict[str, Any]:
    """Upsert one candidate by its stable fingerprint.

    列集对齐真实 cloud_candidates 表结构（曾用假设列 raw_profile 导致 1054
    全量投递失败，outbox fail-closed 拦下——2026-08-14 修复为 parsed_json）。
    """

    row = record.to_db_dict()
    row["fingerprint"] = record.fingerprint()
    row["parsed_json"] = json.dumps(record.model_dump(mode="json"), ensure_ascii=False, default=str)
    columns = [
        "fingerprint", "name", "phone", "email", "platform", "source_url", "source_type",
        "title", "location", "current_company", "current_role", "undergraduate_school",
        "expected_salary", "experiences_json", "education_json", "keywords_json", "raw_text",
        "parsed_json",
    ]
    values = [row.get(column, "") for column in columns]
    updates = ", ".join(f"{column} = VALUES({column})" for column in columns[1:])
    sql = (
        "INSERT INTO cloud_candidates ("
        + ", ".join(columns)
        + ") VALUES ("
        + ", ".join(["%s"] * len(columns))
        + ") ON DUPLICATE KEY UPDATE "
        + updates
    )
    with closing(_connection()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, values)
            connection.commit()
            return {"fingerprint": row["fingerprint"], "affected_rows": cursor.rowcount}


def get_candidate(fingerprint: str) -> dict[str, Any] | None:
    """Read one candidate by fingerprint through the same RDS boundary."""

    with closing(_connection()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM cloud_candidates WHERE fingerprint = %s LIMIT 1",
                (fingerprint,),
            )
            return cursor.fetchone()


# ---------------------------------------------------------------------------
# Read path for the demo frontend (cloud_candidates is the source of truth).
# All SQL stays in this module; callers get frontend-ready dicts.
# ---------------------------------------------------------------------------


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else (str(value) if value else None)


def public_candidate_row(row: dict[str, Any]) -> dict[str, Any]:
    """Shape one cloud_candidates row for the frontend proxy contract."""

    quality = row.get("quality_score")
    return {
        "id": row.get("id"),
        "fingerprint": row.get("fingerprint"),
        "name": row.get("name"),
        "phone": row.get("phone") or None,
        "email": row.get("email") or None,
        "current_company": row.get("current_company") or None,
        "current_role": row.get("current_role") or None,
        "current_location": row.get("location") or None,
        "location": row.get("location") or None,
        "undergraduate_school": row.get("undergraduate_school") or None,
        "expected_salary": row.get("expected_salary") or None,
        "opportunity_intent": row.get("opportunity_intent") or None,
        "platform": row.get("platform") or None,
        "source_url": row.get("source_url") or None,
        "review_status": row.get("review_status") or None,
        "quality_score": float(quality) if quality is not None else None,
        "missing_fields": _json_list(row.get("missing_fields")),
        "experiences": _json_list(row.get("experiences_json"))[:10],
        "keywords": _json_list(row.get("keywords_json")),
        "raw_text": row.get("raw_text") or "",
        "collected_at": _iso(row.get("collected_at")),
        "updated_at": _iso(row.get("updated_at")),
        # 云端没有本地评分列，显式置空，前端按缺失处理
        "score": None,
        "jd_score": None,
        "jd_recommendation": None,
        "recommendation": None,
    }


def list_candidates(q: str = "", limit: int = 200) -> list[dict[str, Any]]:
    """List cloud candidates, contactable first, newest first.

    MySQL has no NULLS LAST; boolean sort keys achieve the same ordering.
    """

    limit = max(1, min(int(limit), 500))
    sql = "SELECT * FROM cloud_candidates"
    params: list[Any] = []
    if q:
        sql += " WHERE name LIKE %s OR current_company LIKE %s OR raw_text LIKE %s"
        term = f"%{q}%"
        params = [term, term, term]
    sql += " ORDER BY (phone IS NULL OR phone = ''), collected_at DESC, id DESC LIMIT %s"
    params.append(limit)
    with closing(_connection()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return [public_candidate_row(row) for row in cursor.fetchall()]


def get_candidate_by_id(candidate_id: int) -> dict[str, Any] | None:
    """Read one cloud candidate by primary key."""

    with closing(_connection()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM cloud_candidates WHERE id = %s LIMIT 1",
                (candidate_id,),
            )
            row = cursor.fetchone()
    return public_candidate_row(row) if row else None


def fetch_match_pool(pool_size: int = 100) -> list[dict[str, Any]]:
    """Fetch a candidate pool for JD matching: full resumes, contactable first.

    垃圾姓名（解析失败的版块标题等）不进匹配池——触达场景不可用。
    """

    pool_size = max(1, min(int(pool_size), 500))
    with closing(_connection()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT * FROM cloud_candidates
                   WHERE raw_text IS NOT NULL AND LENGTH(raw_text) > 200
                     AND name IS NOT NULL AND name != ''
                     AND name NOT IN ('全文','未知','打招呼','在线简历','待识别候选人','核心优势','个人优势','工作经历')
                   ORDER BY (phone IS NULL OR phone = ''), collected_at DESC
                   LIMIT %s""",
                (pool_size,),
            )
            return [public_candidate_row(row) for row in cursor.fetchall()]


__all__ = [
    "RdsConfigurationError",
    "fetch_match_pool",
    "get_candidate",
    "get_candidate_by_id",
    "list_candidates",
    "public_candidate_row",
    "upsert_candidate",
]
