"""Guest auto-sync must use only the service-owned shared TTC source."""

from unittest.mock import patch

from fastapi.testclient import TestClient

from reloop.config import settings
from reloop.db.engine import SessionLocal, init_db
from reloop.db.models import TalentProfile, User
from reloop.main import app


def test_empty_guest_pool_autosync_uses_shared_token_and_source(monkeypatch):
    monkeypatch.setattr(settings, "auth_allow_guest", True)
    monkeypatch.setattr(settings, "ttc_shared_auth_token", "shared-service-token")
    monkeypatch.setattr(settings, "ttc_talent_auth_token", "legacy-token-that-must-not-be-used")
    monkeypatch.setattr(settings, "ttc_talent_space_id", "U-shared")
    init_db()
    db = SessionLocal()
    try:
        db.query(TalentProfile).filter(TalentProfile.owner_user_id == settings.guest_owner_id).delete()
        db.query(User).filter(User.user_id == settings.guest_owner_id).delete()
        db.commit()
    finally:
        db.close()

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
