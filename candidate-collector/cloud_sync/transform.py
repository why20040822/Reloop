"""Convert local SQLite rows / CandidateRecord to cloud_candidates schema."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from collections.abc import Mapping
from typing import Any


def _parse_timestamp(value: str | datetime | None) -> datetime | None:
    """Return a MySQL ``DATETIME`` compatible naive UTC timestamp."""
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        normalized = value.strip()
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            try:
                parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return None

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def sqlite_row_to_cloud(row: sqlite3.Row | Mapping[str, Any]) -> dict[str, Any]:
    """Convert a local candidates SQLite row into the cloud_candidates schema.

    .. deprecated:: 本地 SQLite 批量同步已下线（DATA_GOVERNANCE §4），
       新写入一律走 ``ingestion.entry.ingest_record``。此函数仅为存量脚本/
       测试保留，2026-08-05 修复了两个 NameError（activity_score/signals）
       并移除了 ``str(id)`` 自造指纹。
    """
    # sqlite3.Row implements key lookup but intentionally has no ``dict.get``.
    # Normalize once so both real SQLite rows and dict-like test inputs behave
    # identically throughout the transformation.
    data = dict(row)
    collected_at = _parse_timestamp(data.get("collected_at"))

    # Preserve every local column in parsed_json so nothing is lost.
    parsed_json = {
        "id": data.get("id"),
        "explicit_age": data.get("explicit_age"),
        "experience_years": data.get("experience_years"),
        "undergraduate_tier": data.get("undergraduate_tier"),
        "employment_status": data.get("employment_status"),
        "summary": data.get("summary"),
        "hard_filter_reason": data.get("hard_filter_reason"),
        "consulting_evidence": data.get("consulting_evidence"),
        "inhouse_evidence": data.get("inhouse_evidence"),
        "product_evidence": data.get("product_evidence"),
        "brand_evidence": data.get("brand_evidence"),
        "channel_evidence": data.get("channel_evidence"),
        "client_evidence": data.get("client_evidence"),
        "score": data.get("score"),
        "jd_score": data.get("jd_score"),
        "jd_recommendation": data.get("jd_recommendation"),
        "jd_scores_json": data.get("jd_scores_json"),
        "recommendation": data.get("recommendation"),
        "strengths_json": data.get("strengths_json"),
        "risks_json": data.get("risks_json"),
    }

    return {
        "fingerprint": data.get("fingerprint") or _fallback_fingerprint(data),
        "name": data.get("name") or "",
        "platform": data.get("platform") or "",
        "source_candidate_id": data.get("source_candidate_id") or "",
        "source_url": data.get("source_url") or "",
        "source_type": data.get("source_type") or "",
        "title": data.get("title") or "",
        "location": data.get("location") or "",
        "current_company": data.get("current_company") or "",
        "current_role": data.get("current_role") or "",
        "phone": data.get("phone") or "",
        "email": data.get("email") or "",
        "undergraduate_school": data.get("undergraduate_school") or "",
        "expected_salary": data.get("expected_salary") or "",
        "experiences_json": data.get("experiences_json") or "[]",
        "education_json": data.get("education_json") or "{}",
        "keywords_json": data.get("keywords_json") or "[]",
        "raw_text": data.get("raw_text") or "",
        "review_status": "pending",
        "attachment_path": data.get("attachment_path"),
        "attachment_sha256": data.get("attachment_sha256"),
        "collected_at": collected_at,
        "parsed_json": json.dumps(parsed_json, ensure_ascii=False, default=str),
        "activity_score": data.get("activity_score") or 0,
        "activity_signals": _json_or(data.get("activity_signals"), {}),
        "owner": data.get("owner"),
        "visibility": data.get("visibility") or "team",
        "starred": bool(data.get("starred")),
        "last_active_at": _parse_timestamp(data.get("last_active_at")),
    }


def _json_or(value: Any, default: Any) -> str:
    """Normalize a JSON column input (dict/list/JSON string/None) to a JSON string."""
    if value is None:
        return json.dumps(default, ensure_ascii=False)
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def _fallback_fingerprint(data: Mapping[str, Any]) -> str:
    """R5 兜底：与 models.fingerprint_input() 同一兜底链，禁止自创算法。"""
    if data.get("phone"):
        return hashlib.sha256(f"phone|{data['phone']}".encode("utf-8")).hexdigest()
    parts = [data.get("name") or "", data.get("current_company") or "", data.get("current_role") or ""]
    if any(parts):
        raw = "name_company_title|" + "|".join(parts)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
    raw_text = data.get("raw_text") or data.get("source_url") or ""
    raw = "raw_hash|" + hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def candidate_record_to_cloud(record: Any) -> dict[str, Any]:
    """Convert a CandidateRecord (models.py) to a cloud_candidates row.

    R5：指纹唯一算法——一律 ``sha256(record.fingerprint_input())``。
    ``extra.browser_capture_fingerprint`` 不再充当行指纹（仍保留在 parsed_json），
    附件 sha256 由 fingerprint_input 的第三级兜底自然覆盖。
    """
    data = record.model_dump() if hasattr(record, "model_dump") else dict(record)
    if hasattr(record, "fingerprint_input"):
        fingerprint = hashlib.sha256(record.fingerprint_input().encode("utf-8")).hexdigest()
    else:
        identity = "|".join(
            str(data.get(key) or "")
            for key in ("phone", "email", "source_url", "name", "current_company", "current_title")
        )
        identity = identity or str(data.get("raw_text") or "")
        fingerprint = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    signals = data.get("activity_signals") or {}
    activity_score = data.get("activity_score")
    if not activity_score:
        # 活跃度在入库时确定性计算（activity.calculate_activity），
        # 信号含 employment_status/opportunity_intent/starred，无需后台爬取。
        try:
            from activity import calculate_activity

            activity_score, last_active, breakdown = calculate_activity(
                signals,
                starred=bool(data.get("starred")),
                employment_status=data.get("employment_status"),
                opportunity_intent=data.get("opportunity_intent"),
            )
            signals = {**signals, **breakdown}
            if last_active and not data.get("last_active_at"):
                data["last_active_at"] = last_active
        except Exception:
            activity_score = activity_score or 0
    return {
        "fingerprint": fingerprint,
        "name": data.get("name") or "",
        "platform": data.get("source_platform") or data.get("platform") or "",
        "source_candidate_id": (data.get("extra") or {}).get("source_candidate_id") or "",
        "source_url": data.get("source_url") or "",
        "source_type": data.get("source_type") or "",
        "title": data.get("current_title") or data.get("title") or "",
        "location": data.get("current_location") or data.get("location") or "",
        "current_company": data.get("current_company") or "",
        "current_role": data.get("current_title") or "",
        "phone": data.get("phone") or "",
        "email": data.get("email") or "",
        "undergraduate_school": data.get("undergraduate_school") or data.get("school") or "",
        "expected_salary": data.get("expected_salary") or "",
        "experiences_json": json.dumps(data.get("work_experiences", []), ensure_ascii=False, default=str),
        "education_json": json.dumps(data.get("education", {}), ensure_ascii=False, default=str),
        "keywords_json": json.dumps(data.get("skills", []) or data.get("keywords", []), ensure_ascii=False, default=str),
        "raw_text": data.get("raw_text") or "",
        "review_status": data.get("review_status", "pending"),
        "attachment_path": data.get("original_attachment_path") or data.get("attachment_path"),
        "attachment_sha256": data.get("attachment_sha256"),
        "collected_at": _parse_timestamp(data.get("captured_at") or data.get("collected_at")),
        "parsed_json": json.dumps(data, ensure_ascii=False, default=str),
        "activity_score": activity_score or 0,
        "activity_signals": json.dumps(signals, ensure_ascii=False, default=str),
        "owner": data.get("owner"),
        "visibility": data.get("visibility") or "team",
        "starred": bool(data.get("starred")),
        "last_active_at": _parse_timestamp(data.get("last_active_at")),
        "expected_title": data.get("expected_title") or None,
        "opportunity_intent": data.get("opportunity_intent") or None,
    }
