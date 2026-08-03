"""All HTTP request schemas for the Reloop API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

MAX_TEXT = 600_000


class CapturePayload(BaseModel):
    url: str = ""
    title: str = ""
    heading: str = ""
    text: str = Field(min_length=10, max_length=MAX_TEXT)
    platform: str = ""
    source_type: str = "authorized_visible_page"
    captured_at: str | None = None
    structured_data: dict[str, Any] | None = None


class TextPayload(BaseModel):
    text: str = Field(min_length=10, max_length=MAX_TEXT)
    title: str = "手动导入"
    url: str = ""


class UrlPayload(BaseModel):
    url: str


class LocalDownloadPayload(BaseModel):
    path: str = Field(min_length=1, max_length=1000)
    source_url: str = ""


class FeishuWebMessagePayload(BaseModel):
    client_id: str = Field(default="default", max_length=120)
    chat_title: str = Field(default="", max_length=300)
    sender: str = Field(default="", max_length=120)
    text: str = Field(min_length=1, max_length=80_000)
    url: str = Field(default="", max_length=2000)
    message_time: str = Field(default="", max_length=120)
    page_title: str = Field(default="", max_length=300)
    captured_at: str | None = None
    auto_reply: bool = True


class FeishuReplyAckPayload(BaseModel):
    reply_id: int
    status: str = Field(default="filled", max_length=40)


class IngestFilePayload(BaseModel):
    path: str = Field(min_length=1, max_length=1000)
    dry_run: bool = True
    skip_duplicates: bool = True
    check_feishu_exists: bool = False
    source_platform: str | None = Field(default=None, max_length=40)
    source_url: str | None = Field(default=None, max_length=2000)
    source_extra: dict[str, Any] | None = None


class IngestTextPayload(BaseModel):
    text: str = Field(min_length=10, max_length=MAX_TEXT)
    title: str = "手动导入"
    source_url: str = ""
    dry_run: bool = True


class IngestFromUrlPayload(BaseModel):
    url: str = Field(min_length=10, max_length=2000)
    dry_run: bool = True


class SearchPayload(BaseModel):
    q: str = Field(min_length=1, max_length=200)
    min_score: int | None = Field(default=None, ge=0, le=100)
    platform: str | None = Field(default=None, max_length=40)
    limit: int = Field(default=50, ge=1, le=200)


class FeedbackPayload(BaseModel):
    candidate_id: int | None = None
    fingerprint: str | None = Field(default=None, max_length=120)
    feedback_type: str = Field(min_length=1, max_length=80)
    field: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=1000)


class ReviewCorrections(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=120)
    current_company: str | None = Field(default=None, max_length=120)
    current_title: str | None = Field(default=None, max_length=120)
    school: str | None = Field(default=None, max_length=120)
    expected_salary: str | None = Field(default=None, max_length=80)
    work_experiences: list[dict[str, Any]] | None = None
    education: dict[str, Any] | None = None


class ReviewRejectPayload(BaseModel):
    reason: str = Field(default="", max_length=1000)


__all__ = [
    "CapturePayload", "TextPayload", "UrlPayload", "LocalDownloadPayload",
    "FeishuWebMessagePayload", "FeishuReplyAckPayload", "IngestFilePayload",
    "IngestTextPayload", "IngestFromUrlPayload", "SearchPayload", "FeedbackPayload",
    "ReviewCorrections", "ReviewRejectPayload",
]
