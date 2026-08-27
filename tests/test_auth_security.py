"""Authentication boundary regressions for production and explicit development mode."""

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from reloop.config import settings
from reloop.db.engine import SessionLocal, init_db
from reloop.db.models import TalentProfile, User
from reloop.main import app
from reloop.modules.auth.feishu import create_session_token


def test_obsolete_auto_login_module_cannot_persist_plaintext_credentials():
    module = Path(__file__).resolve().parents[1] / "reloop/modules/auth/auto_login.py"

    assert not module.exists()


@pytest.fixture
def clean_auth_db(monkeypatch):
    init_db()
    db = SessionLocal()
    try:
        db.query(TalentProfile).delete()
        db.query(User).delete()
        db.commit()
    finally:
        db.close()
    monkeypatch.setattr(settings, "auth_require_token", True)
    monkeypatch.setattr(settings, "auth_allow_guest", True)
    monkeypatch.setattr(settings, "auth_auto_register", True)


def _add_user(user_id: str) -> str:
    db = SessionLocal()
    try:
        db.add(User(user_id=user_id, display_name=user_id))
        db.commit()
    finally:
        db.close()
    return create_session_token(user_id)


def test_production_rejects_missing_token_even_with_owner_header(clean_auth_db):
    with TestClient(app) as client:
        response = client.get("/auth/me", headers={"X-Owner-User-Id": "victim-user"})

    assert response.status_code == 401
    db = SessionLocal()
    try:
        assert db.query(User).count() == 0
    finally:
        db.close()


def test_production_rejects_missing_token_instead_of_creating_guest(clean_auth_db):
    with TestClient(app) as client:
        response = client.get("/auth/me")

    assert response.status_code == 401
    db = SessionLocal()
    try:
        assert db.query(User).filter(User.user_id == settings.guest_owner_id).first() is None
    finally:
        db.close()


def test_signed_identity_wins_over_conflicting_owner_header(clean_auth_db):
    token = _add_user("signed-owner")
    _add_user("header-owner")

    with TestClient(app) as client:
        response = client.get(
            "/auth/me",
            headers={"X-Auth-Token": token, "X-Owner-User-Id": "header-owner"},
        )

    assert response.status_code == 200
    assert response.json()["user_id"] == "signed-owner"


def test_development_owner_header_remains_available_when_token_enforcement_is_off(
    clean_auth_db, monkeypatch
):
    monkeypatch.setattr(settings, "auth_require_token", False)

    with TestClient(app) as client:
        response = client.get("/auth/me", headers={"X-Owner-User-Id": "development-owner"})

    assert response.status_code == 200
    assert response.json()["user_id"] == "development-owner"


def test_ttc_login_url_never_accepts_development_owner_header(clean_auth_db, monkeypatch):
    monkeypatch.setattr(settings, "auth_require_token", False)
    monkeypatch.setattr(settings, "auth_public_base_url", "https://reloop.example.test")

    with TestClient(app) as client:
        response = client.get(
            "/auth/ttc/login-url", headers={"X-Owner-User-Id": "development-owner"}
        )

    assert response.status_code == 401


def test_production_ingest_rejects_owner_header_and_does_not_start_write(clean_auth_db):
    with TestClient(app) as client, patch(
        "reloop.api.sync.talent_sync_service.sync_for_user_async"
    ) as sync:
        response = client.post(
            "/sync/ttc/ingest",
            headers={"X-Owner-User-Id": "victim-user"},
            json={"talents": [{"id": "poison", "name": "Injected"}]},
        )

    assert response.status_code == 401
    sync.assert_not_called()


def test_production_ingest_rejects_signed_guest_pool_write(clean_auth_db):
    token = _add_user(settings.guest_owner_id)

    with TestClient(app) as client, patch(
        "reloop.api.sync.talent_sync_service.sync_for_user_async"
    ) as sync:
        response = client.post(
            "/sync/ttc/ingest",
            headers={"X-Auth-Token": token},
            json={"talents": [{"id": "poison", "name": "Injected"}]},
        )

    assert response.status_code == 401
    sync.assert_not_called()


def test_production_ingest_accepts_signed_non_guest_user(clean_auth_db):
    token = _add_user("signed-ingest-owner")

    with TestClient(app) as client, patch(
        "reloop.api.sync.talent_sync_service.sync_for_user_async", return_value="sync-signed"
    ) as sync:
        response = client.post(
            "/sync/ttc/ingest",
            headers={"X-Auth-Token": token},
            json={"talents": [{"id": "owned", "name": "Owned"}]},
        )

    assert response.status_code == 200
    sync.assert_called_once_with(
        "signed-ingest-owner", raw_payload=[{"id": "owned", "name": "Owned"}]
    )


def test_development_ingest_accepts_explicit_owner_header(clean_auth_db, monkeypatch):
    monkeypatch.setattr(settings, "auth_require_token", False)

    with TestClient(app) as client, patch(
        "reloop.api.sync.talent_sync_service.sync_for_user_async", return_value="sync-dev"
    ) as sync:
        response = client.post(
            "/sync/ttc/ingest",
            headers={"X-Owner-User-Id": "development-owner"},
            json={"talents": [{"id": "dev", "name": "Development"}]},
        )

    assert response.status_code == 200
    sync.assert_called_once_with(
        "development-owner", raw_payload=[{"id": "dev", "name": "Development"}]
    )


def test_development_sync_write_rejects_anonymous_guest_fallback(clean_auth_db, monkeypatch):
    monkeypatch.setattr(settings, "auth_require_token", False)

    with TestClient(app) as client, patch(
        "reloop.api.sync.talent_sync_service.sync_for_user_async"
    ) as sync:
        response = client.post(
            "/sync/ttc/ingest",
            json={"talents": [{"id": "guest", "name": "Anonymous"}]},
        )

    assert response.status_code == 401
    sync.assert_not_called()


def test_production_ttc_sync_rejects_owner_header_before_using_shared_pool(clean_auth_db):
    with TestClient(app) as client, patch(
        "reloop.api.sync.talent_sync_service.sync_for_user_async"
    ) as sync:
        response = client.post("/sync/ttc", headers={"X-Owner-User-Id": "victim-user"})

    assert response.status_code == 401
    sync.assert_not_called()
