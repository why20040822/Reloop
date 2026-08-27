"""Validated contracts for raw and structured job descriptions."""

import base64
from io import BytesIO
import re

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


MAX_JD_IMAGES = 4
MAX_JD_IMAGE_BYTES = 8 * 1024 * 1024
_DATA_IMAGE_URL = re.compile(r"^data:(image/(?:jpeg|png|gif|webp));base64,([A-Za-z0-9+/]*={0,2})$")


def _validate_image_data_url(value: str) -> str:
    match = _DATA_IMAGE_URL.fullmatch(value)
    if match is None:
        raise ValueError("图片必须是 JPEG/PNG/GIF/WebP data URL")
    encoded = match.group(2)
    max_encoded_bytes = ((MAX_JD_IMAGE_BYTES + 2) // 3) * 4 + 4
    if len(encoded) > max_encoded_bytes:
        raise ValueError("图片解码后不能超过 8 MiB")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise ValueError("图片 data URL 无效") from exc
    if not decoded or len(decoded) > MAX_JD_IMAGE_BYTES:
        raise ValueError("图片解码后不能超过 8 MiB")
    media_type = match.group(1)
    valid_signatures = {
        "image/jpeg": decoded.startswith(b"\xff\xd8\xff"),
        "image/png": decoded.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/gif": decoded.startswith((b"GIF87a", b"GIF89a")),
        "image/webp": len(decoded) >= 12 and decoded.startswith(b"RIFF") and decoded[8:12] == b"WEBP",
    }
    if not valid_signatures[media_type]:
        raise ValueError("图片内容与 data URL 类型不匹配")
    try:
        with Image.open(BytesIO(decoded)) as image:
            image.verify()
        with Image.open(BytesIO(decoded)) as image:
            image.load()
    except (OSError, SyntaxError, UnidentifiedImageError, ValueError) as exc:
        raise ValueError("图片数据不完整或已损坏") from exc
    return value


class JDAnalysis(BaseModel):
    """The complete, displayable structure returned by the JD parser."""

    model_config = ConfigDict(extra="forbid", strict=True)

    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    responsibilities: list[str] = Field(min_length=1)
    required_skills: list[str] = Field(min_length=1)
    preferred_skills: list[str] = Field(min_length=1)
    experience: str = Field(min_length=1)
    education: str = Field(min_length=1)
    location: str = Field(min_length=1)
    industry_keywords: list[str] = Field(min_length=1)
    salary_range: str = Field(min_length=1)
    team_size: str = Field(min_length=1)
    reporting_line: str = Field(min_length=1)
    language_requirements: list[str] = Field(min_length=1)
    company_name: str | None = Field(default=None, max_length=128)

    @field_validator(
        "title",
        "summary",
        "experience",
        "education",
        "location",
        "salary_range",
        "team_size",
        "reporting_line",
    )
    @classmethod
    def normalize_scalar_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("字段不能为空")
        return cleaned

    @field_validator("company_name")
    @classmethod
    def normalize_company_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator(
        "responsibilities",
        "required_skills",
        "preferred_skills",
        "industry_keywords",
        "language_requirements",
    )
    @classmethod
    def normalize_list_text(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            cleaned = value.strip()
            if not cleaned:
                raise ValueError("列表项不能为空")
            if cleaned not in seen:
                seen.add(cleaned)
                normalized.append(cleaned)
        if not normalized:
            raise ValueError("列表不能为空")
        return normalized


class JDParseRequest(BaseModel):
    """A bounded raw JD submitted for parse preview only."""

    model_config = ConfigDict(extra="forbid", strict=True)

    jd_text: str = Field(default="", max_length=50_000)
    images: list[str] = Field(default_factory=list, max_length=MAX_JD_IMAGES)

    @field_validator("jd_text")
    @classmethod
    def require_non_blank_jd(cls, value: str) -> str:
        cleaned = value.strip()
        return cleaned

    @field_validator("images")
    @classmethod
    def validate_images(cls, values: list[str]) -> list[str]:
        return [_validate_image_data_url(value) for value in values]

    @model_validator(mode="after")
    def require_text_or_images(self) -> "JDParseRequest":
        if not self.jd_text and not self.images:
            raise ValueError("JD 文本或图片不能为空")
        return self


class JDParseResponse(BaseModel):
    """Structured parse preview plus its editable raw-JD source text."""

    model_config = ConfigDict(extra="forbid", strict=True)

    analysis: JDAnalysis
    source_text: str = Field(min_length=1)

    @field_validator("source_text")
    @classmethod
    def require_source_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("source_text 不能为空")
        return cleaned
