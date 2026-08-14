"""Reloop FastAPI 应用入口。

启动:
    conda activate reloop
    uvicorn reloop.main:app --reload --host 0.0.0.0 --port 8000
"""

import logging

from fastapi import FastAPI

from reloop.api import positions, recommend, sync, talents
from reloop.config import settings
from reloop.db.engine import init_db

logging.basicConfig(level=settings.app_log_level.upper())
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Reloop",
    description="私域人才触达优先级推荐 —— 今天你最应该联系谁,以及为什么。",
    version="0.2.0",
)


@app.on_event("startup")
def on_startup() -> None:
    """建表(开发期自动; 生产走 sql/schema.sql)。"""
    try:
        init_db()
        logger.info("[startup] DB tables ready")
    except Exception as e:  # noqa: BLE001
        logger.warning("[startup] init_db skipped (DB 未就绪?): %s", e)


@app.get("/health", tags=["系统"])
def health():
    return {"status": "ok", "app": settings.app_name, "env": settings.app_env}


# 挂载路由
app.include_router(sync.router)
app.include_router(talents.router)
app.include_router(positions.router)
app.include_router(recommend.router)
