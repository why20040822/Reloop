"""Human review service for ingestion log records.

Provides queue listing, detail retrieval, and approval/rejection of parsed
candidates. Approval queues the corrected payload; the worker is the only
component that commits RDS and Feishu.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from typing import Any

from reloop.domain.models import CandidateRecord, Education, FieldConfidence, WorkExperience
from reloop.ingestion.delivery import DeliveryJob, DeliveryStore
from reloop.ingestion.pipeline import _db_conn, init_ingestion_tables, record_fingerprint


def _candidate_from_log(row: sqlite3.Row) -> CandidateRecord | None:
    """Reconstruct a CandidateRecord from ingestion_log data."""
    dry_run = row["dry_run_payload"]
    if dry_run:
        try:
            payload = json.loads(dry_run)
            candidate = payload.get("candidate") or {}
            return CandidateRecord(**candidate)
        except Exception:
            pass
    # Fallback: minimal record from log columns.
    return CandidateRecord(
        name=row["name"] or "",
        phone=row["phone"] or "",
        current_company=row["current_company"] or "",
        current_title=row["current_title"] or "",
    )


def review_queue(limit: int = 50) -> dict[str, Any]:
    """Return ingestion records awaiting human review."""
    init_ingestion_tables()
    with closing(_db_conn()) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT * FROM ingestion_log
            WHERE review_status = 'pending'
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    items = []
    for row in rows:
        record = _candidate_from_log(row)
        items.append({
            "id": row["id"],
            "fingerprint": row["fingerprint"],
            "name": record.name or row["name"],
            "phone": record.phone or row["phone"],
            "current_company": record.current_company or row["current_company"],
            "current_title": record.current_title or row["current_title"],
            "feishu_write_status": row["feishu_write_status"],
            "attachment_sha256": row["attachment_sha256"],
            "updated_at": row["updated_at"],
        })
    return {"ok": True, "count": len(items), "items": items}


def review_detail(log_id: int) -> dict[str, Any]:
    """Return full details for a single review item."""
    init_ingestion_tables()
    with closing(_db_conn()) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM ingestion_log WHERE id=?", (log_id,)).fetchone()
    if not row:
        return {"ok": False, "error": "记录不存在"}
    record = _candidate_from_log(row)
    return {
        "ok": True,
        "log_id": row["id"],
        "fingerprint": row["fingerprint"],
        "feishu_write_status": row["feishu_write_status"],
        "feishu_record_id": row["feishu_record_id"],
        "review_status": row["review_status"],
        "attachment_sha256": row["attachment_sha256"],
        "dry_run_payload": json.loads(row["dry_run_payload"] or "{}"),
        "error_message": row["error_message"],
        "candidate": record.model_dump(),
    }


def _apply_corrections(record: CandidateRecord, corrections: dict[str, Any]) -> None:
    """Apply human corrections to a CandidateRecord, converting nested dicts to models."""
    for key, value in corrections.items():
        if not hasattr(record, key):
            continue
        if key == "work_experiences" and isinstance(value, list):
            value = [WorkExperience(**item) if isinstance(item, dict) else item for item in value]
        if key == "education" and isinstance(value, dict):
            value = Education(**value)
        if key == "education_list" and isinstance(value, list):
            value = [Education(**item) if isinstance(item, dict) else item for item in value]
        setattr(record, key, value)

    # Mark corrected fields as human-verified and boost overall confidence.
    for key in corrections:
        existing = next((fc for fc in record.field_confidences if fc.field == key), None)
        if existing:
            existing.confidence = 1.0
            existing.note = "human verified"
        else:
            record.field_confidences.append(FieldConfidence(field=key, confidence=1.0, note="human verified"))
    if corrections:
        record.parse_confidence = 1.0

    # Derive current company/title from first work experience when not explicitly corrected.
    if record.work_experiences and "current_company" not in corrections:
        record.current_company = record.work_experiences[0].company
    if record.work_experiences and "current_title" not in corrections:
        record.current_title = record.work_experiences[0].role


def approve_record(
    log_id: int,
    corrections: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply corrections, queue delivery, and mark the review as approved."""
    init_ingestion_tables()
    corrections = corrections or {}
    with closing(_db_conn()) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM ingestion_log WHERE id=?", (log_id,)).fetchone()
    if not row:
        return {"ok": False, "error": "记录不存在"}

    record = _candidate_from_log(row)
    if record is None:
        return {"ok": False, "error": "无法解析候选人记录"}

    # Apply corrections.
    _apply_corrections(record, corrections)

    store = DeliveryStore()
    job = _queue_review_payload(store, row, record)

    with closing(_db_conn()) as conn:
        conn.execute(
            """
            UPDATE ingestion_log SET
                fingerprint=?,
                feishu_record_id=NULL,
                feishu_write_status='blocked',
                review_status='approved',
                dry_run_payload=?,
                name=?,
                phone=?,
                current_company=?,
                current_title=?,
                updated_at=datetime('now')
            WHERE id=?
            """,
            (
                job.fingerprint,
                json.dumps({"candidate": record.model_dump(), "job_id": job.id}, ensure_ascii=False),
                record.name or "",
                record.phone or "",
                record.current_company or "",
                record.current_title or "",
                log_id,
            ),
        )
        conn.commit()

    return {
        "ok": True,
        "action": "approved",
        "feishu_record_id": None,
        "feishu_write_status": "blocked",
        "job_id": job.id,
        "delivery": "queued",
    }


def _queue_review_payload(
    store: DeliveryStore,
    row: sqlite3.Row,
    record: CandidateRecord,
) -> DeliveryJob:
    """Queue a reviewed payload, reusing its existing outbox job when present."""

    try:
        payload = json.loads(row["dry_run_payload"] or "{}")
    except (TypeError, ValueError):
        payload = {}
    job_id = payload.get("job_id")
    if isinstance(job_id, int) and store.get(job_id):
        return store.reset_for_delivery(job_id, record)
    return store.enqueue(record, fingerprint=row["fingerprint"] or record_fingerprint(record))


def reject_record(log_id: int, reason: str = "") -> dict[str, Any]:
    """Mark a record as rejected."""
    init_ingestion_tables()
    with closing(_db_conn()) as conn:
        conn.execute(
            """
            UPDATE ingestion_log SET
                review_status='rejected',
                error_message=?,
                updated_at=datetime('now')
            WHERE id=?
            """,
            (reason, log_id),
        )
        conn.commit()
    return {"ok": True, "action": "rejected"}
