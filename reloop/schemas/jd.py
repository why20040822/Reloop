"""Validated contracts for raw and structured job descriptions."""

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
