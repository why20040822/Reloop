"""配置加载：优先环境变量，兜底 ~/.claude/settings.json 的 env 段。密钥一律不落代码。"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"


@dataclass
class Config:
    base_url: str          # e.g. https://api.kimi.com/coding/
    api_key: str
    model: str
    timeout_ms: int = 300_000
    max_turns: int = 30
    compact_threshold: int = 120_000   # 估算 tokens，超过则压缩历史

    @property
    def timeout_s(self) -> float:
        return self.timeout_ms / 1000


def _from_claude_settings() -> dict:
    if CLAUDE_SETTINGS.exists():
        try:
            return json.loads(CLAUDE_SETTINGS.read_text()).get("env", {})
        except Exception:
            return {}
    return {}


def load_config() -> Config:
    s = _from_claude_settings()
    env = os.environ

    def pick(name: str, default: str = "") -> str:
        return env.get(name) or s.get(name) or default

    return Config(
        base_url=pick("ANTHROPIC_BASE_URL", "https://api.kimi.com/coding/"),
        api_key=pick("ANTHROPIC_AUTH_TOKEN") or pick("ANTHROPIC_API_KEY"),
        model=pick("ANTHROPIC_MODEL", "k3[1m]"),
        timeout_ms=int(pick("API_TIMEOUT_MS", "300000")),
    )
