"""Browser capture model and parser used by the standalone cloud gateway."""
from __future__ import annotations

import hashlib
from typing import Any

from pydantic import BaseModel, Field

from models import CandidateRecord
from parsers.unified_parser import parse_resume_text


class BrowserCapturePayload(BaseModel):
    url: str = ""
    title: str = ""
    heading: str = ""
    text: str = Field(min_length=10, max_length=600_000)
    platform: str = ""
    source_candidate_id: str | None = Field(default=None, max_length=255)
    source_type: str = "browser_capture"
    captured_at: str | None = None
    structured_data: dict[str, Any] | None = None
    dry_run: bool = False
    skip_duplicates: bool = True
    check_feishu_exists: bool = False
    page_session_id: str = Field(default="", max_length=255)
    plugin_version: str = Field(default="", max_length=32)


def _capture_text(payload: BrowserCapturePayload) -> str:
    structured = payload.structured_data or {}
    sections = structured.get("sections")
    if not isinstance(sections, list):
        return payload.text

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
    return combined if len(combined) >= 10 else payload.text


def build_candidate_from_capture(payload: BrowserCapturePayload) -> CandidateRecord:
    """Convert visible candidate-page content into the canonical cloud record."""
    text = _capture_text(payload)
    source_type = payload.source_type or "browser_capture"
    source_platform = payload.platform or source_type
    record = parse_resume_text(
        text,
        title=payload.title,
        source_url=payload.url,
        source_type=source_type,
    )
    record.source_url = payload.url or record.source_url
    record.source_platform = source_platform
    record.source_type = source_type
    if payload.source_candidate_id:
        record.extra["source_candidate_id"] = payload.source_candidate_id
    record.captured_at = payload.captured_at
    record.raw_text = text
    fingerprint_input = f"{payload.url or ''}|{text[:4000]}"
    record.extra["browser_capture_fingerprint"] = hashlib.sha256(
        fingerprint_input.encode("utf-8")
    ).hexdigest()
    return record
