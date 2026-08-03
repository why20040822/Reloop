"""Runtime paths and environment-backed configuration for Reloop."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = Path(os.getenv("RELOOP_DATA_DIR", str(PROJECT_ROOT / "data"))).expanduser()
STATIC_DIR = PROJECT_ROOT / "static"
DB_PATH = DATA_DIR / "candidates.db"


def ensure_data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR
