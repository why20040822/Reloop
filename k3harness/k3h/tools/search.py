"""搜索工具：grep（ripgrep 优先）/ glob。"""
from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path

from .base import ToolContext, ToolError
from .files import _resolve


def grep(ctx: ToolContext, pattern: str, path: str = ".", max_results: int = 100) -> str:
    p = _resolve(ctx, path)
    cmd = ["rg", "--line-number", "--no-heading", "--max-count", str(max_results), pattern, str(p)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        r = subprocess.run(
            ["grep", "-rn", "-E", pattern, str(p)], capture_output=True, text=True, timeout=60
        )
    out = r.stdout.strip()
    if not out:
        return "无匹配"
    lines = out.splitlines()
    if len(lines) > max_results:
        lines = lines[:max_results]
        return "\n".join(lines) + f"\n...[仅显示前 {max_results} 条]"
    return "\n".join(lines)


def glob(ctx: ToolContext, pattern: str, path: str = ".") -> str:
    p = _resolve(ctx, path)
    if not p.is_dir():
        raise ToolError(f"目录不存在: {p}")
    matches = sorted(str(m.relative_to(p)) for m in p.rglob("*") if fnmatch.fnmatch(m.name, pattern) or fnmatch.fnmatch(str(m.relative_to(p)), pattern))
    if not matches:
        return "无匹配"
    if len(matches) > 200:
        return "\n".join(matches[:200]) + f"\n...[共 {len(matches)} 项，仅显示前 200]"
    return "\n".join(matches)
