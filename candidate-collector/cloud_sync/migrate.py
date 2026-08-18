"""MySQL migration runner + 版本校验（R1：结构变更只走 migrations）。

用法：
    python -m cloud_sync.migrate status    # 已应用/待应用清单
    python -m cloud_sync.migrate apply     # 按编号应用待执行迁移
    python -m cloud_sync.migrate verify    # live 版本 = repo 版本？不一致退出码 1

服务启动时调用 ``ensure_current()``：live 落后 repo 版本即拒绝启动
（设环境变量 TTC_MIGRATE_AUTO_APPLY=true 则先自动补齐再启动）。

幂等策略：schema_migrations 版本表为准；对重复执行才出现的
"Duplicate column / Duplicate key name / already exists" 错误容忍并继续，
其余错误立即中止（不静默吞，R7）。
"""
from __future__ import annotations

import hashlib
import logging
import re
import sys
from pathlib import Path

import pymysql

from .client import get_conn

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).with_name("migrations")

# 重复执行迁移时允许出现的错误片段（MySQL 无 ADD COLUMN IF NOT EXISTS 的补偿）
_TOLERABLE = ("Duplicate column", "Duplicate key name", "already exists")


def _version_of(path: Path) -> int:
    match = re.match(r"^(\d+)_", path.name)
    if not match:
        raise ValueError(f"migration 文件名必须以 NNN_ 开头: {path.name}")
    return int(match.group(1))


def list_repo_migrations() -> list[tuple[int, str, Path]]:
    """Return [(version, name, path)] sorted by version."""
    items = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        items.append((_version_of(path), path.name, path))
    return items


def _ensure_version_table(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INT PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            checksum VARCHAR(64) NOT NULL,
            applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def applied_versions(cur) -> dict[int, str]:
    _ensure_version_table(cur)
    cur.execute("SELECT version, name FROM schema_migrations ORDER BY version")
    return {row[0]: row[1] for row in cur.fetchall()}


def pending_migrations(cur) -> list[tuple[int, str, Path]]:
    done = applied_versions(cur)
    return [item for item in list_repo_migrations() if item[0] not in done]


def apply_all() -> list[str]:
    """Apply pending migrations in version order. Returns applied names."""
    applied: list[str] = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            todo = pending_migrations(cur)
            for version, name, path in todo:
                sql = path.read_text(encoding="utf-8")
                statements = [s.strip() for s in sql.split(";") if s.strip()]
                for stmt in statements:
                    # 跳过纯注释段（split 后可能只剩注释行）
                    body = "\n".join(
                        line for line in stmt.splitlines() if not line.strip().startswith("--")
                    ).strip()
                    if not body:
                        continue
                    try:
                        cur.execute(stmt)
                    except (pymysql.err.ProgrammingError, pymysql.err.OperationalError) as exc:
                        if any(t in str(exc) for t in _TOLERABLE):
                            logger.info("migrate %s: 容忍重复执行错误: %s", name, exc)
                            continue
                        logger.error("migrate %s 失败: %s", name, exc)
                        raise
                checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
                cur.execute(
                    "INSERT INTO schema_migrations (version, name, checksum) VALUES (%s, %s, %s)",
                    (version, name, checksum),
                )
                applied.append(name)
                logger.info("migrate applied: %s", name)
    return applied


def repo_version() -> int:
    migrations = list_repo_migrations()
    return migrations[-1][0] if migrations else 0


def live_version() -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            done = applied_versions(cur)
            return max(done) if done else 0


def is_current() -> bool:
    return live_version() >= repo_version()


def ensure_current(auto_apply: bool | None = None) -> None:
    """启动闸门：live 落后 repo 即拒绝启动（或按 env 自动补齐）。"""
    import os

    if auto_apply is None:
        auto_apply = os.getenv("TTC_MIGRATE_AUTO_APPLY", "").lower() in ("1", "true", "yes")
    repo = repo_version()
    live = live_version()
    if live >= repo:
        return
    if auto_apply:
        applied = apply_all()
        logger.info("自动补齐 migrations: %s", applied)
        return
    raise RuntimeError(
        f"数据库结构版本落后：live={live} repo={repo}。"
        f"请先运行 candidate-collector/.venv/bin/python -m cloud_sync.migrate apply，"
        f"或设 TTC_MIGRATE_AUTO_APPLY=true 自动补齐。（R1：结构变更只走 migrations）"
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        with get_conn() as conn:
            with conn.cursor() as cur:
                done = applied_versions(cur)
                for version, name, _ in list_repo_migrations():
                    mark = "✅ applied" if version in done else "⏳ pending"
                    print(f"{version:03d} {name}: {mark}")
    elif cmd == "apply":
        applied = apply_all()
        print(f"applied {len(applied)}: {applied}" if applied else "已是最新，无待执行迁移")
    elif cmd == "verify":
        repo, live = repo_version(), live_version()
        print(f"repo={repo} live={live} {'OK' if live >= repo else 'DRIFT'}")
        sys.exit(0 if live >= repo else 1)
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main()
