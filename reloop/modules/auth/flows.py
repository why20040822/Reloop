"""Hashed, expiring, one-use state for browser-correlated authorization flows."""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets
from typing import Any

from sqlalchemy.orm import Session

from reloop.db.models import AuthFlowToken


FLOW_COOKIE_NAME = "reloop_auth_flow"


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def browser_binding(existing: str | None) -> tuple[str, bool]:
    """Return an existing server-issued binding, or a fresh browser secret."""
    value = (existing or "").strip()
    if len(value) >= 32:
        return value, False
    return secrets.token_urlsafe(32), True


def issue_flow_token(
    db: Session,
    *,
    provider: str,
    purpose: str,
    browser_secret: str,
    ttl_seconds: int,
    user_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> str:
    raw = secrets.token_urlsafe(32)
    db.add(
        AuthFlowToken(
            token_hash=_digest(raw),
            purpose=purpose,
            provider=provider,
            browser_binding_hash=_digest(browser_secret),
            user_id=user_id,
            payload=payload,
            expires_at=_now() + dt.timedelta(seconds=ttl_seconds),
        )
    )
    db.flush()
    return raw


def consume_flow_token(
    db: Session,
    *,
    raw_token: str | None,
    provider: str,
    purpose: str,
    browser_secret: str | None,
) -> dict[str, Any] | None:
    """Atomically consume a matching unexpired token and return its safe metadata."""
    token = (raw_token or "").strip()
    browser = (browser_secret or "").strip()
    if not token or not browser:
        return None
    now = _now()
    row = (
        db.query(AuthFlowToken)
        .filter(
            AuthFlowToken.token_hash == _digest(token),
            AuthFlowToken.provider == provider,
            AuthFlowToken.purpose == purpose,
            AuthFlowToken.browser_binding_hash == _digest(browser),
            AuthFlowToken.consumed_at.is_(None),
            AuthFlowToken.expires_at > now,
        )
        .first()
    )
    if row is None:
        return None
    updated = (
        db.query(AuthFlowToken)
        .filter(
            AuthFlowToken.id == row.id,
            AuthFlowToken.consumed_at.is_(None),
            AuthFlowToken.expires_at > now,
        )
        .update({AuthFlowToken.consumed_at: now}, synchronize_session=False)
    )
    if updated != 1:
        db.rollback()
        return None
    db.flush()
    return {"user_id": row.user_id, "payload": dict(row.payload or {})}
