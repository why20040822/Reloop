"""The test session must never inherit a caller-provided database target."""

from reloop.config import settings


def test_pytest_database_url_overrides_external_environment():
    assert settings.database_url.endswith("reloop-test.db")
    assert "external-test-database" not in settings.database_url
