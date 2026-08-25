"""登录态提供器: 从加密 storageState 解出可用 token / cookie。

供 sync/client 自动读取, 优先级:
  1. 加密 storageState 里的 localStorage token(键名见 auth_token_ls_keys)
  2. 加密 storageState 里的 cookie(拼成 Cookie 头, 兜底)
  3. 都没有 -> None(client 再回落到 .env 手填的 auth_token)

storageState 结构(Playwright 标准):
  {"cookies":[{name,value,domain,...}], "origins":[{origin, localStorage:[{name,value}]}]}
"""

from __future__ import annotations

import logging
from typing import Optional

from reloop.config import settings
from reloop.modules.auth import vault

logger = logging.getLogger(__name__)


def _token_keys() -> list[str]:
    return [k.strip().lower() for k in (settings.auth_token_ls_keys or "").split(",") if k.strip()]


def get_bearer_token() -> Optional[str]:
    """从加密登录态提取 Bearer token(localStorage 优先)。无则 None。"""
    state = vault.load_state()
    if not state:
        return None
    wanted = _token_keys()
    for origin in state.get("origins") or []:
        for item in origin.get("localStorage") or []:
            name = str(item.get("name", "")).lower()
            val = item.get("value")
            if not val:
                continue
            if name in wanted:
                token = str(val)
                # 去掉可能存在的 "Bearer " 前缀, client 会自己拼
                if token.lower().startswith("bearer "):
                    token = token[7:]
                logger.info("[auth] 从加密登录态取到 token(localStorage 键=%s)", name)
                return token
    return None


def get_cookie_header() -> Optional[str]:
    """把加密登录态里的 cookie 拼成 Cookie 头(兜底方案)。无则 None。"""
    state = vault.load_state()
    if not state:
        return None
    cookies = state.get("cookies") or []
    pairs = [f"{c.get('name')}={c.get('value')}" for c in cookies if c.get("name")]
    if not pairs:
        return None
    logger.info("[auth] 从加密登录态拼出 cookie 头(%d 项)", len(pairs))
    return "; ".join(pairs)


def resolve_auth() -> dict:
    """给 client 用的统一鉴权解析。

    返回 {"token": str|None, "cookie": str|None, "source": str}。
    source: vault_token / vault_cookie / env_token / none
    """
    token = get_bearer_token()
    if token:
        return {"token": token, "cookie": None, "source": "vault_token"}
    cookie = get_cookie_header()
    if cookie:
        return {"token": None, "cookie": cookie, "source": "vault_cookie"}
    env_token = (settings.ttc_talent_auth_token or "").strip()
    if env_token:
        return {"token": env_token, "cookie": None, "source": "env_token"}
    return {"token": None, "cookie": None, "source": "none"}
