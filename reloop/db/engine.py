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
    """FastAPI 依赖: 每个请求一个会话。

    生产落库方式: 请求正常结束自动 commit; 抛异常则 rollback;
    最后关闭会话。这样业务代码无需在每个写接口里手动 commit,
    也避免"接口返回成功但写入被静默回滚"的数据丢失问题。
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """根据 ORM 模型建表(开发/测试用; 生产建议走 sql/schema.sql)。"""
    from reloop.db import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
