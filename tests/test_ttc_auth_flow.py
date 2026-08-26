"""Offline regressions for TTC callback binding and authenticated sync behavior."""

import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from reloop.api.auth import create_session_token
from reloop.config import settings
from reloop.db.engine import SessionLocal, init_db
from reloop.db.models import User
from reloop.main import app
from reloop.modules.auth.vault import VaultError, seal_user_token, unseal_user_token
from reloop.modules.sync.client import TTCClient, get_sync_progress, talent_sync_service


def test_user_token_is_not_saved_in_plaintext(monkeypatch):
    monkeypatch.setattr(settings, "auth_vault_key", Fernet.generate_key().decode("utf-8"))
    raw = "header.payload.signature-for-test"
    encrypted = seal_user_token(raw)

    assert encrypted.startswith("v1:")
    assert raw not in encrypted
    assert unseal_user_token(encrypted) == raw


def test_user_token_requires_explicit_vault_key(monkeypatch):
    monkeypatch.setattr(settings, "auth_vault_key", "")
    monkeypatch.setattr(settings, "auth_session_secret", "")
    monkeypatch.setattr(settings, "feishu_app_secret", "")

    with pytest.raises(VaultError, match="BRAINX_AUTH_VAULT_KEY"):
        seal_user_token("must-not-use-the-public-development-secret")


def test_ttc_client_uses_real_gateway_paths():
    client = TTCClient()
    seen = []

    def fake_request(url, params=None, headers=None, max_retries=3):
        seen.append((url, params, headers))
        return SimpleNamespace(status_code=200, json=lambda: {"data": {"list": []}}, text="")

    client._request_with_retry = fake_request  # type: ignore[method-assign]
    assert client.fetch_talents("space-1", "token", source="shared") == []
    assert seen[0][0].endswith("/api/private-talent/v1/all-talents/space-1/talents")
    assert client.fetch_talents(auth_token="token", source="owned") == []
    assert seen[1][0].endswith("/api/private-talent/v1/talents")


def test_official_callback_binds_user_and_starts_owned_sync(monkeypatch):
    monkeypatch.setattr(settings, "auth_vault_key", Fernet.generate_key().decode("utf-8"))
    init_db()
    user_id = "fs_ttc_flow_test"
    db = SessionLocal()
    try:
        db.query(User).filter(User.user_id == user_id).delete()
        db.add(User(user_id=user_id, display_name="测试用户"))
        db.commit()
    finally:
        db.close()

    session_token = create_session_token(user_id)
    with TestClient(app) as client, \
            patch("reloop.api.auth.validate_token", return_value={"space_id": "U-own", "display_name": "我的 TTC"}), \
            patch("reloop.modules.sync.client.talent_sync_service.sync_for_user_async", return_value="sync-owned") as sync:
        result = client.post(
            "/auth/ttc/bind",
            headers={"X-Auth-Token": session_token},
            json={"token": "a-token-that-is-long-enough-to-be-accepted"},
        )
        assert result.status_code == 200, result.text
        assert result.json()["sync_id"] == "sync-owned"
        sync.assert_called_once_with(user_id, auth_token="a-token-that-is-long-enough-to-be-accepted", source="owned")

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.user_id == user_id).one()
        assert user.ttc_space_id == "U-own"
        assert user.ttc_bound_name == "我的 TTC"
        assert user.ttc_auth_token != "a-token-that-is-long-enough-to-be-accepted"
        assert unseal_user_token(user.ttc_auth_token) == "a-token-that-is-long-enough-to-be-accepted"
    finally:
        db.close()


def test_official_callback_rejects_missing_vault_key_without_writing_or_syncing(monkeypatch):
    monkeypatch.setattr(settings, "auth_vault_key", "")
    init_db()
    user_id = "fs_ttc_vault_missing"
    db = SessionLocal()
    try:
        db.query(User).filter(User.user_id == user_id).delete()
        db.add(User(user_id=user_id, display_name="测试用户"))
        db.commit()
    finally:
        db.close()

    session_token = create_session_token(user_id)
    with TestClient(app) as client, \
            patch("reloop.api.auth.validate_token", return_value={"space_id": "U-own", "display_name": "我的 TTC"}) as validate, \
            patch("reloop.modules.sync.client.talent_sync_service.sync_for_user_async") as sync:
        result = client.post(
            "/auth/ttc/bind",
            headers={"X-Auth-Token": session_token},
            json={"token": "a-token-that-is-long-enough-to-be-accepted"},
        )

    assert result.status_code == 503
    assert "BRAINX_AUTH_VAULT_KEY" in result.json()["detail"]
    validate.assert_not_called()
    sync.assert_not_called()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.user_id == user_id).one()
        assert user.ttc_auth_token is None
        assert user.ttc_space_id is None
        assert user.ttc_bound_name is None
    finally:
        db.close()


def test_invalid_session_token_does_not_silently_become_guest(monkeypatch):
    init_db()
    monkeypatch.setattr(settings, "auth_allow_guest", True)
    with TestClient(app) as client:
        response = client.get("/auth/me", headers={"X-Auth-Token": "invalid-session-token"})

    assert response.status_code == 401
    assert "登录态" in response.json()["detail"]


def test_async_sync_ids_are_unique_and_report_synced_count():
    with patch.object(talent_sync_service, "sync_for_user", return_value=3):
        first = talent_sync_service.sync_for_user_async("fs_sync_test")
        second = talent_sync_service.sync_for_user_async("fs_sync_test")

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            first_status = get_sync_progress(first)
            second_status = get_sync_progress(second)
            if first_status.get("status") == second_status.get("status") == "done":
                break
            time.sleep(0.01)

    assert first != second
    assert first_status["synced"] == 3
    assert first_status["current"] == 3
    assert second_status["synced"] == 3
