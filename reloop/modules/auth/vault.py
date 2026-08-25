"""加密存储: 用 Fernet 对称加密读写 Playwright storageState。

抄 agent-browser 的 AGENT_BROWSER_ENCRYPTION_KEY 加密静态存储做法:
storageState(含 cookie+localStorage, 明文即等于登录态) 落盘前必须加密,
直接对冲 Public 仓库泄漏风险。密钥只从 .env 的 BRAINX_AUTH_VAULT_KEY 注入。

生成密钥(一次性):
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
把输出填进 .env 的 BRAINX_AUTH_VAULT_KEY。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from reloop.config import settings

logger = logging.getLogger(__name__)


class VaultError(RuntimeError):
    """加密存储相关错误。"""


def _get_cipher() -> Optional[Fernet]:
    """构造 Fernet; 未配置密钥时返回 None(调用方据此决定降级)。"""
    key = (settings.auth_vault_key or "").strip()
    if not key:
        return None
    try:
        return Fernet(key.encode("utf-8"))
    except Exception as e:  # noqa: BLE001
        raise VaultError(
            f"BRAINX_AUTH_VAULT_KEY 不是合法的 Fernet 密钥: {e}. "
            "用 `python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"` 生成。"
        ) from e


def _vault_path() -> Path:
    return Path(settings.auth_vault_path)


def has_vault_key() -> bool:
    """是否已配置加密密钥。"""
    return bool((settings.auth_vault_key or "").strip())


def vault_exists() -> bool:
    """加密登录态文件是否已存在。"""
    return _vault_path().exists()


def save_state(state: dict) -> Path:
    """加密保存 Playwright storageState 字典到磁盘。

    未配置密钥 -> VaultError(拒绝明文落盘登录态, 防泄漏)。
    """
    cipher = _get_cipher()
    if cipher is None:
        raise VaultError(
            "未配置 BRAINX_AUTH_VAULT_KEY, 拒绝以明文保存登录态。"
            "请先生成并配置加密密钥。"
        )
    path = _vault_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = cipher.encrypt(json.dumps(state, ensure_ascii=False).encode("utf-8"))
    path.write_bytes(blob)
    logger.info("[vault] 登录态已加密保存: %s (%d bytes)", path, len(blob))
    return path


def load_state() -> Optional[dict]:
    """解密读取 storageState 字典; 不存在/无密钥/损坏时返回 None。"""
    cipher = _get_cipher()
    if cipher is None:
        return None
    path = _vault_path()
    if not path.exists():
        return None
    try:
        raw = cipher.decrypt(path.read_bytes())
        return json.loads(raw.decode("utf-8"))
    except InvalidToken:
        logger.warning("[vault] 解密失败(密钥不匹配或文件损坏): %s", path)
        return None
    except Exception as e:  # noqa: BLE001
        logger.warning("[vault] 读取登录态失败: %s", e)
        return None
