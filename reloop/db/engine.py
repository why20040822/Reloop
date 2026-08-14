"""SQLAlchemy 引擎 / 会话工厂。

唯一数据库: RDS MySQL (生产)。
测试可用 BRAINX_DATABASE_URL=sqlite:///... 覆盖为本地 SQLite。
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from reloop.config import settings


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


_dsn = settings.sync_dsn

if _dsn.startswith("sqlite"):
    engine = create_engine(_dsn, future=True, connect_args={"check_same_thread": False})
else:
    engine = create_engine(
        _dsn,
        pool_size=settings.mysql_pool_size,
        pool_pre_ping=True,
        pool_recycle=3600,
        future=True,
    )

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖: 提供一个数据库会话并在请求结束后关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """根据 ORM 模型建表(开发/测试用; 生产建议走 sql/schema.sql)。"""
    from reloop.db import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
