"""Reloop HTTP application entry point."""

import os

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from reloop.api import legacy
from reloop.api.deps import require_api_access
from reloop.api.routes import cloud, ingest, jobs, ops, review, search
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
# cloud 先于 jobs：/api/candidates 由云端读接管（云端未配置时回退本地）
for router in (cloud.router, ops.router, ingest.router, jobs.router, search.router, review.router):
    app.include_router(router)
app.router.on_startup.append(legacy.startup)

__all__ = ["app"]
