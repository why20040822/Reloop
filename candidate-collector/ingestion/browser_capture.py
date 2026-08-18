"""Authorized browser-capture ingestion with original-PDF preservation."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from adapters.feishu_base import AttachmentUploadError, FeishuBaseAdapter
from ingestion.pipeline import (
    _sync_to_cloud,
    init_ingestion_tables,
    local_duplicate_exists,
    record_fingerprint,
)
from models import CandidateRecord
from parsers.unified_parser import parse_resume_file, parse_resume_text

# 插件端提取的 heading 若形如姓名则可直接采用——服务端文本提取在
# BOSS 推荐页（raw_text 从分节开始、无姓名行）上必然失败。
_HEADING_NAME_RE = re.compile(r"^[一-龥·A-Za-z]{2,10}(先生|女士)?$")
_HEADING_STOP = {
    "全文", "转发", "不合适", "打招呼", "更换职位沟通", "经历概览",
    "在线简历", "附件简历", "立即沟通", "聊一聊", "工作经历", "教育经历",
    "招聘规范",
}


def _heading_as_name(heading: str) -> str | None:
    candidate = (heading or "").strip().split("\n")[0].strip()
    if candidate and candidate not in _HEADING_STOP and _HEADING_NAME_RE.match(candidate):
        return candidate
    return None


DB_PATH = Path(__file__).resolve().parent.parent / "data" / "candidates.db"
BROWSER_FEISHU_MAPPING_PATH = (
    Path(__file__).resolve().parent.parent
    / "config"
    / "feishu_field_mapping_candidate.json"
)


def _db_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


class BrowserCapturePayload(BaseModel):
    schema_version: str = "2"
    url: str = ""
    title: str = ""
    heading: str = ""
    text: str = Field(min_length=10, max_length=600_000)
    platform: str = ""
    source_type: str = "browser_auto_import"
    source_candidate_id: str | None = Field(default=None, max_length=200)
    captured_at: str | None = None
    structured_data: dict[str, Any] | None = None
    profile: dict[str, Any] | None = None
    resume: dict[str, Any] | None = None
    pdf_fetch_failed_reason: str | None = Field(default=None, max_length=1000)
    dry_run: bool = False
    skip_duplicates: bool = True
    check_feishu_exists: bool = False


def _build_text_from_payload(payload: BrowserCapturePayload) -> str:
    structured = payload.structured_data or {}
    sections = structured.get("sections") if isinstance(structured.get("sections"), list) else None
    if sections:
        parts: list[str] = []
        for section in sections:
            if not isinstance(section, dict):
                continue
            heading = str(section.get("heading") or "").strip()
            body = str(section.get("text") or "").strip()
            if heading:
                parts.append(heading)
            if body:
                parts.append(body)
        combined = "\n".join(parts)
        if len(combined) >= 10:
            return combined
    return payload.text


def _find_profile_value(value: Any, keys: set[str], depth: int = 0) -> Any:
    if depth > 5:
        return None
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in keys and item not in (None, "", [], {}):
                return item
        for item in value.values():
            found = _find_profile_value(item, keys, depth + 1)
            if found not in (None, "", [], {}):
                return found
    elif isinstance(value, list):
        for item in value[:20]:
            found = _find_profile_value(item, keys, depth + 1)
            if found not in (None, "", [], {}):
                return found
    return None


def _profile_text(profile: dict[str, Any], *keys: str) -> str | None:
    value = _find_profile_value(profile, {key.lower() for key in keys})
    if isinstance(value, (str, int, float)):
        text = str(value).strip()
        return text or None
    if isinstance(value, dict):
        for key in ("name", "text", "value"):
            if value.get(key):
                return str(value[key]).strip() or None
    return None


def _merge_page_profile(record: CandidateRecord, payload: BrowserCapturePayload) -> None:
    profile = payload.profile or {}
    overrides = {
        "name": _profile_text(profile, "cn_name", "real_name", "display_name", "displayName", "name"),
        "phone": _profile_text(profile, "phone", "mobile", "telephone", "phone_number"),
        "email": _profile_text(profile, "email", "mail"),
        "current_company": _profile_text(profile, "current_company", "company_name", "company"),
        "current_title": _profile_text(profile, "current_title", "position", "job_title", "title"),
        "current_location": _profile_text(profile, "current_location", "location", "city"),
        "school": _profile_text(profile, "school_name", "school", "university"),
        "degree": _profile_text(profile, "degree", "education_level", "education"),
        "expected_salary": _profile_text(profile, "expected_salary", "expect_salary"),
        "opportunity_intent": _profile_text(profile, "opportunity_intent", "job_status"),
    }
    for field, value in overrides.items():
        if value:
            setattr(record, field, value)

    skills = _find_profile_value(profile, {"tech_stack", "skills", "skill_tags"})
    if isinstance(skills, list):
        clean = [str(item.get("name") if isinstance(item, dict) else item).strip() for item in skills]
        record.tech_stack = [item for item in clean if item][:100]
    elif isinstance(skills, str):
        record.tech_stack = [item.strip() for item in skills.replace("，", ",").split(",") if item.strip()][:100]


def build_candidate_from_capture(
    payload: BrowserCapturePayload,
    *,
    attachment_path: Path | str | None = None,
) -> CandidateRecord:
    """Build a canonical record; structured platform fields override PDF guesses."""
    text = _build_text_from_payload(payload)
    path = Path(attachment_path) if attachment_path else None
    if path and path.is_file():
        record = parse_resume_file(path)
        if not record.raw_text:
            record.raw_text = text
        record.original_attachment_path = str(path.resolve())
        record.attachment_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        record.attachment_mime_type = "application/pdf"
    else:
        record = parse_resume_text(
            text,
            title=payload.title,
            source_url=payload.url,
            source_type=payload.source_type,
        )

    platform = (payload.platform or "browser").lower()
    source_id = (payload.source_candidate_id or "").strip()
    source_url = payload.url
    if platform == "ttc" and source_id:
        source_id = source_id.upper()
        source_url = f"https://app.ttcadvisory.com/app/talent/{source_id}"

    record.source_url = source_url or record.source_url
    record.source_record_id = source_id or record.source_record_id
    record.source_platform = platform
    record.source_type = payload.source_type or "browser_auto_import"
    record.captured_at = payload.captured_at
    _merge_page_profile(record, payload)
    # 插件端从页面结构提取的姓名（如 BOSS 抽屉头部）优先于文本猜测。
    heading_name = _heading_as_name(payload.heading)
    if heading_name and (not record.name or record.name in _HEADING_STOP):
        record.name = heading_name
    # 脏身份数据不抛出：丢弃不可信的 source_record_id（以 URL 为准），
    # 打标记交人工复核，避免后续 fingerprint/ttc_pid 再次触发 ValueError。
    try:
        record.sync_source_identity()
    except ValueError as exc:
        record.extra["invalid_source_identity"] = str(exc)
        record.review_status = "needs_review"
        record.source_record_id = None
        record.sync_source_identity()
    # BOSS 页面开 DevTools 会被强制退出：插件自报的 DOM 诊断随记录上云，
    # 存 extra.boss_name_debug 供定位真实姓名元素。
    structured = payload.structured_data or {}
    if isinstance(structured.get("name_debug"), dict):
        record.extra["boss_name_debug"] = structured["name_debug"]
    record.extra.update({
        "browser_capture_schema": payload.schema_version,
        "resume_metadata": payload.resume or {},
        "browser_capture_fingerprint": hashlib.sha256(
            f"{platform}|{source_id}|{source_url}|{text[:4000]}".encode("utf-8")
        ).hexdigest(),
    })
    if not path:
        reason = payload.pdf_fetch_failed_reason or "平台未返回PDF原件"
        record.notes = f"未获取到PDF原件：{reason}。已按平台结构化资料写入。"
    return record


def _write_log(
    record: CandidateRecord,
    *,
    fingerprint: str,
    status: str,
    attachment_status: str,
    record_id: str | None = None,
    table_id: str | None = None,
    error: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    with closing(_db_conn()) as conn:
        conn.execute(
            """
            INSERT INTO ingestion_log (
                fingerprint, source_record_id, source_platform, source_url,
                attachment_sha256, phone, name, current_company, current_title,
                feishu_record_id, feishu_table_id, feishu_write_status,
                attachment_status, review_status, error_message, dry_run_payload,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            ON CONFLICT(fingerprint) DO UPDATE SET
                source_record_id=excluded.source_record_id,
                source_platform=excluded.source_platform,
                source_url=excluded.source_url,
                attachment_sha256=excluded.attachment_sha256,
                phone=excluded.phone,
                name=excluded.name,
                current_company=excluded.current_company,
                current_title=excluded.current_title,
                feishu_record_id=COALESCE(excluded.feishu_record_id, ingestion_log.feishu_record_id),
                feishu_table_id=COALESCE(excluded.feishu_table_id, ingestion_log.feishu_table_id),
                feishu_write_status=excluded.feishu_write_status,
                attachment_status=excluded.attachment_status,
                retry_count=CASE WHEN excluded.feishu_write_status IN ('failed','partial')
                    THEN ingestion_log.retry_count + 1 ELSE ingestion_log.retry_count END,
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
                record_id,
                table_id,
                status,
                attachment_status,
                "pending",
                error,
                json.dumps(payload or {"candidate": record.model_dump()}, ensure_ascii=False),
            ),
        )
        conn.commit()


def import_browser_capture(
    payload: BrowserCapturePayload,
    *,
    attachment_path: Path | str | None = None,
    feishu_adapter: FeishuBaseAdapter | None = None,
) -> dict[str, Any]:
    init_ingestion_tables()
    record = build_candidate_from_capture(payload, attachment_path=attachment_path)
    fingerprint = record_fingerprint(record)
    # Browser-extension imports are intentionally pinned to the user-selected
    # Base. Do not let a process-wide FEISHU_MAPPING_FILE override redirect the
    # automatic browser path to another database.
    adapter = feishu_adapter or FeishuBaseAdapter(
        mapping_path=BROWSER_FEISHU_MAPPING_PATH, validate_schema=True
    )

    duplicate = local_duplicate_exists(record)
    if duplicate and payload.skip_duplicates:
        if (
            record.original_attachment_path
            and duplicate.get("feishu_record_id")
            and duplicate.get("attachment_status") != "uploaded"
        ):
            target = FeishuBaseAdapter(
                table_id=duplicate.get("feishu_table_id") or adapter.table_id,
                validate_schema=True,
            )
            try:
                target.upload_attachment(
                    record.original_attachment_path,
                    duplicate["feishu_record_id"],
                    target.attachment_field_id(),
                    expected_sha256=record.attachment_sha256,
                )
                _write_log(
                    record,
                    fingerprint=fingerprint,
                    status="success",
                    attachment_status="uploaded",
                    record_id=duplicate["feishu_record_id"],
                    table_id=target.table_id,
                )
                return {
                    "ok": True,
                    "action": "attachment_uploaded",
                    "candidate": record.model_dump(),
                    "fingerprint": fingerprint,
                    "feishu_record_id": duplicate["feishu_record_id"],
                    "feishu_table_id": target.table_id,
                    "attachment_uploaded": True,
                }
            except Exception as exc:
                _write_log(
                    record,
                    fingerprint=fingerprint,
                    status="partial",
                    attachment_status="failed",
                    record_id=duplicate["feishu_record_id"],
                    table_id=target.table_id,
                    error=str(exc),
                )
                return {"ok": False, "action": "attachment_retry_pending", "error": str(exc)}
        return {
            "ok": True,
            "action": "skipped_duplicate",
            "candidate": record.model_dump(),
            "fingerprint": fingerprint,
            "feishu_record_id": duplicate.get("feishu_record_id"),
            "feishu_table_id": duplicate.get("feishu_table_id"),
            "duplicate": duplicate,
        }

    if payload.check_feishu_exists and adapter.record_exists(record):
        return {"ok": True, "action": "skipped_duplicate_feishu", "candidate": record.model_dump()}

    if payload.dry_run:
        dry_payload = adapter.dry_run(record)
        _write_log(
            record,
            fingerprint=fingerprint,
            status="dry_run",
            attachment_status="pending" if record.original_attachment_path else "none",
            payload={"candidate": record.model_dump(), "feishu_payload": dry_payload},
        )
        return {"ok": True, "action": "dry_run", "candidate": record.model_dump(), "feishu_payload": dry_payload}

    # 云端人才库是第一目标：先写 cloud_candidates，飞书写失败不再阻断入库。
    _sync_to_cloud(record)

    try:
        response = adapter.create_record(record)
        record_id = _extract_record_id(response)
        if not record_id:
            raise RuntimeError(f"Feishu create_record did not return a record_id: {response}")
        table_id = response.get("feishu_table_id") or getattr(adapter, "table_id", None)
        if not isinstance(table_id, str):
            table_id = None
        attachment_uploaded = bool(response.get("attachment_uploaded"))
        attachment_status = (
            "uploaded" if attachment_uploaded else
            "pending" if record.original_attachment_path else "none"
        )
        write_status = "partial" if attachment_status == "pending" else "success"
        _write_log(
            record,
            fingerprint=fingerprint,
            status=write_status,
            attachment_status=attachment_status,
            record_id=record_id,
            table_id=table_id,
            payload={"candidate": record.model_dump(), "feishu_payload": adapter.dry_run(record)},
        )
        action = "skipped_duplicate_feishu" if response.get("idempotent_existing") else "created"
        if attachment_status == "pending":
            action = "attachment_retry_pending"
        return {
            "ok": attachment_status != "pending",
            "action": action,
            "candidate": record.model_dump(),
            "fingerprint": fingerprint,
            "feishu_record_id": record_id,
            "feishu_table_id": table_id,
            "attachment_uploaded": attachment_uploaded,
            "fallback_reason": response.get("fallback_reason"),
        }
    except AttachmentUploadError as exc:
        _write_log(
            record,
            fingerprint=fingerprint,
            status="partial",
            attachment_status="failed",
            record_id=exc.record_id,
            table_id=exc.table_id,
            error=str(exc),
        )
        return {
            "ok": False,
            "action": "attachment_retry_pending",
            "feishu_record_id": exc.record_id,
            "feishu_table_id": exc.table_id,
            "error": str(exc),
        }
    except Exception as exc:
        _write_log(
            record,
            fingerprint=fingerprint,
            status="failed",
            attachment_status="pending" if record.original_attachment_path else "none",
            error=str(exc),
        )
        return {
            # 云端已写入，飞书失败降级为警告，不再判定整单失败。
            "ok": True,
            "action": "created_cloud_only",
            "candidate": record.model_dump(),
            "fingerprint": fingerprint,
            "warning": "飞书写入失败，已仅写入云端人才库：" + str(exc)[:120],
        }


def _extract_record_id(resp: dict[str, Any]) -> str | None:
    data = resp.get("data", {})
    if isinstance(data, dict):
        records = data.get("records")
        if isinstance(records, list) and records:
            return records[0].get("record_id")
        record_ids = data.get("record_id_list")
        if isinstance(record_ids, list) and record_ids:
            return record_ids[0]
        return data.get("record_id")
    if isinstance(data, list) and data:
        return data[0].get("record_id")
    return None
