"""Reloop HTTP application entry point."""

import os

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from reloop.api import legacy
from reloop.api.deps import require_api_access
from reloop.api.routes import ingest, jobs, ops, review, search
from reloop.config import STATIC_DIR

app = FastAPI(
    title="TTC 候选人数据收藏器",
    version="0.1.0",
    dependencies=[Depends(require_api_access)],
)
cors_origins = [item.strip() for item in os.getenv("RELOOP_CORS_ORIGINS", "").split(",") if item.strip()]
if cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Actor"],
    )
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
for router in (ops.router, ingest.router, jobs.router, search.router, review.router):
    app.include_router(router)
app.router.on_startup.append(legacy.startup)

__all__ = ["app"]
