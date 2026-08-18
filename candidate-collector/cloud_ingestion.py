"""Direct browser-capture ingestion into the cloud candidate table."""
from __future__ import annotations

from typing import Any

from cloud_capture import BrowserCapturePayload, build_candidate_from_capture
from cloud_sync.client import CloudSyncClient
from cloud_sync.config import RDS_DB, rds_configured
from ingestion.entry import ingest_record
from plugin_auth import AuthenticatedActor


def cloud_target_info() -> dict[str, str]:
    return {
        "name": "云端人才库",
        "database": RDS_DB,
        "table": "cloud_candidates",
    }


def import_capture_to_cloud(
    payload: BrowserCapturePayload,
    *,
    client: CloudSyncClient | None = None,
    actor: AuthenticatedActor | None = None,
) -> dict[str, Any]:
    """Parse a visible candidate page and idempotently upsert it to RDS."""
    if not rds_configured() and client is None:
        raise RuntimeError("RDS 尚未配置")

    record = build_candidate_from_capture(payload)
    if not (record.name or "").strip():
        record.review_status = "needs_review"
    cloud = client or CloudSyncClient()
    # 统一入口：QualityGate 随行进库 + 唯一指纹；写失败抛 UpsertError（R7）
    entry = ingest_record(
        record,
        client=cloud,
        actor_user_id=actor.user_id if actor else None,
    )
    fingerprint = entry.fingerprint
    stats = entry.stats

    stored = cloud.get_candidate(fingerprint)
    if not stored:
        raise RuntimeError("云数据库写入后未能回读记录")

    action = entry.action
    source_candidate_id = (record.extra or {}).get("source_candidate_id") or ""
    platform = record.source_platform or payload.platform or ""
    if source_candidate_id and stored.get("id"):
        cloud.link_resume_files(int(stored["id"]), platform, source_candidate_id)
    if actor and stored.get("id"):
        cloud.record_activity_event({
            "user_id": actor.user_id,
            "candidate_id": int(stored["id"]),
            "resume_file_id": None,
            "platform": platform or "unknown",
            "source_candidate_id": source_candidate_id,
            "action": "candidate_collected" if action == "created" else "candidate_seen_duplicate",
            "page_session_id": payload.page_session_id or fingerprint,
            "plugin_version": payload.plugin_version,
            "metadata": {"source_type": payload.source_type},
        })
    candidate = record.model_dump()
    candidate.pop("raw_text", None)
    return {
        "ok": True,
        "action": action,
        "candidate": candidate,
        "fingerprint": fingerprint,
        "cloud_record_id": stored.get("id"),
        "stored_at": stored.get("updated_at") or stored.get("created_at"),
        "target": cloud_target_info(),
        "write_stats": stats,
        "quality_score": entry.quality_score,
        "missing_fields": entry.missing_fields,
    }
