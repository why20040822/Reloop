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
    """Upsert one candidate by its stable fingerprint."""

    row = record.to_db_dict()
    row["fingerprint"] = record.fingerprint()
    row["raw_profile"] = json.dumps(row, ensure_ascii=False, default=str)
    columns = ["fingerprint", "name", "phone", "email", "raw_profile"]
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


__all__ = ["RdsConfigurationError", "get_candidate", "upsert_candidate"]
