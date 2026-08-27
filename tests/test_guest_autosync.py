"""Guest auto-sync must use only the service-owned shared TTC source."""

from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from reloop.api.deps import get_current_user
from reloop.config import settings
from reloop.db.engine import SessionLocal, init_db
from reloop.db.models import TalentProfile, User
from reloop.main import app


def _empty_guest_pool():
    init_db()
    db = SessionLocal()
    try:
        db.query(TalentProfile).filter(TalentProfile.owner_user_id == settings.guest_owner_id).delete()
        db.query(User).filter(User.user_id == settings.guest_owner_id).delete()
        db.commit()
    finally:
        db.close()


def test_concurrent_guest_creation_recovers_the_user_created_by_another_request(monkeypatch):
    monkeypatch.setattr(settings, "auth_allow_guest", True)
    monkeypatch.setattr(settings, "auth_require_token", False)
    _empty_guest_pool()
    db = SessionLocal()
    original_commit = db.commit
    raced = False

    def commit_after_other_request_wins():
        nonlocal raced
        if raced:
            return original_commit()
        raced = True
        db.rollback()
        winner = SessionLocal()
        try:
            winner.add(User(user_id=settings.guest_owner_id, display_name="访客"))
            winner.commit()
        finally:
            winner.close()
        raise IntegrityError("INSERT INTO users", {}, Exception("duplicate guest"))

    monkeypatch.setattr(db, "commit", commit_after_other_request_wins)
    try:
        user = get_current_user(db=db, x_owner_user_id=None, x_auth_token=None)
    finally:
        db.close()

    assert user.user_id == settings.guest_owner_id
    assert user.display_name == "访客"


def test_manual_guest_sync_rejects_legacy_token_only_configuration(monkeypatch):
    monkeypatch.setattr(settings, "auth_allow_guest", True)
    monkeypatch.setattr(settings, "auth_require_token", False)
    monkeypatch.setattr(settings, "ttc_shared_auth_token", "")
    monkeypatch.setattr(settings, "ttc_talent_auth_token", "legacy-token-that-must-not-be-used")

    with TestClient(app) as client, patch(
        "reloop.api.sync.talent_sync_service.sync_for_user_async",
    ) as sync:
        response = client.post(
            "/sync/ttc", headers={"X-Owner-User-Id": settings.guest_owner_id}
        )

    assert response.status_code == 409, response.text
    assert "BRAINX_TTC_SHARED_AUTH_TOKEN" in response.json()["detail"]
    sync.assert_not_called()


def test_empty_guest_pool_autosync_rejects_legacy_token_only_configuration(monkeypatch):
    monkeypatch.setattr(settings, "auth_allow_guest", True)
    monkeypatch.setattr(settings, "auth_require_token", False)
    monkeypatch.setattr(settings, "ttc_shared_auth_token", "")
    monkeypatch.setattr(settings, "ttc_talent_auth_token", "legacy-token-that-must-not-be-used")
    monkeypatch.setattr(settings, "ttc_talent_space_id", "U-shared")
    _empty_guest_pool()

    with TestClient(app) as client, patch(
        "reloop.modules.sync.client.talent_sync_service.sync_for_user_async",
    ) as sync:
        response = client.get("/talents")

    assert response.status_code == 200, response.text
    sync.assert_not_called()


def test_empty_guest_pool_autosync_uses_shared_token_and_source(monkeypatch):
    monkeypatch.setattr(settings, "auth_allow_guest", True)
    monkeypatch.setattr(settings, "auth_require_token", False)
    monkeypatch.setattr(settings, "ttc_shared_auth_token", "shared-service-token")
    monkeypatch.setattr(settings, "ttc_talent_auth_token", "legacy-token-that-must-not-be-used")
    monkeypatch.setattr(settings, "ttc_talent_space_id", "U-shared")
    _empty_guest_pool()

    with TestClient(app) as client, patch(
        "reloop.modules.sync.client.talent_sync_service.sync_for_user_async",
        return_value="shared-sync",
    ) as sync:
        response = client.get("/talents")

    assert response.status_code == 200, response.text
    sync.assert_called_once_with(
        settings.guest_owner_id,
        space_id="U-shared",
        auth_token="shared-service-token",
        source="shared",
    )
