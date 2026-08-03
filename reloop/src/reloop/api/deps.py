"""FastAPI dependency providers.

The current deployment uses a local SQLite store.  Keeping these providers in
the API layer makes the storage and actor boundary explicit for later router
extraction without putting FastAPI imports into domain or ingestion modules.
"""

from __future__ import annotations

import hmac
import os
import sqlite3
from collections.abc import Iterator
from contextlib import closing

from fastapi import HTTPException, Request

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


def require_api_access(request: Request) -> str:
    """Require a bearer token when the API is configured for shared access.

    Local development remains usable without a token.  Deployments that bind
    beyond localhost must set ``RELOOP_API_TOKEN``; the main app installs this
    dependency for every API route, while health remains intentionally public.
    """

    expected = os.getenv("RELOOP_API_TOKEN", "").strip()
    if request.url.path == "/api/health" or not expected:
        return "local"
    authorization = request.headers.get("authorization", "")
    scheme, _, supplied = authorization.partition(" ")
    if scheme.lower() != "bearer" or not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="需要有效的 API Bearer token")
    return request.headers.get("x-actor", "local")[:120] or "local"


def get_actor(request: Request) -> str:
    """Return the server-resolved actor for local/API calls.

    Authentication middleware can replace this dependency without changing
    route signatures.  An empty actor is intentionally not treated as an
    elevated identity by downstream authorization checks.
    """

    return request.headers.get("x-actor", "local")[:120] or "local"
