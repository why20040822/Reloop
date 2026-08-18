"""工具上下文与注册表。schema 描述刻意写短——每个字都是每轮要付的 token。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ToolContext:
    cwd: Path
    mode: str = "apply"          # dry-run | apply
    use_rtk: bool = True


# 写型 bash 命令的保守识别（dry-run 模式下拦截）
WRITEISH = re.compile(
    r"(>>?|[^|]\|\s*tee\b|\brm\b|\bmv\b|\bcp\b|\bmkdir\b|\btouch\b|\bsed\s+-i|\bgit\s+(push|commit|add|reset|checkout)\b|--apply\b|\bwrite\b)",
    re.IGNORECASE,
)


class ToolError(Exception):
    pass
