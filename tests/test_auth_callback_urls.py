"""OAuth callback addresses must be fixed server-side, never supplied by the SPA."""

from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from reloop.config import settings
from reloop.main import app


def test_ttc_login_uses_server_owned_public_callback(monkeypatch):
    monkeypatch.setattr(settings, "auth_public_base_url", "https://reloop.example.test/")
    with TestClient(app) as client:
        response = client.get("/auth/ttc/login-url")

    assert response.status_code == 200, response.text
    callback_url = parse_qs(urlparse(response.json()["url"]).query)["callback_url"][0]
    assert callback_url == "https://reloop.example.test/auth/ttc/callback"


def test_provider_callback_moves_query_into_spa_hash_route(monkeypatch):
    monkeypatch.setattr(settings, "auth_public_base_url", "https://reloop.example.test")
    with TestClient(app) as client:
        response = client.get("/auth/feishu/callback?code=one-time-code&state=reloop", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "https://reloop.example.test/#/auth/callback?code=one-time-code&state=reloop"
