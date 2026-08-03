"""FastAPI dependency providers.

The current deployment uses a local SQLite store.  Keeping these providers in
the API layer makes the storage and actor boundary explicit for later router
extraction without putting FastAPI imports into domain or ingestion modules.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing

from reloop.config import DB_PATH


def get_db() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        with closing(connection):
            pass


def get_actor() -> str:
    """Return the server-resolved actor for local/API calls.

    Authentication middleware can replace this dependency without changing
    route signatures.  An empty actor is intentionally not treated as an
    elevated identity by downstream authorization checks.
    """

    return "local"
