"""Backend-only DeepSeek parser for structured job descriptions."""

import json

import httpx
from pydantic import ValidationError

from reloop.config import settings
from reloop.schemas.jd import JDAnalysis


class JDParserUnavailable(RuntimeError):
    """Raised when the DeepSeek service has not been configured."""


class JDParserError(RuntimeError):
    """Raised when DeepSeek cannot produce a valid structured JD."""


def build_jd_messages(jd_text: str) -> list[dict[str, str]]:
    """Build the constrained chat prompt without exposing configuration values."""
    return [
        {
            "role": "system",
            "content": (
                "你是招聘岗位分析助手。仅返回 JSON 对象，且必须包含 title、summary、"
                "responsibilities、required_skills、preferred_skills、experience、education、"
                "location、industry_keywords、salary_range、team_size、reporting_line、"
                "language_requirements。无法从 JD 得知的标量字段使用“未提供”，"
                "列表字段使用 [“未提供”]。所有列表字段必须是非空字符串数组。"
            ),
        },
        {"role": "user", "content": jd_text},
    ]


class DeepSeekJDParser:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.api_key = settings.deepseek_api_key if api_key is None else api_key
        self.base_url = base_url or settings.deepseek_base_url
        self.model = model or settings.deepseek_model
        self.timeout_seconds = timeout_seconds or settings.deepseek_timeout_seconds
        self.transport = transport

    def parse(self, jd_text: str) -> JDAnalysis:
        cleaned = jd_text.strip()
        if not self.api_key:
            raise JDParserUnavailable("DeepSeek JD 解析尚未配置")
        payload = {
            "model": self.model,
            "messages": build_jd_messages(cleaned),
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout_seconds) as client:
                response = client.post(
                    f"{self.base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
            return JDAnalysis.model_validate(json.loads(content))
        except httpx.TimeoutException as exc:
            raise JDParserError("DeepSeek JD 解析超时，请稍后重试") from exc
        except (httpx.HTTPError, IndexError, KeyError, TypeError, ValueError, ValidationError) as exc:
            raise JDParserError("DeepSeek 未返回有效的 JD 结构") from exc
