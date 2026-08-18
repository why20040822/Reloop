"""工具注册表：anthropic schema（描述写短）+ dispatch。"""
from __future__ import annotations

from typing import Callable

from . import files, search, shell
from .base import ToolContext

TOOLS: list[dict] = [
    {
        "name": "read_file",
        "description": "读文件片段（带行号）。默认400行，大文件用 offset/limit 分段读，禁止一次读全文。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "offset": {"type": "integer", "default": 0},
                "limit": {"type": "integer", "default": 400},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "写整个文件（新建或覆盖）。dry-run 模式只预览 diff。",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": "精确替换：old_string 必须在文件中唯一出现。dry-run 模式只预览 diff。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_string": {"type": "string"},
                "new_string": {"type": "string"},
            },
            "required": ["path", "old_string", "new_string"],
        },
    },
    {
        "name": "list_dir",
        "description": "列目录内容（一层）。",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "default": "."}},
        },
    },
    {
        "name": "grep",
        "description": "正则搜索文件内容，返回 文件:行号:内容，上限100条。定位优先用它，而不是读全文。",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string", "default": "."},
                "max_results": {"type": "integer", "default": 100},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "glob",
        "description": "按文件名模式找文件（如 *.py）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string", "default": "."},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "bash",
        "description": "执行 shell 命令（zsh）。输出自动截断。dry-run 模式拦截写型命令。超时默认120s。",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "integer", "default": 120},
            },
            "required": ["command"],
        },
    },
]

_DISPATCH: dict[str, Callable] = {
    "read_file": files.read_file,
    "write_file": files.write_file,
    "edit_file": files.edit_file,
    "list_dir": files.list_dir,
    "grep": search.grep,
    "glob": search.glob,
    "bash": shell.bash,
}


def dispatch(ctx: ToolContext, name: str, arguments: dict) -> tuple[str, bool]:
    """返回 (输出文本, 是否错误)。"""
    fn = _DISPATCH.get(name)
    if not fn:
        return f"未知工具: {name}", True
    try:
        return fn(ctx, **arguments), False
    except TypeError as e:
        return f"参数错误: {e}", True
    except Exception as e:
        return f"{type(e).__name__}: {e}", True
