"""TTC official callback URL construction and token validation."""

from typing import Any
from urllib.parse import urlencode, urlparse

import httpx

from reloop.config import settings


class TTCAuthError(RuntimeError):
    """TTC official authorization failed or the login token is invalid."""


def build_login_url(redirect_uri: str) -> str:
    parsed = urlparse(redirect_uri)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise TTCAuthError("回调地址必须是可访问的 http(s) 工作台地址")
    return f"{settings.ttc_authorize_url.rstrip('/')}?{urlencode({'callback_url': redirect_uri, 'auto': '1'})}"


def _unwrap(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def _first_text(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def validate_token(token: str) -> dict[str, str]:
    if not token or len(token.strip()) < 16:
        raise TTCAuthError("缺少有效的人才库登录态")
    try:
        response = httpx.get(f"{settings.ttc_talent_api_base_url.rstrip('/')}/api/private-talent/v1/user/me", headers={"Accept": "application/json", "Authorization": f"Bearer {token.strip()}"}, timeout=20)
    except httpx.HTTPError as exc:
        raise TTCAuthError("无法连接 TTC 人才库服务，请稍后重试") from exc
    if response.status_code in {401, 403}:
        raise TTCAuthError("飞书登录态已失效，请重新登录")
    if response.status_code != 200:
        raise TTCAuthError("TTC 人才库暂时无法验证登录态")
    try:
        profile = _unwrap(response.json())
    except ValueError as exc:
        raise TTCAuthError("TTC 人才库返回了无法识别的登录信息") from exc
    return {"space_id": _first_text(profile, "user_unique_id", "user_id", "id", "open_id"), "display_name": _first_text(profile, "user_name", "nick_name", "name", "display_name")}
