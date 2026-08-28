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
    import logging

    from reloop.db import models  # noqa: F401

    try:
        Base.metadata.create_all(bind=engine)
    except Exception as e:  # noqa: BLE001
        # gunicorn 多 worker 并发启动时 create_all 有 check-then-create 竞态,
        # 表已由其他 worker 建好会抛 1050 —— 忽略, 补列逻辑照常执行。
        logging.getLogger(__name__).warning("[init_db] create_all skipped: %s", e)
    _ensure_columns()
    _ensure_indexes()


def _ensure_indexes() -> None:
    """幂等补唯一索引(F2, 2026-08-28): 旧库补 uq_talent_owner_source。

    create_all 不会给已存在的表加约束。若表里已有重复数据, 创建唯一索引会失败——
    此时只告警并提示先跑 scripts/dedup_talents.py, 不阻塞启动。
    """
    import logging

    from sqlalchemy import text

    logger = logging.getLogger(__name__)
    idx_name = "uq_talent_owner_source"
    try:
        with engine.begin() as conn:
            if engine.dialect.name == "mysql":
                has = conn.execute(
                    text(
                        "SELECT COUNT(*) FROM information_schema.statistics "
                        "WHERE table_schema = DATABASE() "
                        "AND table_name = 'talent_profiles' AND index_name = :i"
                    ),
                    {"i": idx_name},
                ).scalar()
                if has:
                    return
                stmt = (
                    "ALTER TABLE talent_profiles "
                    "ADD UNIQUE KEY uq_talent_owner_source (owner_user_id, source_id)"
                )
            else:  # sqlite
                row = conn.execute(
                    text(
                        "SELECT COUNT(*) FROM sqlite_master "
                        "WHERE type='index' AND name = :i"
                    ),
                    {"i": idx_name},
                ).scalar()
                if row:
                    return
                stmt = (
                    "CREATE UNIQUE INDEX uq_talent_owner_source "
                    "ON talent_profiles (owner_user_id, source_id)"
                )
            conn.execute(text(stmt))
            logger.info("[init_db] unique index uq_talent_owner_source created")
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "[init_db] 唯一索引 uq_talent_owner_source 创建失败(表里可能有历史重复数据): %s; "
            "请先运行 python scripts/dedup_talents.py 去重后重启", e
        )


def _ensure_columns() -> None:
    """幂等补列: 对已有旧库补上后续版本新增的列(create_all 不会 ALTER 旧表)。

    升级点:
      - v0.3: users.ttc_auth_token / users.ttc_bound_name(飞书登录 + TTC 绑定)
      - v3.2: talent_profiles.notes / stability / work_history(运营备注 + 稳定性 + 工作经历)
      - v3.5: talent_profiles.projects / delivery_records / resume_updated_at
      - v4.1: talent_profiles.contact_phone/contact_email/seek_status/
              current_salary/expected_salary/target_positions/education_history/contact_status
              (对齐 TTC 真实接口字段 + 备注: 收藏/联系状态/备注语句)
      - v4.2: positions.jd_analysis/jd_analysis_version(结构化 JD 解析结果)
    """
    from sqlalchemy import inspect, text

    expected = {
        "users": [
            ("ttc_auth_token", "TEXT NULL"),
            ("ttc_bound_name", "VARCHAR(128) NULL"),
            ("last_sync_at", "DATETIME NULL"),
            ("last_sync_count", "INTEGER NULL"),
            # R4(2026-08-28): 会话版本(token 吊销)
            ("session_version", "INTEGER NOT NULL DEFAULT 0"),
        ],
        "talent_profiles": [
            ("notes", "TEXT NULL"),
            ("stability", "JSON NULL"),
            ("work_history", "JSON NULL"),
            ("projects", "JSON NULL"),
            ("delivery_records", "JSON NULL"),
            ("resume_updated_at", "DATETIME NULL"),
            ("contact_phone", "VARCHAR(64) NULL"),
            ("contact_email", "VARCHAR(128) NULL"),
            ("seek_status", "VARCHAR(64) NULL"),
            ("current_salary", "VARCHAR(64) NULL"),
            ("expected_salary", "VARCHAR(64) NULL"),
            ("target_positions", "JSON NULL"),
            ("education_history", "JSON NULL"),
            ("contact_status", "VARCHAR(32) NULL"),
        ],
        "positions": [
            ("jd_analysis", "JSON NULL"),
            ("jd_analysis_version", "VARCHAR(32) NULL"),
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
