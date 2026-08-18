"""文件工具：read_file / write_file / edit_file / list_dir。"""
from __future__ import annotations

import difflib
from pathlib import Path

from .base import ToolContext, ToolError
from ..truncate import truncate_lines


def _resolve(ctx: ToolContext, path: str) -> Path:
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = ctx.cwd / p
    return p.resolve()


def read_file(ctx: ToolContext, path: str, offset: int = 0, limit: int = 400) -> str:
    p = _resolve(ctx, path)
    if not p.is_file():
        raise ToolError(f"文件不存在: {p}")
    lines = p.read_text(errors="replace").splitlines()
    total = len(lines)
    chunk = lines[offset: offset + limit]
    body = "\n".join(f"{offset + i + 1}\t{ln}" for i, ln in enumerate(chunk))
    note = f"[{p} 共 {total} 行，显示 {offset + 1}-{offset + len(chunk)}]"
    if offset + limit < total:
        note += f" 还有 {total - offset - limit} 行，用 offset 继续读"
    return f"{note}\n{truncate_lines(body, limit + 5)}"


def write_file(ctx: ToolContext, path: str, content: str) -> str:
    p = _resolve(ctx, path)
    if ctx.mode == "dry-run":
        old = p.read_text(errors="replace") if p.is_file() else ""
        diff = "\n".join(difflib.unified_diff(old.splitlines(), content.splitlines(), lineterm="", n=2))
        return f"[DRY-RUN] 拟写入 {p}（{len(content)} chars）。diff 预览：\n{truncate_lines(diff, 60)}\n（apply 模式才落盘）"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return f"已写入 {p}（{len(content)} chars）"


def edit_file(ctx: ToolContext, path: str, old_string: str, new_string: str) -> str:
    p = _resolve(ctx, path)
    if not p.is_file():
        raise ToolError(f"文件不存在: {p}")
    text = p.read_text(errors="replace")
    count = text.count(old_string)
    if count == 0:
        raise ToolError("old_string 未找到")
    if count > 1:
        raise ToolError(f"old_string 出现 {count} 次，需更长上下文保证唯一")
    new_text = text.replace(old_string, new_string, 1)
    if ctx.mode == "dry-run":
        diff = "\n".join(difflib.unified_diff(text.splitlines(), new_text.splitlines(), lineterm="", n=2))
        return f"[DRY-RUN] 拟编辑 {p}。diff 预览：\n{truncate_lines(diff, 60)}\n（apply 模式才落盘）"
    p.write_text(new_text)
    return f"已编辑 {p}"


def list_dir(ctx: ToolContext, path: str = ".") -> str:
    p = _resolve(ctx, path)
    if not p.is_dir():
        raise ToolError(f"目录不存在: {p}")
    entries = sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name))
    lines = [f"{'d' if e.is_dir() else 'f'} {e.name}" for e in entries[:200]]
    suffix = f"\n...[共 {len(entries)} 项，仅显示前 200]" if len(entries) > 200 else ""
    return f"[{p}]\n" + "\n".join(lines) + suffix
