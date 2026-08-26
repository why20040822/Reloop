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
