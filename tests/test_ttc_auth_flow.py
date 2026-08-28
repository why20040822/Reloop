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
from reloop.modules.sync.client import TTCAuthRequired, TTCClient, get_sync_progress, talent_sync_service


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


def test_legacy_plaintext_user_token_requires_reconnect_and_cannot_sync():
    init_db()
    user_id = "fs_legacy_plaintext_ttc_token"
    plaintext = "legacy-plaintext-token-that-must-not-be-used"
    db = SessionLocal()
    try:
        db.query(User).filter(User.user_id == user_id).delete()
        db.add(User(user_id=user_id, display_name="旧凭据用户", ttc_auth_token=plaintext))
        db.commit()
    finally:
        db.close()

    with pytest.raises(VaultError, match="重新"):
        unseal_user_token(plaintext)

    session_token = create_session_token(user_id)
    with TestClient(app) as client, patch(
        "reloop.api.sync.talent_sync_service.sync_for_user_async",
    ) as sync:
        me_response = client.get("/auth/me", headers={"X-Auth-Token": session_token})
        sync_response = client.post("/sync/ttc", headers={"X-Auth-Token": session_token})

    assert me_response.status_code == 200, me_response.text
    assert me_response.json()["ttc_connected"] is False
    assert sync_response.status_code == 409, sync_response.text
    assert "重新" in sync_response.json()["detail"]
    sync.assert_not_called()


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


@pytest.mark.parametrize(
    ("shared_token", "legacy_token"),
    [("shared-service-token", ""), ("", "legacy-token-that-must-not-be-used")],
)
def test_owned_ttc_client_requires_explicit_user_token(monkeypatch, shared_token, legacy_token):
    monkeypatch.setattr(settings, "ttc_shared_auth_token", shared_token)
    monkeypatch.setattr(settings, "ttc_talent_auth_token", legacy_token)
    client = TTCClient()

    with patch.object(client, "_request_with_retry") as request:
        with pytest.raises(TTCAuthRequired):
            client.fetch_talents(source="owned")

    request.assert_not_called()


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


@pytest.mark.parametrize("submitted_token", ["a-token-that-is-long-enough-to-be-accepted", ""])
def test_official_callback_rejects_missing_vault_key_without_writing_or_syncing(monkeypatch, submitted_token):
    monkeypatch.setattr(settings, "auth_vault_key", "")
    init_db()
    user_id = f"fs_ttc_vault_missing_{'value' if submitted_token else 'blank'}"
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
            json={"token": submitted_token},
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


def test_async_sync_idempotent_for_same_owner_and_reports_synced_count():
    """R6(2026-08-28) 新语义: 同 owner 已有 running 同步时, 重复触发必须复用同一 sync_id。

    时序确定性修复(2026-08-28 夜): 原 mock 瞬间返回, 首个同步可能在第二次触发前
    就写完 done, 复用断言变成赌毫秒窗口(实测连续失败)。改为用 Event 把首个同步
    阻塞到第二次触发之后 —— 断言本身一字未动。
    """
    import threading

    release = threading.Event()
    started = threading.Event()

    def slow_sync(owner_user_id, **kwargs):
        started.set()
        release.wait(timeout=5)
        return 3

    with patch.object(talent_sync_service, "sync_for_user", side_effect=slow_sync):
        first = talent_sync_service.sync_for_user_async("fs_sync_test")
        assert started.wait(timeout=2), "首个同步应已开始并处于 running"
        second = talent_sync_service.sync_for_user_async("fs_sync_test")
        release.set()

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            first_status = get_sync_progress(first)
            if first_status.get("status") == "done":
                break
            time.sleep(0.01)

    assert second == first, "同 owner running 中重复触发必须复用 sync_id(幂等)"
    assert first_status["synced"] == 3
    assert first_status["current"] == 3


def test_async_sync_new_id_after_previous_done():
    """R6(2026-08-28): 上一次同步完成后, 新触发应产生新的 sync_id。

    注意时序: 内存态 done 与 sync_runs 终态回写之间有毫秒级窗口,
    该窗口内触发会被 L2 锁幂等复用——所以轮询直到拿到新 id 为止。
    """
    with patch.object(talent_sync_service, "sync_for_user", return_value=1):
        first = talent_sync_service.sync_for_user_async("fs_sync_done_test")
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if get_sync_progress(first).get("status") == "done":
                break
            time.sleep(0.01)

        second = first
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and second == first:
            second = talent_sync_service.sync_for_user_async("fs_sync_done_test")
            if second == first:
                time.sleep(0.05)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if get_sync_progress(second).get("status") == "done":
                break
            time.sleep(0.01)

    assert first != second, "上次完成后应允许新的同步"
    assert get_sync_progress(second).get("status") == "done"
