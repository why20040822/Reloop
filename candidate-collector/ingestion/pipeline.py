"""End-to-end ingestion pipeline.

Transforms raw resume inputs (files or text) into a :class:`models.CandidateRecord`,
runs deduplication, and writes to the configured Feishu Base.  The pipeline
supports dry-run mode so operators can preview what would change before
committing.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from adapters.feishu_base import FeishuBaseAdapter
from ingestion.delivery import DeliveryStore, DeliveryWorker
from models import CandidateRecord
from parsers.unified_parser import parse_resume_file, parse_resume_text


logger = logging.getLogger(__name__)


def _sync_to_cloud(record: CandidateRecord) -> dict[str, Any]:
    """Best-effort sync a CandidateRecord to cloud RDS via the unified entry. Never raise."""
    try:
        from cloud_sync.config import rds_configured
        from ingestion.entry import ingest_record

        if not rds_configured():
            return {"status": "skipped", "reason": "rds_not_configured"}
        result = ingest_record(record, read_back=False)
        return {"status": "success", **result.stats, "quality_score": result.quality_score}
    except Exception as exc:
        logger.warning(f"cloud sync skipped: {exc}")
        return {"status": "failed", "error": str(exc)}


DB_PATH = Path(__file__).resolve().parent.parent / "data" / "candidates.db"


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
                source_record_id TEXT,
                source_platform TEXT,
                source_url TEXT,
                attachment_sha256 TEXT,
                phone TEXT,
                name TEXT,
                current_company TEXT,
                current_title TEXT,
                feishu_record_id TEXT,
                feishu_table_id TEXT,
                feishu_write_status TEXT NOT NULL DEFAULT 'pending',
                attachment_status TEXT NOT NULL DEFAULT 'none',
                retry_count INTEGER NOT NULL DEFAULT 0,
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
        if "source_record_id" not in cols:
            conn.execute("ALTER TABLE ingestion_log ADD COLUMN source_record_id TEXT")
        migrations = {
            "source_platform": "TEXT",
            "source_url": "TEXT",
            "feishu_table_id": "TEXT",
            "attachment_status": "TEXT NOT NULL DEFAULT 'none'",
            "retry_count": "INTEGER NOT NULL DEFAULT 0",
        }
        for column, definition in migrations.items():
            if column not in cols:
                conn.execute(f"ALTER TABLE ingestion_log ADD COLUMN {column} {definition}")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ingestion_sha256 ON ingestion_log(attachment_sha256)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ingestion_phone ON ingestion_log(phone)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ingestion_review ON ingestion_log(review_status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ingestion_source_record_id ON ingestion_log(source_record_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ingestion_source_identity "
            "ON ingestion_log(source_platform, source_record_id)"
        )
        conn.commit()


def local_duplicate_exists(record: CandidateRecord) -> dict[str, Any] | None:
    """Return existing ingestion log row if this candidate was already processed.

    Dry-run and failed attempts are not treated as duplicates so operators can
    re-run them or convert a dry-run preview into a real write.
    """
    excluded_statuses = {"dry_run", "failed"}
    with closing(_db_conn()) as conn:
        if record.ttc_pid:
            # TTC person_leads_id is the only local identity key.  Reusing a
            # name, phone, email, or attachment across distinct PIDs must not
            # collapse legitimate source profiles.
            row = conn.execute(
                """SELECT * FROM ingestion_log
                   WHERE fingerprint = ? AND feishu_write_status NOT IN (?, ?)
                   LIMIT 1""",
                (record_fingerprint(record), *excluded_statuses),
            ).fetchone()
            return dict(row) if row else None
        if record.source_record_id:
            row = conn.execute(
                """SELECT * FROM ingestion_log
                   WHERE source_platform = ? AND source_record_id = ?
                     AND feishu_write_status NOT IN (?, ?)
                   LIMIT 1""",
                (
                    record.source_platform or record.source_type,
                    record.source_record_id,
                    *excluded_statuses,
                ),
            ).fetchone()
            if row:
                return dict(row)
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
    return hashlib.sha256(record.fingerprint_input().encode("utf-8")).hexdigest()


def _deliver_record(
    record: CandidateRecord,
    fingerprint: str,
    adapter: FeishuBaseAdapter,
) -> dict[str, Any]:
    """Persist a delivery job and attempt its two ordered sinks once."""
    store = DeliveryStore(DB_PATH)
    job_id = store.enqueue(record, fingerprint)

    feishu_response: dict[str, Any] = {}

    def cloud_sink(candidate: CandidateRecord) -> dict[str, Any]:
        response = _sync_to_cloud(candidate)
        # RDS 未配置时不阻断飞书投递，但状态如实标记 skipped（不再伪装成成功），
        # 便于核对哪些记录只在飞书、待补云。
        if response.get("status") == "skipped":
            logger.info("cloud sink skipped（RDS 未配置），仅投递飞书: %s", fingerprint)
            return {"status": "success", "skipped": True, **response}
        return response

    def feishu_sink(candidate: CandidateRecord) -> dict[str, Any]:
        response = adapter.upsert_record(candidate)
        if isinstance(response, dict):
            feishu_response.clear()
            feishu_response.update(response)
        record_id = _extract_record_id(response)
        return {
            "status": "success" if record_id else "failed",
            "record_id": record_id,
            "error": None if record_id else f"Feishu did not return record_id: {response}",
        }

    result = DeliveryWorker(store, cloud_sink, feishu_sink).deliver(job_id)
    job = store.get(job_id) or {}
    completed = result.state == "completed"
    payload = {
        "candidate": record.model_dump(),
        "delivery": result.as_dict(),
    }
    with closing(_db_conn()) as conn:
        conn.execute(
            """
            INSERT INTO ingestion_log (
                fingerprint, source_record_id, source_platform, source_url,
                attachment_sha256, phone, name, current_company,
                current_title, feishu_record_id, feishu_write_status,
                review_status, error_message, dry_run_payload, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            ON CONFLICT(fingerprint) DO UPDATE SET
                source_record_id=excluded.source_record_id,
                source_platform=excluded.source_platform,
                source_url=excluded.source_url,
                phone=excluded.phone,
                name=excluded.name,
                current_company=excluded.current_company,
                current_title=excluded.current_title,
                feishu_record_id=excluded.feishu_record_id,
                feishu_write_status=excluded.feishu_write_status,
                review_status=excluded.review_status,
                error_message=excluded.error_message,
                dry_run_payload=excluded.dry_run_payload,
                updated_at=datetime('now')
            """,
            (
                fingerprint,
                record.source_record_id,
                record.source_platform,
                record.source_url,
                record.attachment_sha256,
                record.phone,
                record.name,
                record.current_company,
                record.current_title,
                job.get("feishu_record_id"),
                result.feishu_status,
                record.review_status,
                result.cloud_error or result.feishu_error,
                json.dumps(payload, ensure_ascii=False, default=str),
            ),
        )
        conn.commit()
    if completed and feishu_response.get("idempotent_existing"):
        action = "skipped_duplicate_feishu"
    elif completed:
        action = "created"
    else:
        action = "queued_for_retry"
    return {
        "ok": True,
        "action": action,
        "candidate": record.model_dump(),
        "fingerprint": fingerprint,
        "job_id": job_id,
        "feishu_record_id": job.get("feishu_record_id"),
        "delivery": result.as_dict(),
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
        dry_run: If True, only preview the Feishu payload without writing.
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
        explicit_source_id = source_extra.get("source_record_id") or source_extra.get(
            "person_leads_id"
        )
        if explicit_source_id:
            record.source_record_id = str(explicit_source_id)
        record.extra.update(source_extra)
    try:
        record.sync_source_identity()
    except ValueError as exc:
        # 脏数据（source_record_id 与 URL 不匹配）不允许 500 崩掉整个 ingest，
        # 落 failed 日志后正常返回，便于排查重跑。
        fingerprint = hashlib.sha256(
            f"invalid|{file_path}|{exc}".encode("utf-8")
        ).hexdigest()
        with closing(_db_conn()) as conn:
            conn.execute(
                """
                INSERT INTO ingestion_log (
                    fingerprint, source_record_id, source_platform, source_url,
                    feishu_write_status, review_status, error_message, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'failed', 'pending', ?, datetime('now'), datetime('now'))
                ON CONFLICT(fingerprint) DO UPDATE SET
                    error_message=excluded.error_message,
                    updated_at=datetime('now')
                """,
                (
                    fingerprint,
                    record.source_record_id,
                    record.source_platform,
                    record.source_url,
                    f"invalid source identity: {exc}",
                ),
            )
            conn.commit()
        return {
            "ok": False,
            "action": "failed",
            "candidate": record.model_dump(),
            "fingerprint": fingerprint,
            "error": f"invalid source identity: {exc}",
        }

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
                    fingerprint, source_record_id, source_platform, source_url,
                    attachment_sha256, phone, name, current_company,
                    current_title, feishu_write_status, review_status, dry_run_payload, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                ON CONFLICT(fingerprint) DO UPDATE SET
                    source_record_id=excluded.source_record_id,
                    source_platform=excluded.source_platform,
                    source_url=excluded.source_url,
                    phone=excluded.phone,
                    name=excluded.name,
                    current_company=excluded.current_company,
                    current_title=excluded.current_title,
                    dry_run_payload=excluded.dry_run_payload,
                    updated_at=datetime('now')
                """,
                (
                    fingerprint,
                    record.source_record_id,
                    record.source_platform,
                    record.source_url,
                    record.attachment_sha256,
                    record.phone,
                    record.name,
                    record.current_company,
                    record.current_title,
                    "dry_run",
                    "pending",
                    json.dumps(dry_run_payload, ensure_ascii=False, default=str),
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

    return _deliver_record(record, fingerprint, adapter)


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
                    fingerprint, source_record_id, source_platform, source_url,
                    attachment_sha256, phone, name, current_company,
                    current_title, feishu_write_status, review_status, dry_run_payload, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                ON CONFLICT(fingerprint) DO UPDATE SET
                    source_record_id=excluded.source_record_id,
                    source_platform=excluded.source_platform,
                    source_url=excluded.source_url,
                    phone=excluded.phone,
                    name=excluded.name,
                    current_company=excluded.current_company,
                    current_title=excluded.current_title,
                    dry_run_payload=excluded.dry_run_payload,
                    updated_at=datetime('now')
                """,
                (
                    fingerprint,
                    record.source_record_id,
                    record.source_platform,
                    record.source_url,
                    record.attachment_sha256,
                    record.phone,
                    record.name,
                    record.current_company,
                    record.current_title,
                    "dry_run",
                    "pending",
                    json.dumps(dry_run_payload, ensure_ascii=False, default=str),
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

    return _deliver_record(record, fingerprint, adapter)


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
