"""会话历史 + 主动 compact（阈值远低于 1M，保险丝而非常态）。"""
from __future__ import annotations

from .backends.base import ChatBackend
from .backends.anthropic import assistant_message, tool_results_message
from .truncate import estimate_messages_tokens

SUMMARY_PROMPT = "把以下对话历史压缩成 <=600 字的中文摘要，保留：任务目标、已完成的操作及结果、关键文件路径、未解决的问题。只输出摘要。\n\n"


class Session:
    def __init__(self, compact_threshold: int = 120_000, keep_recent: int = 6):
        self.messages: list[dict] = []
        self.compact_threshold = compact_threshold
        self.keep_recent = keep_recent
        self.compacts = 0

    def add_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def add_assistant(self, resp) -> None:
        self.messages.append(assistant_message(resp))

    def add_tool_results(self, results) -> None:
        self.messages.append(tool_results_message(results))

    def estimated_tokens(self) -> int:
        return estimate_messages_tokens(self.messages)

    def maybe_compact(self, backend: ChatBackend, max_tokens: int = 2048) -> bool:
        """超阈值时：保留首条 user + 最近 N 条，中间段 LLM 摘要替换；失败则机械丢弃。"""
        if self.estimated_tokens() < self.compact_threshold or len(self.messages) <= self.keep_recent + 2:
            return False
        first = self.messages[0]
        recent = self.messages[-self.keep_recent:]
        middle = self.messages[1:-self.keep_recent]
        try:
            flat = []
            for m in middle:
                content = m.get("content")
                if isinstance(content, str):
                    flat.append(f"[{m['role']}] {content[:2000]}")
                else:
                    for b in content:
                        if b.get("type") == "text":
                            flat.append(f"[{m['role']}] {b['text'][:2000]}")
                        elif b.get("type") == "tool_result":
                            flat.append(f"[tool] {str(b.get('content'))[:500]}")
            resp = backend.complete("", [{"role": "user", "content": SUMMARY_PROMPT + "\n".join(flat)}], tools=[], max_tokens=max_tokens)
            summary = resp.text or "(摘要失败，历史已机械截断)"
        except Exception:
            summary = "(摘要调用失败，中间历史已机械截断)"
        self.messages = [first, {"role": "user", "content": f"[历史压缩摘要]\n{summary}"}] + recent
        self.compacts += 1
        return True
