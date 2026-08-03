"""Reloop HTTP application entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from reloop.api import legacy
from reloop.api.routes import ingest, jobs, ops, review, search
from reloop.config import STATIC_DIR

app = FastAPI(title="TTC 候选人数据收藏器", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
for router in (ops.router, ingest.router, jobs.router, search.router, review.router):
    app.include_router(router)
app.router.on_startup.append(legacy.startup)

__all__ = ["app"]
