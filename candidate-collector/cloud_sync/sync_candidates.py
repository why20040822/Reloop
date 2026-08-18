"""Sync local candidate-collector SQLite candidates to cloud RDS PostgreSQL.

Usage:
    cd /Users/ashley/Downloads/ttc的交易系统/candidate-collector
    python cloud_sync/sync_candidates.py

Environment:
    RDS_HOST, RDS_PORT, RDS_DB, RDS_USER, RDS_PASSWORD
    Optional: RDS_SYNC_BATCH_SIZE, RDS_SYNC_DRY_RUN
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from .client import CloudSyncClient
from .config import rds_configured
from .transform import sqlite_row_to_cloud


DB_PATH = Path(__file__).resolve().parent.parent / "data" / "candidates.db"


def fetch_local_candidates(limit: int = 0) -> list[dict]:
    """Read candidates from the local SQLite database."""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Local DB not found: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    sql = "SELECT * FROM candidates ORDER BY id"
    if limit > 0:
        sql += f" LIMIT {limit}"

    rows = [sqlite_row_to_cloud(r) for r in cur.execute(sql).fetchall()]
    conn.close()
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="同步本地候选人数据到云端 RDS")
    parser.add_argument("--limit", type=int, default=0, help="最多同步数量，0 表示全部")
    parser.add_argument("--dry-run", action="store_true", help="预览但不写入")
    parser.add_argument("--ensure-schema", action="store_true", help="同步前先创建表")
    args = parser.parse_args()

    if not rds_configured():
        print("错误：RDS 环境变量未配置。请设置 RDS_HOST, RDS_DB, RDS_USER, RDS_PASSWORD。")
        return 1

    client = CloudSyncClient()
    if args.dry_run:
        client.dry_run = True

    if args.ensure_schema:
        client.ensure_schema()

    rows = fetch_local_candidates(args.limit)
    print(f"本地候选人数：{len(rows)}")
    if not rows:
        return 0

    stats = client.upsert_candidates(rows)
    print(f"同步完成：新增 {stats['inserted']}，更新 {stats['updated']}，错误 {stats['errors']}")
    print(f"云端总数：{client.count_candidates()}")
    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
