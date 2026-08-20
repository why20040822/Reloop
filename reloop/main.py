"""Reloop FastAPI 应用入口。

启动:
    conda activate reloop
    uvicorn reloop.main:app --reload --host 0.0.0.0 --port 8000
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from reloop.api import auth, positions, recommend, sync, talents
from reloop.config import settings
from reloop.db.engine import init_db

logging.basicConfig(level=settings.app_log_level.upper())
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """建表(开发期自动; 生产走 sql/schema.sql)。"""
    try:
        init_db()
        logger.info("[startup] DB tables ready")
    except Exception as e:  # noqa: BLE001
        logger.warning("[startup] init_db skipped (DB 未就绪?): %s", e)
    yield


app = FastAPI(
    title="Reloop",
    description="私域人才触达优先级推荐 —— 今天你最应该联系谁,以及为什么。",
    version="0.2.0",
    lifespan=lifespan,
)

# 允许配套前端跨域调用 (前端预览域名与本服务不同源)。
# 来源用 BRAINX_CORS_ALLOW_ORIGINS 配置; 默认 "*" 放通全部(开发期)。
_cors_origins = settings.cors_origins_list
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    # 允许携带自定义隔离头 X-Owner-User-Id; "*" 来源下不能同时开 credentials。
    allow_credentials=_cors_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["系统"])
def health():
    return {"status": "ok", "app": settings.app_name, "env": settings.app_env}


# 挂载路由
app.include_router(auth.router)
app.include_router(sync.router)
app.include_router(talents.router)
app.include_router(positions.router)
app.include_router(recommend.router)


# 前后端合并部署: 后端直接伺服 webapp/ 静态前端 (同源, 免 CORS)。
# 必须放在 API 路由之后挂载, 这样 /docs、/talents、/recommend 等接口优先匹配,
# 其余路径(含 "/")回退到 SPA 入口 index.html (hash 路由, 无需服务端路由)。
_WEBAPP_DIR = settings.webapp_path
if settings.serve_webapp and _WEBAPP_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(_WEBAPP_DIR), html=True), name="webapp")
    logger.info("[startup] serving webapp from %s", _WEBAPP_DIR)
else:
    logger.info("[startup] webapp serving disabled (serve_webapp=%s, dir=%s)",
                settings.serve_webapp, _WEBAPP_DIR)
