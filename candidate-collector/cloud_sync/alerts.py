"""同步错误告警（R7：错误不得静默吞）。

任何 sync 出现 errors>0 或写入异常时调用 ``alert_sync_error``：
1. 永远打 ERROR 日志；
2. 配置了 TTC_FEISHU_NOTIFY_ENABLED=true + TTC_FEISHU_CHAT_ID 时，
   通过 lark-cli 发飞书群通知（与 ttc_daemon 同一通道）。

告警本身绝不抛出——业务异常已经够多了，告警不能再添乱。
"""
from __future__ import annotations

import logging
import os
import subprocess

logger = logging.getLogger(__name__)

_MAX_DETAIL = 800  # 飞书消息截断，避免刷屏


def _notify_enabled() -> bool:
    return (
        os.getenv("TTC_FEISHU_NOTIFY_ENABLED", "").lower() == "true"
        and bool(os.getenv("TTC_FEISHU_CHAT_ID"))
    )


def send_feishu_text(text: str) -> bool:
    """Send a text message to the ops chat via lark-cli. Never raises."""
    if not _notify_enabled():
        return False
    cmd = [
        "lark-cli", "im", "+messages-send",
        "--as", "bot",
        "--chat-id", os.environ["TTC_FEISHU_CHAT_ID"],
        "--msg-type", "text",
        "--text", text,
        "--json",
    ]
    try:
        env = os.environ.copy()
        env["LARKSUITE_CLI_NO_UPDATE_NOTIFIER"] = "1"
        env["LARKSUITE_CLI_NO_SKILLS_NOTIFIER"] = "1"
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)
        if result.returncode != 0:
            logger.error("飞书告警发送失败: %s", result.stderr or result.stdout)
            return False
        return True
    except Exception as exc:  # noqa: BLE001 - 告警通道自身不得抛出
        logger.error("飞书告警发送异常: %s", exc)
        return False


def alert_sync_error(title: str, detail: str) -> None:
    """Log an ERROR and notify the ops chat. Never raises."""
    logger.error("%s: %s", title, detail)
    send_feishu_text(f"🚨 {title}\n{detail[:_MAX_DETAIL]}")
