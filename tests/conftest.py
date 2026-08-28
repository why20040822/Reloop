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
    # BUG-302(2026-08-28): 显式声明测试鉴权口径, 不依赖本机 .env——换机器/CI 不再全红
    os.environ.setdefault("BRAINX_AUTH_REQUIRE_TOKEN", "false")
    os.environ.setdefault("BRAINX_AUTH_SESSION_SECRET", "test-suite-secret")
    # 同步限流在测试里关闭(时间型限流会让连续调用 /sync/ttc 的测试随机 429)
    os.environ.setdefault("BRAINX_SYNC_MIN_INTERVAL_SECONDS", "0")
