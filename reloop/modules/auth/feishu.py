"""飞书扫码登录(自建应用 OAuth 2.0)。

流程:
  1. 前端展示登录二维码(内容 = 飞书授权页 URL, /auth/feishu/qrcode 生成 SVG)
  2. 用户飞书扫码确认 -> 飞书重定向回 redirect_uri 并携带 ?code=...
  3. 前端拿 code 调 POST /auth/feishu/login:
     后端 app_access_token -> (code 换) user_access_token -> user_info
  4. 以飞书 open_id 作为 Reloop 用户标识, 签发 HMAC 会话 token(X-Auth-Token)

说明: Reloop 自己的飞书应用拿到的 open_id 与 TTC 平台(TTC 的飞书应用)
视角的 open_id 不同, 无法直接换 TTC 数据 Token —— TTC Token 由用户在
TTC 站点登录后获取并绑定(见 /auth/ttc/bind)。

依赖: 无 SDK, httpx 直连开放接口; 未配置 App ID/Secret 时相关接口返回未启用。
"""

import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Optional

import httpx

from reloop.config import settings

logger = logging.getLogger(__name__)

_FEISHU_OPEN_BASE = "https://open.feishu.cn"
_AUTHORIZE_PATH = "/open-apis/authen/v1/index"


def create_session_token(user_id: str, ttl_hours: Optional[int] = None) -> str:
    """签发会话 token: base64url(payload).hex_hmac。无状态、无需存储。"""
    ttl = ttl_hours or settings.auth_session_ttl_hours
    payload = json.dumps(
        {"user_id": user_id, "exp": int(time.time()) + ttl * 3600},
        ensure_ascii=False, separators=(",", ":"),
    )
    b = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
    sig = hmac.new(settings.auth_secret.encode("utf-8"), b.encode("ascii"),
                   hashlib.sha256).hexdigest()
    return f"{b}.{sig}"


def verify_session_token(token: str) -> Optional[str]:
    """校验会话 token, 通过返回 user_id, 否则 None。"""
    try:
        b, sig = token.split(".", 1)
    except ValueError:
        return None
    expect = hmac.new(settings.auth_secret.encode("utf-8"), b.encode("ascii"),
                      hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expect):
        return None
    pad = "=" * (-len(b) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(b + pad))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(payload, dict):
        return None
    if int(payload.get("exp", 0)) < time.time():
        return None
    user_id = payload.get("user_id")
    return user_id if isinstance(user_id, str) and user_id else None


def decode_ttc_jwt_unverified(token: str) -> dict:
    """解码 TTC 网关 JWT 的 payload(仅读取身份声明用于绑定展示, 不做签名校验)。"""
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        p = parts[1]
        pad = "=" * (-len(p) % 4)
        data = json.loads(base64.urlsafe_b64decode(p + pad))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


class FeishuAuthService:
    """飞书开放平台 OAuth 封装(httpx 直连, 无 SDK)。"""

    def __init__(self) -> None:
        self.app_id = settings.feishu_app_id
        self.app_secret = settings.feishu_app_secret
        self._app_token: Optional[str] = None
        self._app_token_exp: float = 0.0

    @property
    def enabled(self) -> bool:
        return settings.feishu_enabled

    def login_url(self, redirect_uri: str, state: str = "reloop") -> str:
        """飞书网页授权(扫码)页 URL。redirect_uri 需在飞书开放平台应用内配置。"""
        from urllib.parse import quote

        return (
            f"{_FEISHU_OPEN_BASE}{_AUTHORIZE_PATH}"
            f"?app_id={quote(self.app_id)}"
            f"&redirect_uri={quote(redirect_uri, safe='')}"
            f"&state={quote(state)}"
        )

    def _get_app_access_token(self) -> Optional[str]:
        if not self.enabled:
            return None
        if self._app_token and time.time() < self._app_token_exp - 120:
            return self._app_token
        try:
            resp = httpx.post(
                f"{_FEISHU_OPEN_BASE}/open-apis/auth/v3/app_access_token/internal",
                json={"app_id": self.app_id, "app_secret": self.app_secret},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                logger.warning("[feishu] app_access_token error: %s", data.get("msg"))
                return None
            self._app_token = data.get("app_access_token")
            self._app_token_exp = time.time() + int(data.get("expire", 1800))
            return self._app_token
        except Exception as e:  # noqa: BLE001
            logger.warning("[feishu] app_access_token failed: %s", e)
            return None

    def login_by_code(self, code: str) -> Optional[dict]:
        """授权码换用户信息: {open_id, union_id, name, ...}。失败返回 None。"""
        app_token = self._get_app_access_token()
        if not app_token:
            return None
        try:
            # v1 接口: code -> user_access_token
            # (注: v2 路径 /authen/v2/oidc/access_token 对本应用返回 404 page
            #  not found, 2026-08-20 实测; v1 返回 {code, message, data:{access_token}})
            resp = httpx.post(
                f"{_FEISHU_OPEN_BASE}/open-apis/authen/v1/oidc/access_token",
                headers={"Authorization": f"Bearer {app_token}"},
                json={"grant_type": "authorization_code", "code": code},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                logger.warning("[feishu] access_token error: %s %s",
                               data.get("code"), data.get("message"))
                return None
            user_access_token = (data.get("data") or {}).get("access_token")
            if not user_access_token:
                return None
            # user_access_token -> 用户信息
            resp = httpx.get(
                f"{_FEISHU_OPEN_BASE}/open-apis/authen/v1/user_info",
                headers={"Authorization": f"Bearer {user_access_token}"},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                logger.warning("[feishu] user_info error: %s %s",
                               data.get("code"), data.get("message"))
                return None
            info = data.get("data") or {}
            if not info.get("open_id"):
                return None
            return info
        except Exception as e:  # noqa: BLE001
            logger.warning("[feishu] login_by_code failed: %s", e)
            return None


feishu_auth = FeishuAuthService()
