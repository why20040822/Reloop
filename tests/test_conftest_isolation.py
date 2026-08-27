"""The test session must never inherit a caller-provided database target."""

from pathlib import Path

from reloop.config import settings


def test_pytest_database_url_overrides_external_environment():
    assert settings.database_url.endswith("reloop-test.db")
    assert "external-test-database" not in settings.database_url


def test_pipeline_collection_has_no_database_file_deletion_or_env_override():
    source = (Path(__file__).with_name("test_pipeline.py")).read_text(encoding="utf-8")

    assert "os.remove" not in source
    assert 'os.environ["BRAINX_DATABASE_URL"]' not in source
