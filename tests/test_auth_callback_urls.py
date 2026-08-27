"""Server-owned OAuth callbacks must be correlated, expiring, and secret-safe."""

import asyncio
import datetime as dt
import hashlib
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from reloop.config import settings
from reloop.db.engine import SessionLocal, engine, init_db
from reloop.db.models import User
from reloop.main import app
from reloop.modules.auth.feishu import create_session_token, feishu_auth
from reloop.modules.auth.redaction import RedactAuthCallbackMiddleware
from reloop.modules.auth.vault import unseal_user_token


def _state_from_feishu_url(url: str) -> str:
    return parse_qs(urlparse(url).query)["state"][0]


def _ttc_callback_from_login_url(url: str) -> tuple[str, str]:
    query = parse_qs(urlparse(url).query)
    return query["callback_url"][0], query["state"][0]


def _fragment_query(location: str) -> dict[str, list[str]]:
    fragment = urlparse(location).fragment
    return parse_qs(fragment.split("?", 1)[1] if "?" in fragment else "")


def _prepare_provider_settings(monkeypatch):
    monkeypatch.setattr(settings, "auth_public_base_url", "https://reloop.example.test")
    monkeypatch.setattr(settings, "feishu_app_id", "cli_test")
    monkeypatch.setattr(settings, "feishu_app_secret", "feishu-secret")
    monkeypatch.setattr(feishu_auth, "app_id", "cli_test")
    monkeypatch.setattr(feishu_auth, "app_secret", "feishu-secret")
    init_db()
    db = SessionLocal()
    try:
        db.execute(text("DELETE FROM auth_flow_tokens"))
        db.query(User).delete()
        db.commit()
    finally:
        db.close()


def _add_user(user_id: str) -> str:
    db = SessionLocal()
    try:
        db.add(User(user_id=user_id, display_name=user_id))
        db.commit()
    finally:
        db.close()
    return create_session_token(user_id)


def test_init_db_creates_server_side_auth_flow_storage_idempotently():
    init_db()
    init_db()

    assert "auth_flow_tokens" in inspect(engine).get_table_names()
    columns = {column["name"] for column in inspect(engine).get_columns("auth_flow_tokens")}
    assert {
        "token_hash", "purpose", "provider", "browser_binding_hash", "user_id",
        "payload", "expires_at", "consumed_at",
    }.issubset(columns)


def test_feishu_login_issues_random_server_side_state_bound_to_browser(monkeypatch):
    _prepare_provider_settings(monkeypatch)

    with TestClient(app, base_url="https://reloop.example.test") as first:
        first_response = first.get("/auth/feishu/url")
    with TestClient(app, base_url="https://reloop.example.test") as second:
        second_response = second.get("/auth/feishu/url")

    first_state = _state_from_feishu_url(first_response.json()["url"])
    second_state = _state_from_feishu_url(second_response.json()["url"])
    assert first_response.status_code == second_response.status_code == 200
    assert len(first_state) >= 32
    assert first_state != second_state
    assert "reloop_auth_flow=" in first_response.headers["set-cookie"]

    db = SessionLocal()
    try:
        rows = db.execute(text(
            "SELECT token_hash, browser_binding_hash FROM auth_flow_tokens "
            "WHERE purpose='oauth_state'"
        )).all()
    finally:
        db.close()
    assert hashlib.sha256(first_state.encode()).hexdigest() in {row.token_hash for row in rows}
    assert all(first_state not in row.token_hash for row in rows)
    assert all(len(row.browser_binding_hash) == 64 for row in rows)


def test_feishu_callback_exchanges_code_server_side_and_handle_is_single_use(monkeypatch):
    _prepare_provider_settings(monkeypatch)

    with TestClient(app, base_url="https://reloop.example.test") as client, patch.object(
        feishu_auth,
        "login_by_code",
        return_value={"open_id": "open-user", "name": "Feishu User"},
    ) as exchange:
        state = _state_from_feishu_url(client.get("/auth/feishu/url").json()["url"])
        callback = client.get(
            f"/auth/feishu/callback?code=provider-code&state={state}", follow_redirects=False
        )
        query = _fragment_query(callback.headers["location"])
        handle = query["handle"][0]
        login = client.post("/auth/feishu/login", json={"handle": handle})
        replay = client.post("/auth/feishu/login", json={"handle": handle})

    assert callback.status_code == 302
    assert query["status"] == ["success"]
    assert "provider-code" not in callback.headers["location"]
    assert "provider-code" not in callback.text
    assert "state=" not in callback.headers["location"]
    assert login.status_code == 200
    assert login.json()["user"]["user_id"] == "fs_open-user"
    assert replay.status_code == 401
    exchange.assert_called_once_with("provider-code")


def test_feishu_state_mismatch_is_rejected_before_code_exchange(monkeypatch):
    _prepare_provider_settings(monkeypatch)

    with TestClient(app, base_url="https://reloop.example.test") as client, patch.object(
        feishu_auth, "login_by_code"
    ) as exchange:
        client.get("/auth/feishu/url")
        callback = client.get(
            "/auth/feishu/callback?code=provider-code&state=wrong-state",
            follow_redirects=False,
        )

    assert _fragment_query(callback.headers["location"]) == {
        "status": ["error"], "error": ["invalid_state"],
    }
    assert "provider-code" not in callback.headers["location"]
    exchange.assert_not_called()


def test_feishu_callback_rejects_missing_state_before_code_exchange(monkeypatch):
    _prepare_provider_settings(monkeypatch)

    with TestClient(app, base_url="https://reloop.example.test") as client, patch.object(
        feishu_auth, "login_by_code"
    ) as exchange:
        callback = client.get(
            "/auth/feishu/callback?code=provider-code",
            follow_redirects=False,
        )

    assert _fragment_query(callback.headers["location"]) == {
        "status": ["error"], "error": ["invalid_state"],
    }
    assert "provider-code" not in callback.headers["location"]
    exchange.assert_not_called()


def test_feishu_state_is_expiring_and_single_use(monkeypatch):
    _prepare_provider_settings(monkeypatch)

    with TestClient(app, base_url="https://reloop.example.test") as client, patch.object(
        feishu_auth,
        "login_by_code",
        return_value={"open_id": "open-user", "name": "Feishu User"},
    ) as exchange:
        state = _state_from_feishu_url(client.get("/auth/feishu/url").json()["url"])
        first = client.get(f"/auth/feishu/callback?code=first-code&state={state}", follow_redirects=False)
        replay = client.get(f"/auth/feishu/callback?code=second-code&state={state}", follow_redirects=False)

        expired_state = _state_from_feishu_url(client.get("/auth/feishu/url").json()["url"])
        db = SessionLocal()
        try:
            db.execute(text(
                "UPDATE auth_flow_tokens SET expires_at=:expired WHERE token_hash=:token_hash"
            ), {
                "expired": dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(seconds=1),
                "token_hash": hashlib.sha256(expired_state.encode()).hexdigest(),
            })
            db.commit()
        finally:
            db.close()
        expired = client.get(
            f"/auth/feishu/callback?code=expired-code&state={expired_state}", follow_redirects=False
        )

    assert _fragment_query(first.headers["location"])["status"] == ["success"]
    assert _fragment_query(replay.headers["location"])["error"] == ["invalid_state"]
    assert _fragment_query(expired.headers["location"])["error"] == ["invalid_state"]
    exchange.assert_called_once_with("first-code")


def test_feishu_session_handle_expires_before_exchange(monkeypatch):
    _prepare_provider_settings(monkeypatch)

    with TestClient(app, base_url="https://reloop.example.test") as client, patch.object(
        feishu_auth,
        "login_by_code",
        return_value={"open_id": "handle-expiry-user", "name": "Feishu User"},
    ):
        state = _state_from_feishu_url(client.get("/auth/feishu/url").json()["url"])
        callback = client.get(
            f"/auth/feishu/callback?code=provider-code&state={state}",
            follow_redirects=False,
        )
        handle = _fragment_query(callback.headers["location"])["handle"][0]
        db = SessionLocal()
        try:
            db.execute(
                text("UPDATE auth_flow_tokens SET expires_at=:expired WHERE token_hash=:token_hash"),
                {
                    "expired": dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
                    - dt.timedelta(seconds=1),
                    "token_hash": hashlib.sha256(handle.encode()).hexdigest(),
                },
            )
            db.commit()
        finally:
            db.close()
        exchange = client.post("/auth/feishu/login", json={"handle": handle})

    assert exchange.status_code == 401
    assert "无效或已过期" in exchange.json()["detail"]


def test_feishu_state_is_bound_to_the_initiating_browser(monkeypatch):
    _prepare_provider_settings(monkeypatch)

    with TestClient(app, base_url="https://reloop.example.test") as initiator:
        state = _state_from_feishu_url(initiator.get("/auth/feishu/url").json()["url"])
    with TestClient(app, base_url="https://reloop.example.test") as other, patch.object(
        feishu_auth, "login_by_code"
    ) as exchange:
        callback = other.get(
            f"/auth/feishu/callback?code=stolen-code&state={state}", follow_redirects=False
        )

    assert _fragment_query(callback.headers["location"])["error"] == ["invalid_state"]
    exchange.assert_not_called()


def test_ttc_login_uses_user_bound_state_and_backend_callback_never_redirects_token(monkeypatch):
    _prepare_provider_settings(monkeypatch)
    monkeypatch.setattr(settings, "auth_vault_key", Fernet.generate_key().decode())
    token = _add_user("fs_ttc_owner")
    provider_token = "ttc-provider-token-that-must-never-reach-the-spa"

    with TestClient(app, base_url="https://reloop.example.test") as client, patch(
        "reloop.api.auth.validate_token",
        return_value={"space_id": "U-own", "display_name": "Owned TTC"},
    ) as validate, patch(
        "reloop.modules.sync.client.talent_sync_service.sync_for_user_async",
        return_value="sync-owned",
    ) as sync:
        login_url = client.get(
            "/auth/ttc/login-url", headers={"X-Auth-Token": token}
        ).json()["url"]
        callback_url, state = _ttc_callback_from_login_url(login_url)
        callback = client.get(
            f"/auth/ttc/callback?state={state}&token={provider_token}", follow_redirects=False
        )
        replay = client.get(
            f"/auth/ttc/callback?state={state}&token={provider_token}", follow_redirects=False
        )

    assert callback_url == "https://reloop.example.test/auth/ttc/callback"
    assert _fragment_query(callback.headers["location"]) == {"status": ["success"]}
    assert provider_token not in callback.headers["location"]
    assert provider_token not in callback.text
    assert _fragment_query(replay.headers["location"])["error"] == ["invalid_state"]
    validate.assert_called_once_with(provider_token)
    sync.assert_called_once_with("fs_ttc_owner", auth_token=provider_token, source="owned")

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.user_id == "fs_ttc_owner").one()
        flow_payloads = [row[0] for row in db.execute(text("SELECT payload FROM auth_flow_tokens"))]
        assert user.ttc_auth_token != provider_token
        assert unseal_user_token(user.ttc_auth_token) == provider_token
        assert provider_token not in repr(flow_payloads)
    finally:
        db.close()


def test_ttc_callback_rejects_missing_state_before_token_validation(monkeypatch):
    _prepare_provider_settings(monkeypatch)
    provider_token = "ttc-provider-token-that-must-not-reach-the-spa"

    with TestClient(app, base_url="https://reloop.example.test") as client, patch(
        "reloop.api.auth.validate_token"
    ) as validate:
        callback = client.get(
            f"/auth/ttc/callback?token={provider_token}",
            follow_redirects=False,
        )

    assert _fragment_query(callback.headers["location"]) == {
        "status": ["error"], "error": ["invalid_state"],
    }
    assert provider_token not in callback.headers["location"]
    assert provider_token not in callback.text
    validate.assert_not_called()


def test_ttc_callback_rejects_browser_mismatch_expiration_and_missing_token(monkeypatch):
    _prepare_provider_settings(monkeypatch)
    monkeypatch.setattr(settings, "auth_vault_key", Fernet.generate_key().decode())
    token = _add_user("fs_ttc_edge_owner")

    with TestClient(app, base_url="https://reloop.example.test") as initiator:
        _, mismatched_state = _ttc_callback_from_login_url(
            initiator.get("/auth/ttc/login-url", headers={"X-Auth-Token": token}).json()["url"]
        )
    with TestClient(app, base_url="https://reloop.example.test") as other, patch(
        "reloop.api.auth.validate_token"
    ) as validate:
        mismatch = other.get(
            f"/auth/ttc/callback?state={mismatched_state}&token=valid-looking-token",
            follow_redirects=False,
        )
    assert _fragment_query(mismatch.headers["location"])["error"] == ["invalid_state"]
    validate.assert_not_called()

    with TestClient(app, base_url="https://reloop.example.test") as client, patch(
        "reloop.api.auth.validate_token"
    ) as validate:
        _, expired_state = _ttc_callback_from_login_url(
            client.get("/auth/ttc/login-url", headers={"X-Auth-Token": token}).json()["url"]
        )
        db = SessionLocal()
        try:
            db.execute(text(
                "UPDATE auth_flow_tokens SET expires_at=:expired WHERE token_hash=:token_hash"
            ), {
                "expired": dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(seconds=1),
                "token_hash": hashlib.sha256(expired_state.encode()).hexdigest(),
            })
            db.commit()
        finally:
            db.close()
        expired = client.get(
            f"/auth/ttc/callback?state={expired_state}&token=valid-looking-token",
            follow_redirects=False,
        )

        _, missing_state = _ttc_callback_from_login_url(
            client.get("/auth/ttc/login-url", headers={"X-Auth-Token": token}).json()["url"]
        )
        missing = client.get(f"/auth/ttc/callback?state={missing_state}", follow_redirects=False)
        missing_replay = client.get(
            f"/auth/ttc/callback?state={missing_state}&token=valid-looking-token",
            follow_redirects=False,
        )

    assert _fragment_query(expired.headers["location"])["error"] == ["invalid_state"]
    assert _fragment_query(missing.headers["location"])["error"] == ["missing_token"]
    assert _fragment_query(missing_replay.headers["location"])["error"] == ["invalid_state"]
    validate.assert_not_called()


def test_callback_redaction_middleware_scrubs_secret_query_values_before_routing():
    cases = [
        (
            "/auth/feishu/callback",
            b"code=provider-code&state=opaque-state",
            {"code": "provider-code"},
        ),
        (
            "/auth/ttc/callback",
            b"token=provider-token&access_token=alternate-token&state=opaque-state",
            {"token": "provider-token", "access_token": "alternate-token"},
        ),
        (
            "/auth/ttc/callback/",
            b"token=provider-token&state=opaque-state",
            {"token": "provider-token"},
        ),
    ]

    async def invoke(path: str, query_string: bytes):
        captured = {}

        async def downstream(scope, receive, send):
            captured["query_string"] = scope["query_string"]
            captured["secrets"] = scope["state"]["auth_callback_secrets"]

        middleware = RedactAuthCallbackMiddleware(downstream)
        await middleware(
            {"type": "http", "path": path, "query_string": query_string},
            None,
            None,
        )
        return captured

    for path, query_string, expected_secrets in cases:
        captured = asyncio.run(invoke(path, query_string))
        visible_query = parse_qs(captured["query_string"].decode())

        assert captured["secrets"] == expected_secrets
        assert visible_query["state"] == ["opaque-state"]
        for key, raw_secret in expected_secrets.items():
            assert visible_query[key] == ["[REDACTED]"]
            assert raw_secret not in captured["query_string"].decode()
