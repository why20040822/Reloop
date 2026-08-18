"""Load cloud database configuration from environment variables.

Never hard-code secrets here; they are read from the process environment or
a `.env` file at runtime.
"""
from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


def _load_env() -> None:
    """Load .env from the project root if python-dotenv is available."""
    if load_dotenv is None:
        return
    root = Path(__file__).resolve().parent.parent.parent
    env_path = root / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)
    # Also allow OS env to take precedence.
    load_dotenv(override=False)


_load_env()


RDS_HOST = os.getenv("RDS_HOST", "")
RDS_PORT = int(os.getenv("RDS_PORT", "3306"))
RDS_DB = os.getenv("RDS_DB", "ttc_talent")
RDS_USER = os.getenv("RDS_USER", "")
RDS_PASSWORD = os.getenv("RDS_PASSWORD", "")

# Optional: restrict sync batch size and dry-run mode.
RDS_SYNC_BATCH_SIZE = int(os.getenv("RDS_SYNC_BATCH_SIZE", "100"))
RDS_SYNC_DRY_RUN = os.getenv("RDS_SYNC_DRY_RUN", "false").lower() in ("1", "true", "yes")


def rds_configured() -> bool:
    """Return True when all required RDS credentials are present."""
    return all([RDS_HOST, RDS_DB, RDS_USER, RDS_PASSWORD])


def build_conn_kwargs() -> dict:
    """Build pymysql connection keyword arguments from the environment configuration."""
    if not rds_configured():
        raise RuntimeError(
            "RDS credentials are missing. Set RDS_HOST, RDS_DB, RDS_USER, RDS_PASSWORD."
        )
    return {
        "host": RDS_HOST,
        "port": RDS_PORT,
        "user": RDS_USER,
        "password": RDS_PASSWORD,
        "database": RDS_DB,
        "charset": "utf8mb4",
        "autocommit": False,
    }
