"""Shared test configuration for isolated SQLite database state."""

import os
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def pytest_sessionstart(session):
    factory = session.config._tmp_path_factory
    database_path = factory.getbasetemp() / "reloop-test.db"
    os.environ["BRAINX_DATABASE_URL"] = f"sqlite:///{database_path}"
    os.environ.setdefault("BRAINX_LLM_API_KEY", "")
