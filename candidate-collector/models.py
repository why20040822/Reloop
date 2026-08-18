"""Unified candidate record model.

This module defines the canonical data structure produced by every ingestion
path (browser extension, email attachment, local file, public URL, Feishu web
message).  Downstream adapters such as the SQLite store and the Feishu Base
writer consume this model, so ingestion sources do not need to know anything
about specific storage backends.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


TTC_PID_RE = re.compile(r"^(?:PL)?\d+$", re.I)


def ttc_pid_from_canonical_url(value: Optional[str]) -> Optional[str]:
    """Return the TTC PID only for an exact canonical talent URL."""
    if not value:
        return None
    try:
        parsed = urllib.parse.urlsplit(value)
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or parsed.hostname != "app.ttcadvisory.com"
        or parsed.query
        or parsed.fragment
    ):
        return None
    match = re.fullmatch(r"/app/talent/((?:PL)?\d+)/?", parsed.path, re.I)
    return match.group(1).upper() if match else None


class WorkExperience(BaseModel):
    company: str | None = None
    role: str | None = None
    period: str | None = None
    location: str | None = None
    highlights: list[str] = Field(default_factory=list)
    # Evidence snippet supporting this entry, extracted from raw text.
    evidence: str | None = None


class Education(BaseModel):
    school: str | None = None
    major: str | None = None
    degree: str | None = None
    period: str | None = None
    graduation_year: int | None = None
    tier: str | None = None  # e.g. 985 / 211 / other


class ProjectExperience(BaseModel):
    name: str | None = None
    role: str | None = None
    period: str | None = None
    description: str | None = None
    skills: list[str] = Field(default_factory=list)


class FieldConfidence(BaseModel):
    field: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str | None = None
    note: str | None = None


class CandidateRecord(BaseModel):
    """Canonical candidate record.

    Every ingestion path must return a ``CandidateRecord``.  Fields are
    intentionally permissive (many optional) because source quality varies:
    PDFs may be scanned, browser pages may be partial, and email attachments may
    be malformed.  ``null`` or empty values are preferred over fabricated
    values.
    """

    # Identity
    name: str | None = None
    english_name: str | None = None
    aliases: list[str] = Field(default_factory=list)

    # Contact
    phone: str | None = None
    email: str | None = None

    # Current situation
    current_company: str | None = None
    current_title: str | None = None
    current_location: str | None = None
    employment_status: str | None = None  # 在职/离职/看机会等

    # Reloop 运营契约（活跃度/归属/可见性）
    owner: str | None = None  # 负责顾问
    visibility: str = "team"  # private=仅自己可见 / team=组内可见
    starred: bool = False  # 顾问星标
    activity_score: int | None = None  # 入库时由 activity.calculate_activity 计算
    activity_signals: dict[str, Any] = Field(default_factory=dict)
    last_active_at: str | None = None

    # Intent
    expected_location: str | None = None
    expected_salary: str | None = None
    expected_title: str | None = None
    opportunity_intent: str | None = None  # 是否看机会

    # Education
    school: str | None = None
    degree: str | None = None
    undergraduate_graduation_year: int | None = None
    education: Education | None = None
    education_list: list[Education] = Field(default_factory=list)

    # Skills
    skills: list[str] = Field(default_factory=list)
    tech_stack: list[str] = Field(default_factory=list)
    ai_experience: str | None = None

    # Experience
    work_experiences: list[WorkExperience] = Field(default_factory=list)
    project_experiences: list[ProjectExperience] = Field(default_factory=list)

    # Full text
    raw_text: str = ""
    markdown: str | None = None

    # Source metadata
    source_platform: str | None = None
    source_url: str | None = None
    source_record_id: Optional[str] = None
    source_message_id: str | None = None
    source_type: str = "unknown"
    consent_or_access_basis: str | None = None
    captured_at: str | None = None

    # Attachments
    original_attachment_path: str | None = None
    attachment_sha256: str | None = None
    attachment_mime_type: str | None = None

    # Parser metadata
    parser_name: str | None = None
    parser_version: str | None = None
    parse_confidence: float | None = None
    field_confidences: list[FieldConfidence] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)

    # Quality / review
    review_status: str = "pending"  # pending / success / failed / needs_review
    completeness_score: float | None = None  # 0-1 data completeness estimate

    # Extra
    notes: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str | None) -> str | None:
        if not value:
            return None
        digits = "".join(ch for ch in value if ch.isdigit())
        if len(digits) == 11 and digits.startswith("1"):
            return digits
        if len(digits) >= 7:
            return digits
        return None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        if not value:
            return None
        value = value.strip()
        return value or None

    def model_post_init(self, __context: Any) -> None:
        self.sync_source_identity()
        if not self.captured_at:
            self.captured_at = datetime.now(timezone.utc).isoformat()
        # Derive education convenience fields from education_list if not set.
        if not self.education and self.education_list:
            self.education = self.education_list[0]
        if self.education and not self.school:
            self.school = self.education.school
        if self.education and not self.degree:
            self.degree = self.education.degree
        if self.education and self.education.graduation_year and not self.undergraduate_graduation_year:
            self.undergraduate_graduation_year = self.education.graduation_year

    def sync_source_identity(self) -> None:
        """Derive and validate source identity after ingestion metadata changes."""
        url_pid = ttc_pid_from_canonical_url(self.source_url)
        if url_pid:
            if self.source_record_id and self.source_record_id != url_pid:
                raise ValueError(
                    "TTC source_record_id does not match the canonical talent URL"
                )
            self.source_record_id = url_pid
            self.source_platform = "ttc"
            self.source_url = f"https://app.ttcadvisory.com/app/talent/{url_pid}"

    @property
    def ttc_pid(self) -> Optional[str]:
        """Stable TTC business key, or ``None`` for non-TTC records."""
        url_pid = ttc_pid_from_canonical_url(self.source_url)
        if url_pid:
            if self.source_record_id and self.source_record_id != url_pid:
                raise ValueError(
                    "TTC source_record_id does not match the canonical talent URL"
                )
            return url_pid
        platform = (self.source_platform or "").strip().lower()
        legacy_unscoped = not self.source_platform and self.source_type == "unknown"
        if (
            self.source_record_id
            and TTC_PID_RE.fullmatch(self.source_record_id)
            and (platform == "ttc" or legacy_unscoped)
        ):
            return self.source_record_id
        return None

    def fingerprint_input(self) -> str:
        """Return a stable string used for duplicate detection.

        Prefer TTC's stable person_leads_id, then SHA-256 of the attachment,
        phone, and name+company+title.  When all identifying fields are empty,
        fall back to a hash of the raw text so different empty records do not
        collapse to the same fingerprint.
        """
        if self.ttc_pid:
            return f"ttc_pid|{self.ttc_pid}"
        if self.source_record_id:
            platform = (self.source_platform or self.source_type or "unknown").lower()
            return f"source_record|{platform}|{self.source_record_id}"
        if self.attachment_sha256:
            return f"sha256|{self.attachment_sha256}"
        if self.phone:
            return f"phone|{self.phone}"
        parts = [self.name or "", self.current_company or "", self.current_title or ""]
        if any(parts):
            return "name_company_title|" + "|".join(parts)
        raw = self.raw_text or self.source_url or self.captured_at or ""
        return "raw_hash|" + hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def to_db_dict(self) -> dict[str, Any]:
        """Flatten the record for the existing SQLite candidates table.

        This is intentionally conservative: it maps only to fields that already
        exist in ``app.py`` to avoid schema changes in the first iteration.
        """
        return {
            "name": self.name or "待识别候选人",
            "platform": self.source_platform or "本地导入",
            "source_url": self.source_url or "",
            "source_type": self.source_type,
            "title": self.original_attachment_path or self.source_url or "",
            "location": self.current_location or self.expected_location or "",
            "explicit_age": None,
            "experience_years": None,
            "undergraduate_school": self.school or "",
            "undergraduate_tier": self.education.tier if self.education else "",
            "current_company": self.current_company or "",
            "current_role": self.current_title or "",
            "employment_status": self.employment_status or "",
            "expected_salary": self.expected_salary or "",
            "summary": "",
            "experiences_json": json.dumps(self.model_dump().get("work_experiences", []), ensure_ascii=False),
            "education_json": json.dumps(self.model_dump().get("education", {}), ensure_ascii=False),
            "keywords_json": json.dumps(self.skills, ensure_ascii=False),
            "hard_filter_reason": "",
            "raw_text": self.raw_text,
        }
