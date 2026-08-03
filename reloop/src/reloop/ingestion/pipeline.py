"""End-to-end ingestion pipeline.

Transforms raw resume inputs (files or text) into a :class:`CandidateRecord`,
runs deduplication, and commits a durable outbox job. The worker later writes
RDS and the Feishu projection in that order; dry-run previews the payload only.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from reloop.config import DB_PATH
from reloop.domain.models import CandidateRecord
from reloop.ingestion.delivery import DeliveryStore
from reloop.parsing.unified_parser import parse_resume_file, parse_resume_text
from reloop.sinks.feishu.feishu_base import FeishuBaseAdapter


def _db_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_ingestion_tables() -> None:
    """Add ingestion tracking tables to the existing candidates database."""
    with closing(_db_conn()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ingestion_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint TEXT NOT NULL UNIQUE,
                attachment_sha256 TEXT,
                phone TEXT,
                name TEXT,
                current_company TEXT,
                current_title TEXT,
                feishu_record_id TEXT,
                feishu_write_status TEXT NOT NULL DEFAULT 'pending',
                review_status TEXT NOT NULL DEFAULT 'pending',
                dry_run_payload TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        # Migrate existing tables that do not have review_status.
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(ingestion_log)").fetchall()}
        if "review_status" not in cols:
            conn.execute("ALTER TABLE ingestion_log ADD COLUMN review_status TEXT NOT NULL DEFAULT 'pending'")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ingestion_sha256 ON ingestion_log(attachment_sha256)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ingestion_phone ON ingestion_log(phone)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ingestion_review ON ingestion_log(review_status)"
        )
        conn.commit()


def local_duplicate_exists(record: CandidateRecord) -> dict[str, Any] | None:
    """Return existing ingestion log row if this candidate was already processed.

    Dry-run and failed attempts are not treated as duplicates so operators can
    re-run them or convert a dry-run preview into a real write.
    """
    excluded_statuses = {"dry_run", "failed"}
    with closing(_db_conn()) as conn:
        if record.attachment_sha256:
            row = conn.execute(
                """SELECT * FROM ingestion_log
                   WHERE attachment_sha256 = ? AND feishu_write_status NOT IN (?, ?)
                   LIMIT 1""",
                (record.attachment_sha256, *excluded_statuses),
            ).fetchone()
            if row:
                return dict(row)
        if record.phone:
            row = conn.execute(
                """SELECT * FROM ingestion_log
                   WHERE phone = ? AND feishu_write_status NOT IN (?, ?)
                   LIMIT 1""",
                (record.phone, *excluded_statuses),
            ).fetchone()
            if row:
                return dict(row)
        if record.name and record.current_company:
            row = conn.execute(
                """SELECT * FROM ingestion_log
                   WHERE name = ? AND current_company = ? AND feishu_write_status NOT IN (?, ?)
                   LIMIT 1""",
                (record.name, record.current_company, *excluded_statuses),
            ).fetchone()
            if row:
                return dict(row)
    return None


def record_fingerprint(record: CandidateRecord) -> str:
    """Stable local fingerprint used for deduplication."""
    return record.fingerprint()


def _enqueue_for_delivery(record: CandidateRecord, fingerprint: str) -> dict[str, Any]:
    """Persist the outbox job and mirror its local status for review APIs."""

    job = DeliveryStore().enqueue(record, fingerprint=fingerprint)
    payload = {"candidate": record.model_dump(mode="json"), "job_id": job.id}
    with closing(_db_conn()) as conn:
        conn.execute(
            """
            INSERT INTO ingestion_log (
                fingerprint, attachment_sha256, phone, name, current_company,
                current_title, feishu_write_status, review_status, dry_run_payload,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'blocked', 'pending', ?, datetime('now'), datetime('now'))
            ON CONFLICT(fingerprint) DO UPDATE SET
                phone=excluded.phone, name=excluded.name,
                current_company=excluded.current_company, current_title=excluded.current_title,
                feishu_write_status='blocked', dry_run_payload=excluded.dry_run_payload,
                error_message=NULL, updated_at=datetime('now')
            """,
            (
                fingerprint,
                record.attachment_sha256,
                record.phone,
                record.name,
                record.current_company,
                record.current_title,
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        conn.commit()
    return {
        "ok": True,
        "action": "queued",
        "candidate": record.model_dump(mode="json"),
        "fingerprint": fingerprint,
        "job_id": job.id,
        "cloud_status": job.cloud_status,
        "feishu_status": job.feishu_status,
    }


def ingest_file(
    file_path: Path | str,
    *,
    dry_run: bool = True,
    skip_duplicates: bool = True,
    check_feishu_exists: bool = False,
    source_platform: str | None = None,
    source_url: str | None = None,
    source_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ingest a local resume file through the full pipeline.

    Args:
        file_path: Path to PDF/DOC/DOCX/image resume.
        dry_run: If True, only preview the Feishu payload without queuing.
        skip_duplicates: If True, return early when a duplicate is detected.
        check_feishu_exists: If True, query Feishu Base for duplicates (slower).
        source_platform: Override the parsed record's source platform.
        source_url: Override the parsed record's source URL.
        source_extra: Additional metadata merged into record.extra.
    """
    init_ingestion_tables()
    record = parse_resume_file(file_path)
    if source_platform:
        record.source_platform = source_platform
        record.source_type = source_platform
    if source_url:
        record.source_url = source_url
    if source_extra:
        record.extra.update(source_extra)

    fingerprint = record_fingerprint(record)

    duplicate = local_duplicate_exists(record)
    if duplicate and skip_duplicates:
        return {
            "ok": True,
            "action": "skipped_duplicate",
            "candidate": record.model_dump(),
            "fingerprint": fingerprint,
            "duplicate": duplicate,
        }

    adapter = FeishuBaseAdapter()

    if check_feishu_exists and adapter.record_exists(record):
        return {
            "ok": True,
            "action": "skipped_duplicate_feishu",
            "candidate": record.model_dump(),
            "fingerprint": fingerprint,
        }

    if dry_run:
        payload = adapter.dry_run(record)
        dry_run_payload = {
            "candidate": record.model_dump(),
            "feishu_payload": payload,
        }
        with closing(_db_conn()) as conn:
            conn.execute(
                """
                INSERT INTO ingestion_log (
                    fingerprint, attachment_sha256, phone, name, current_company,
                    current_title, feishu_write_status, review_status, dry_run_payload, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                ON CONFLICT(fingerprint) DO UPDATE SET
                    phone=excluded.phone,
                    name=excluded.name,
                    current_company=excluded.current_company,
                    current_title=excluded.current_title,
                    dry_run_payload=excluded.dry_run_payload,
                    updated_at=datetime('now')
                """,
                (
                    fingerprint,
                    record.attachment_sha256,
                    record.phone,
                    record.name,
                    record.current_company,
                    record.current_title,
                    "dry_run",
                    "pending",
                    json.dumps(dry_run_payload, ensure_ascii=False),
                ),
            )
            conn.commit()
        return {
            "ok": True,
            "action": "dry_run",
            "candidate": record.model_dump(),
            "fingerprint": fingerprint,
            "feishu_payload": payload,
        }

    return _enqueue_for_delivery(record, fingerprint)


def ingest_text(
    text: str,
    title: str = "",
    source_url: str = "",
    *,
    dry_run: bool = True,
    skip_duplicates: bool = True,
) -> dict[str, Any]:
    """Ingest raw resume text (e.g. from browser extension) into the pipeline.

    Mirrors :func:`ingest_file` for deduplication and log tracking.
    """
    init_ingestion_tables()
    record = parse_resume_text(text, title=title, source_url=source_url)
    fingerprint = record_fingerprint(record)

    duplicate = local_duplicate_exists(record)
    if duplicate and skip_duplicates:
        return {
            "ok": True,
            "action": "skipped_duplicate",
            "candidate": record.model_dump(),
            "fingerprint": fingerprint,
            "duplicate": duplicate,
        }

    adapter = FeishuBaseAdapter()
    if dry_run:
        payload = adapter.dry_run(record)
        dry_run_payload = {
            "candidate": record.model_dump(),
            "feishu_payload": payload,
        }
        with closing(_db_conn()) as conn:
            conn.execute(
                """
                INSERT INTO ingestion_log (
                    fingerprint, attachment_sha256, phone, name, current_company,
                    current_title, feishu_write_status, review_status, dry_run_payload, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                ON CONFLICT(fingerprint) DO UPDATE SET
                    phone=excluded.phone,
                    name=excluded.name,
                    current_company=excluded.current_company,
                    current_title=excluded.current_title,
                    dry_run_payload=excluded.dry_run_payload,
                    updated_at=datetime('now')
                """,
                (
                    fingerprint,
                    record.attachment_sha256,
                    record.phone,
                    record.name,
                    record.current_company,
                    record.current_title,
                    "dry_run",
                    "pending",
                    json.dumps(dry_run_payload, ensure_ascii=False),
                ),
            )
            conn.commit()
        return {
            "ok": True,
            "action": "dry_run",
            "candidate": record.model_dump(),
            "fingerprint": fingerprint,
            "feishu_payload": payload,
        }

    return _enqueue_for_delivery(record, fingerprint)


def _extract_record_id(resp: dict[str, Any]) -> str | None:
    """Best-effort extraction of Feishu record ID from lark-cli response."""
    data = resp.get("data", {})
    if isinstance(data, dict):
        records = data.get("records")
        if isinstance(records, list) and records:
            return records[0].get("record_id")
        record_id_list = data.get("record_id_list")
        if isinstance(record_id_list, list) and record_id_list:
            return record_id_list[0]
        return data.get("record_id")
    if isinstance(data, list) and data:
        return data[0].get("record_id")
    return None
