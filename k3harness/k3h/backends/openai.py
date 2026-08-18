"""OpenAI chat/completions 兼容 backend（备选协议，probe 确认可用后启用）。"""
from __future__ import annotations

import json
import uuid

import httpx

from .base import Response, ToolCall, Usage
from ..config import Config


class OpenAIBackend:
    name = "openai"

    def __init__(self, cfg: Config, base_url: str | None = None):
        self.cfg = cfg
        base = (base_url or cfg.base_url).rstrip("/")
        self.url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
        self.client = httpx.Client(timeout=cfg.timeout_s, trust_env=False)

    def complete(self, system: str, messages: list[dict], tools: list[dict], max_tokens: int = 8192) -> Response:
        oa_messages = self._convert_messages(system, messages)
        payload: dict = {
            "model": self.cfg.model,
            "max_tokens": max_tokens,
            "messages": oa_messages,
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("input_schema", {}),
                    },
                }
                for t in tools
            ]
        r = self.client.post(
            self.url,
            headers={"content-type": "application/json", "authorization": f"Bearer {self.cfg.api_key}"},
            json=payload,
        )
        if r.status_code != 200:
            raise RuntimeError(f"openai backend {r.status_code}: {r.text[:500]}")
        return self._parse(r.json())

    @staticmethod
    def _convert_messages(system: str, messages: list[dict]) -> list[dict]:
        """内部历史是 anthropic 块格式，这里转 openai 格式。"""
        out: list[dict] = []
        if system:
            out.append({"role": "system", "content": system})
        for m in messages:
            role, content = m["role"], m["content"]
            if isinstance(content, str):
                out.append({"role": role, "content": content})
                continue
            if role == "assistant":
                text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
                tool_calls = [
                    {
                        "id": b["id"],
                        "type": "function",
                        "function": {"name": b["name"], "arguments": json.dumps(b.get("input") or {}, ensure_ascii=False)},
                    }
                    for b in content if b.get("type") == "tool_use"
                ]
                msg: dict = {"role": "assistant", "content": text or None}
                if tool_calls:
                    msg["tool_calls"] = tool_calls
                out.append(msg)
            else:  # user，可能含 tool_result 块
                tool_results = [b for b in content if b.get("type") == "tool_result"]
                if tool_results:
                    for b in tool_results:
                        out.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": b.get("content", "")})
                else:
                    text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
                    out.append({"role": "user", "content": text})
        return out

    @staticmethod
    def _parse(data: dict) -> Response:
        resp = Response(raw=data)
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        resp.text = msg.get("content") or ""
        resp.stop_reason = choice.get("finish_reason") or ""
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            resp.tool_calls.append(ToolCall(id=tc.get("id") or f"call_{uuid.uuid4().hex[:8]}", name=fn.get("name", ""), arguments=args))
        u = data.get("usage") or {}
        resp.usage = Usage(input_tokens=u.get("prompt_tokens", 0), output_tokens=u.get("completion_tokens", 0))
        return resp
