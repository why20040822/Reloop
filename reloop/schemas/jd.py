"""Validated contracts for raw and structured job descriptions."""

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator


_SCALAR_FIELDS = (
    "title", "summary", "experience", "education", "location",
    "salary_range", "team_size", "reporting_line",
)
_LIST_FIELDS = (
    "responsibilities", "required_skills", "preferred_skills",
    "industry_keywords", "language_requirements",
)


class JDAnalysis(BaseModel):
    """The complete, displayable structure returned by the JD parser.

    2026-08-28 实测修复: step 模型偶发"类型翻转"——标量字段返回列表
    (education -> ["本科及以上学历"])、列表字段返回字符串
    (language_requirements -> "未提供")。strict 校验直接判死, 线上 2/3 概率失败。
    这里加 mode="before" 类型矫正(标量取列表拼接/列表按分隔符拆分), 空值校验
    仍由原 after 校验器负责(空白照样报错)。
    """

    model_config = ConfigDict(extra="ignore", strict=True)

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

    @field_validator(*_SCALAR_FIELDS, mode="before")
    @classmethod
    def coerce_scalar_type(cls, value):
        """标量字段类型矫正: list/tuple/set -> 取非空项拼接; None -> 未提供。"""
        if isinstance(value, (list, tuple, set)):
            parts = [str(v).strip() for v in value if str(v).strip()]
            return "、".join(parts) if parts else "未提供"
        if value is None:
            return "未提供"
        return value

    @field_validator(*_LIST_FIELDS, mode="before")
    @classmethod
    def coerce_list_type(cls, value):
        """列表字段类型矫正: str -> 按常见分隔符拆分; tuple/set -> list; None -> 未提供。"""
        if isinstance(value, str):
            parts = [p.strip() for p in re.split(r"[、，,;；/\n]+", value) if p.strip()]
            return parts or ["未提供"]
        if value is None:
            return ["未提供"]
        if isinstance(value, (tuple, set)):
            return list(value)
        return value

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

    model_config = ConfigDict(strict=True)

    jd_text: str = Field(max_length=50_000)

    @field_validator("jd_text")
    @classmethod
    def require_non_blank_jd(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("JD 不能为空")
        return cleaned
