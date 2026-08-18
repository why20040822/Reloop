"""Local account authentication for the ot browser extension.

Users register with a display name, email and password. New accounts are
pending until an administrator enables them. Passwords and opaque session
tokens are stored only as one-way hashes.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any


ACCESS_TTL = timedelta(hours=1)
REFRESH_TTL = timedelta(days=30)
LOGIN_RATE_WINDOW_SECONDS = 10 * 60
LOGIN_RATE_MAX_FAILURES = 5
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
DEFAULT_ADMIN_EMAIL = "jiands233@gmail.com"


class AuthError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 401, code: str = "auth_error") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass(frozen=True)
class AuthenticatedActor:
    user_id: int
    session_id: str
    device_id: str
    email: str
    name: str
    avatar_url: str
    approval_status: str


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise AuthError(f"服务器尚未配置 {name}", status_code=503, code="auth_not_configured")
    return value


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _opaque_token() -> str:
    return secrets.token_urlsafe(48)


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def normalize_email(value: str) -> str:
    email = str(value or "").strip().lower()
    if len(email) > 320 or not EMAIL_PATTERN.fullmatch(email):
        raise AuthError("请输入有效的邮箱地址", status_code=422, code="invalid_email")
    return email


def validate_password(value: str) -> str:
    password = str(value or "")
    if len(password) < 8:
        raise AuthError("密码至少需要 8 位", status_code=422, code="weak_password")
    if len(password) > 128:
        raise AuthError("密码不能超过 128 位", status_code=422, code="weak_password")
    return password


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    password = validate_password(password)
    salt = salt or secrets.token_bytes(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"), salt=salt,
        n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=SCRYPT_DKLEN,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64encode(salt)}${_b64encode(derived)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = str(encoded or "").split("$", 5)
        if algorithm != "scrypt":
            return False
        derived = hashlib.scrypt(
            str(password or "").encode("utf-8"), salt=_b64decode(salt),
            n=int(n), r=int(r), p=int(p), dklen=len(_b64decode(expected)),
        )
        return hmac.compare_digest(derived, _b64decode(expected))
    except (TypeError, ValueError):
        return False


_DUMMY_PASSWORD_HASH = hash_password("dummy-password-never-valid")


def _status(value: str) -> str:
    mapping = {
        "待审批": "pending", "pending": "pending",
        "已启用": "enabled", "enabled": "enabled",
        "已停用": "disabled", "disabled": "disabled",
    }
    return mapping.get(str(value or "").strip(), "pending")


def _public_user(row: dict[str, Any]) -> dict[str, Any]:
    def pick(name: str, default: Any = "") -> Any:
        return row.get(f"user_{name}", row.get(name, default))

    return {
        "id": int(pick("id", 0)),
        "email": str(pick("email")),
        "name": str(pick("name")),
        "avatar_url": str(pick("avatar_url")),
        "approval_status": _status(str(pick("approval_status", "pending"))),
    }


def verify_admin_credentials(email: str, password: str) -> bool:
    try:
        expected_email = normalize_email(
            os.getenv("OT_PLUGIN_ADMIN_EMAIL", "").strip() or DEFAULT_ADMIN_EMAIL
        )
        supplied_email = normalize_email(email)
        password_hash = _required("OT_PLUGIN_ADMIN_PASSWORD_HASH")
    except AuthError:
        return False
    email_ok = hmac.compare_digest(supplied_email.encode("utf-8"), expected_email.encode("utf-8"))
    password_ok = verify_password(password, password_hash)
    return email_ok and password_ok


class PluginAuthService:
    def __init__(self, repository: Any | None = None) -> None:
        if repository is None:
            from cloud_sync.client import CloudSyncClient
            repository = CloudSyncClient()
        self.repository = repository
        self._failed_logins: dict[str, list[float]] = {}
        self._rate_lock = threading.Lock()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    @staticmethod
    def _validate_device_id(device_id: str) -> str:
        device = str(device_id or "").strip()
        if len(device) < 8:
            raise AuthError("缺少设备标识", status_code=422, code="device_required")
        return device[:255]

    @staticmethod
    def _validate_name(name: str) -> str:
        cleaned = " ".join(str(name or "").strip().split())
        if not cleaned or len(cleaned) > 64:
            raise AuthError("姓名需要填写 1 到 64 个字符", status_code=422, code="invalid_name")
        return cleaned

    def _recent_failures(self, key: str, now: float) -> list[float]:
        cutoff = now - LOGIN_RATE_WINDOW_SECONDS
        return [stamp for stamp in self._failed_logins.get(key, []) if stamp > cutoff]

    def _check_rate_limit(self, key: str) -> None:
        now = time.monotonic()
        with self._rate_lock:
            failures = self._recent_failures(key, now)
            self._failed_logins[key] = failures
            if len(failures) >= LOGIN_RATE_MAX_FAILURES:
                raise AuthError("登录尝试过多，请稍后再试", status_code=429, code="login_rate_limited")

    def _record_failed_login(self, key: str) -> None:
        now = time.monotonic()
        with self._rate_lock:
            failures = self._recent_failures(key, now)
            failures.append(now)
            self._failed_logins[key] = failures

    def _clear_failed_logins(self, key: str) -> None:
        with self._rate_lock:
            self._failed_logins.pop(key, None)

    def _issue_session(self, user: dict[str, Any], device_id: str) -> dict[str, Any]:
        now = self._now()
        access_token = _opaque_token()
        refresh_token = _opaque_token()
        session = {
            "id": str(uuid.uuid4()),
            "user_id": int(user["id"]),
            "device_id": self._validate_device_id(device_id),
            "access_token_hash": _token_hash(access_token),
            "refresh_token_hash": _token_hash(refresh_token),
            "access_expires_at": now + ACCESS_TTL,
            "refresh_expires_at": now + REFRESH_TTL,
            "revoked": False,
        }
        self.repository.create_plugin_session(session)
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "access_expires_at": session["access_expires_at"].isoformat(),
            "refresh_expires_at": session["refresh_expires_at"].isoformat(),
            "user": _public_user(user),
        }

    def register(self, *, name: str, email: str, password: str, device_id: str) -> dict[str, Any]:
        clean_name = self._validate_name(name)
        clean_email = normalize_email(email)
        clean_device = self._validate_device_id(device_id)
        password_hash = hash_password(password)
        user = self.repository.create_local_plugin_user(
            name=clean_name, email=clean_email, password_hash=password_hash,
        )
        if not user:
            raise AuthError("该邮箱已经注册，请直接登录", status_code=409, code="account_exists")
        return self._issue_session(user, clean_device)

    def login(self, *, email: str, password: str, device_id: str) -> dict[str, Any]:
        clean_email = normalize_email(email)
        clean_device = self._validate_device_id(device_id)
        self._check_rate_limit(clean_email)
        user = self.repository.get_plugin_user_by_email(clean_email)
        password_hash = str((user or {}).get("password_hash") or _DUMMY_PASSWORD_HASH)
        if not user or not verify_password(password, password_hash):
            self._record_failed_login(clean_email)
            raise AuthError("邮箱或密码错误", code="invalid_credentials")
        self._clear_failed_logins(clean_email)
        self.repository.touch_plugin_user_login(int(user["id"]))
        return self._issue_session(user, clean_device)

    def refresh_session(self, refresh_token: str) -> dict[str, Any]:
        now = self._now()
        access = _opaque_token()
        refresh = _opaque_token()
        updates = {
            "access_token_hash": _token_hash(access),
            "refresh_token_hash": _token_hash(refresh),
            "access_expires_at": now + ACCESS_TTL,
            "refresh_expires_at": now + REFRESH_TTL,
        }
        row = self.repository.rotate_plugin_session(_token_hash(refresh_token), updates, now)
        if not row:
            raise AuthError("刷新令牌无效或已过期", code="invalid_refresh_token")
        return {
            "access_token": access,
            "refresh_token": refresh,
            "access_expires_at": updates["access_expires_at"].isoformat(),
            "refresh_expires_at": updates["refresh_expires_at"].isoformat(),
            "user": _public_user(row),
        }

    def authenticate(self, access_token: str) -> AuthenticatedActor:
        if not access_token:
            raise AuthError("请先登录插件账号", code="login_required")
        row = self.repository.get_session_by_access_hash(_token_hash(access_token), self._now())
        if not row:
            raise AuthError("登录会话无效或已过期", code="session_expired")
        user = _public_user(row)
        return AuthenticatedActor(
            user_id=user["id"],
            session_id=str(row["id"]),
            device_id=str(row["device_id"]),
            email=user["email"],
            name=user["name"],
            avatar_url=user["avatar_url"],
            approval_status=user["approval_status"],
        )

    def logout(self, actor: AuthenticatedActor) -> None:
        self.repository.revoke_plugin_session(actor.session_id)
