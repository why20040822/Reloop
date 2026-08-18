"""token 粗估与工具结果截断。中文 1 字 ≈ 1 token，英文 4 字符 ≈ 1 token，取保守混合估算。"""
from __future__ import annotations


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    return cjk + max(1, (len(text) - cjk) // 4)


def estimate_messages_tokens(messages: list[dict]) -> int:
    total = 0
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            total += estimate_tokens(content)
        elif isinstance(content, list):
            for b in content:
                if b.get("type") == "text":
                    total += estimate_tokens(b.get("text", ""))
                elif b.get("type") == "tool_result":
                    total += estimate_tokens(str(b.get("content", "")))
                elif b.get("type") == "tool_use":
                    total += estimate_tokens(str(b.get("input", "")))
    return total


def truncate_head_tail(text: str, head: int = 2500, tail: int = 2500) -> str:
    """超长输出保留头尾，中间以标记省略。"""
    if len(text) <= head + tail + 100:
        return text
    elided = len(text) - head - tail
    return f"{text[:head]}\n...[elided {elided} chars]...\n{text[-tail:]}"


def truncate_lines(text: str, max_lines: int = 400) -> str:
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    half = max_lines // 2
    kept = lines[:half] + [f"...[elided {len(lines) - max_lines} lines]..."] + lines[-half:]
    return "\n".join(kept)
