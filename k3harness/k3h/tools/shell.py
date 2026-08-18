"""bash 工具：超时、输出截断、dry-run 拦截写型命令、可选 rtk 包装降噪。"""
from __future__ import annotations

import shutil
import subprocess

from .base import WRITEISH, ToolContext
from ..truncate import truncate_head_tail

RTK_PREFIXES = ("ls", "grep", "rg", "git", "find", "npm", "pip", "uv", "cat", "head", "tail", "pytest", "docker")


def _maybe_rtk(ctx: ToolContext, command: str) -> str:
    if not ctx.use_rtk or not shutil.which("rtk"):
        return command
    first = command.strip().split(None, 1)[0] if command.strip() else ""
    if first in RTK_PREFIXES and "|" not in command and ">" not in command:
        return f"rtk {command}"
    return command


def bash(ctx: ToolContext, command: str, timeout: int = 120) -> str:
    if ctx.mode == "dry-run" and WRITEISH.search(command):
        return f"[DRY-RUN] 写型命令已拦截，未执行：{command}\n（apply 模式才执行）"
    cmd = _maybe_rtk(ctx, command)
    try:
        r = subprocess.run(
            ["zsh", "-c", cmd], capture_output=True, text=True,
            timeout=min(timeout, 300), cwd=ctx.cwd,
        )
    except subprocess.TimeoutExpired:
        return f"[超时 {timeout}s] 命令被终止：{command}"
    out = (r.stdout or "")
    if r.stderr:
        out += ("\n[stderr]\n" + r.stderr) if out else r.stderr
    out = out.strip() or "(无输出)"
    return truncate_head_tail(out) + (f"\n[exit {r.returncode}]" if r.returncode else "")
