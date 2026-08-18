"""Anthropic Messages 协议 backend（Kimi coding 端点当前在用的协议）。"""
from __future__ import annotations

import time

import httpx

from .base import Response, ToolCall, Usage
from ..config import Config

MAX_RETRIES = 4
RETRYABLE_STATUS = {429, 500, 502, 503, 529}


class AnthropicBackend:
    name = "anthropic"

    def __init__(self, cfg: Config):
        self.cfg = cfg
        base = cfg.base_url.rstrip("/")
        self.url = base if base.endswith("/v1/messages") else f"{base}/v1/messages"
        # trust_env=False：Kimi 必须直连，忽略 shell 里的 Clash 代理
        self.client = httpx.Client(timeout=cfg.timeout_s, trust_env=False)

    def _headers(self) -> dict:
        return {
            "content-type": "application/json",
            "anthropic-version": "2023-06-01",
            "x-api-key": self.cfg.api_key,
            "authorization": f"Bearer {self.cfg.api_key}",
        }

    def complete(self, system: str, messages: list[dict], tools: list[dict], max_tokens: int = 8192) -> Response:
        payload: dict = {
            "model": self.cfg.model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = tools
        last_err: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                r = self.client.post(self.url, headers=self._headers(), json=payload)
                if r.status_code == 200:
                    return self._parse(r.json())
                if r.status_code not in RETRYABLE_STATUS:
                    raise RuntimeError(f"anthropic backend {r.status_code}: {r.text[:500]}")
                last_err = RuntimeError(f"anthropic backend {r.status_code}: {r.text[:200]}")
            except (httpx.TransportError, httpx.TimeoutException) as e:
                last_err = e
            if attempt < MAX_RETRIES:
                time.sleep(min(2 ** attempt * 2, 30))  # 2s,4s,8s,16s
        raise RuntimeError(f"anthropic backend 重试 {MAX_RETRIES} 次仍失败: {last_err}")

    @staticmethod
    def _parse(data: dict) -> Response:
        resp = Response(stop_reason=data.get("stop_reason") or "", raw=data)
        for block in data.get("content", []):
            btype = block.get("type")
            if btype == "text":
                resp.text += block.get("text", "")
            elif btype == "tool_use":
                resp.tool_calls.append(ToolCall(
                    id=block.get("id", ""),
                    name=block.get("name", ""),
                    arguments=block.get("input") or {},
                ))
        u = data.get("usage") or {}
        resp.usage = Usage(
            input_tokens=u.get("input_tokens", 0),
            output_tokens=u.get("output_tokens", 0),
            cache_read_tokens=u.get("cache_read_input_tokens", 0),
            cache_write_tokens=u.get("cache_creation_input_tokens", 0),
        )
        return resp


def assistant_message(resp: Response) -> dict:
    """把 Response 转回 anthropic assistant 消息块，追加进历史。"""
    content: list[dict] = []
    if resp.text:
        content.append({"type": "text", "text": resp.text})
    for tc in resp.tool_calls:
        content.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments})
    return {"role": "assistant", "content": content}


def tool_results_message(results: list[tuple[ToolCall, str, bool]]) -> dict:
    """results: (tool_call, output_text, is_error)"""
    content = [
        {
            "type": "tool_result",
            "tool_use_id": tc.id,
            "content": out,
            "is_error": is_err,
        }
        for tc, out, is_err in results
    ]
    return {"role": "user", "content": content}
