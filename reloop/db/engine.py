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
    _ensure_columns()


def _ensure_columns() -> None:
    """幂等补列: 对已有旧库补上后续版本新增的列(create_all 不会 ALTER 旧表)。

    升级点:
      - v0.3: users.ttc_auth_token / users.ttc_bound_name(飞书登录 + TTC 绑定)
    """
    from sqlalchemy import inspect, text

    expected = {
        "users": [
            ("ttc_auth_token", "TEXT NULL"),
            ("ttc_bound_name", "VARCHAR(128) NULL"),
        ],
    }
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, columns in expected.items():
            if not insp.has_table(table):
                continue  # 新库: create_all 已按最新模型建好
            existing = {c["name"] for c in insp.get_columns(table)}
            for col_name, col_ddl in columns:
                if col_name in existing:
                    continue
                if engine.dialect.name == "mysql":
                    # MySQL 8 无 ADD COLUMN IF NOT EXISTS, 先查 information_schema
                    has = conn.execute(
                        text(
                            "SELECT COUNT(*) FROM information_schema.columns "
                            "WHERE table_schema = DATABASE() "
                            "AND table_name = :t AND column_name = :c"
                        ),
                        {"t": table, "c": col_name},
                    ).scalar()
                    if has:
                        continue
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_ddl}"))

