#!/usr/bin/env python3
# ONE-OFF (2026-08-03)
# Input: inspect --help and the operator invocation record before running.
# Execution: do not rerun without explicit operator confirmation.

"""
自动随机间隔批量导入脚本。

在一个时间窗口内（默认 60 分钟），以随机间隔自动导入 N 份简历。
适合模拟"人工不定时上传"或平滑调用外部 API 配额。

用法示例
--------
    # 默认：60 分钟内随机导入 50 份（Source MySQL）
    python scripts/auto_bulk_import.py --source mysql --keyword "AI产品经理"

    # 60 分钟内从 TTC API 随机导入 50 份（带 profile_summary）
    export TTC_JWT_TOKEN=eyJ...
    python scripts/auto_bulk_import.py --source ttc --keyword "AI产品经理" --profiles

    # 30 分钟内导入 20 份，间隔 20-60 秒
    python scripts/auto_bulk_import.py --source mysql --keyword "后端" \
        --count 20 --duration-minutes 30 --min-interval 20 --max-interval 60
"""

import argparse
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]

# 复用 bulk_import_resumes 的函数与配置
import bulk_import_resumes as bulk
from ttc_daemon import db as local_db


def _next_interval(
    elapsed: float,
    duration_seconds: float,
    done: int,
    count: int,
    min_interval: float,
    max_interval: float,
) -> float:
    """计算下一次导入前的随机等待秒数，确保剩余次数能在时间内完成。"""
    remaining_time = max(0.0, duration_seconds - elapsed)
    remaining_count = max(1, count - done)

    # 预留剩余次数所需的最小时间
    min_needed = remaining_count * min_interval
    if remaining_time < min_needed:
        # 时间不够了，按最小间隔跑
        return min_interval

    # 剩余时间充裕时，随机但不要超过剩余时间能容纳的上限
    upper = min(max_interval, (remaining_time - (remaining_count - 1) * min_interval))
    lower = min_interval
    if upper <= lower:
        return lower

    return random.uniform(lower, upper)


def _import_one(
    source: str,
    keyword: str,
    token: str,
    fetch_profiles: bool,
    workers: int,
    existing_keys: Set[str],
    progress: Dict[str, Any],
    dry_run: bool,
) -> Tuple[int, int, int, int, List[Dict[str, Any]]]:
    """调用 bulk_import_resumes 导入 1 份，返回统计与记录。"""
    if source == "mysql":
        return bulk.bulk_import_mysql(
            keyword=keyword,
            max_resumes=1,
            batch_size=1,
            existing_keys=existing_keys,
            progress=progress,
            dry_run=dry_run,
        )
    if source == "ttc":
        if not token:
            raise RuntimeError("TTC API 需要 TTC_JWT_TOKEN")
        return bulk.bulk_import_ttc(
            keyword=keyword,
            max_resumes=1,
            batch_size=1,
            workers=workers,
            fetch_profiles=fetch_profiles,
            token=token,
            existing_keys=existing_keys,
            progress=progress,
            dry_run=dry_run,
        )
    raise ValueError(f"不支持的 source: {source}")


def main() -> int:
    bulk.load_env()
    local_db.init_db()

    parser = argparse.ArgumentParser(description="自动随机间隔批量导入简历")
    parser.add_argument("--source", choices=["mysql", "ttc"], default="mysql", help="数据源")
    parser.add_argument("--keyword", default="AI产品经理", help="搜索关键词")
    parser.add_argument("--count", type=int, default=50, help="目标导入份数")
    parser.add_argument("--duration-minutes", type=int, default=60, help="总时间窗口（分钟）")
    parser.add_argument("--min-interval", type=float, default=30, help="最小间隔秒数")
    parser.add_argument("--max-interval", type=float, default=120, help="最大间隔秒数")
    parser.add_argument("--workers", type=int, default=2, help="TTC profile_summary 并发数")
    parser.add_argument("--profiles", action="store_true", help="拉取 TTC profile_summary")
    parser.add_argument("--dry-run", action="store_true", help="空跑，不写入数据库")
    parser.add_argument("--reset-progress", action="store_true", help="重置断点续传进度")
    parser.add_argument("--jwt", type=str, default="", help="TTC JWT Token（推荐环境变量）")
    args = parser.parse_args()

    if args.count < 1:
        parser.error("--count 必须 >= 1")
    if args.duration_minutes < 1:
        parser.error("--duration-minutes 必须 >= 1")
    if not (0 < args.min_interval <= args.max_interval):
        parser.error("--min-interval 必须 > 0 且 <= --max-interval")

    token = args.jwt or os.getenv("TTC_JWT_TOKEN", "")
    duration_seconds = args.duration_minutes * 60

    progress: Dict[str, Any] = {}
    if args.reset_progress:
        bulk.save_progress({})
        print("[INFO] 已重置进度文件")
    else:
        progress = bulk.load_progress()
        cache_key = f"{args.source}:{args.keyword}"
        if progress.get("cache_key") != cache_key:
            progress = {"processed_ids": progress.get("processed_ids", [])}
            progress["cache_key"] = cache_key
            bulk.save_progress(progress)

    existing_keys = bulk.load_existing_keys()
    print(f"[INFO] 自动导入开始")
    print(f"[INFO] source={args.source}, keyword={args.keyword}, count={args.count}")
    print(f"[INFO] 时间窗口={args.duration_minutes}min, 间隔={args.min_interval}s~{args.max_interval}s, dry_run={args.dry_run}")
    print(f"[INFO] 本地 candidates 表已有 {len(existing_keys)} 个去重键")

    start = time.time()
    total_fetched = total_imported = total_skipped = total_failed = 0

    for i in range(1, args.count + 1):
        elapsed = time.time() - start
        if elapsed >= duration_seconds:
            print(f"[INFO] 时间窗口已到，停止导入（已完成 {i-1}/{args.count}）")
            break

        interval = _next_interval(
            elapsed, duration_seconds, i - 1, args.count,
            args.min_interval, args.max_interval,
        )
        next_at = datetime.now().isoformat(timespec="seconds")
        print(f"\n[{i}/{args.count}] 下次导入时间: {next_at}, 间隔: {interval:.1f}s")
        time.sleep(interval)

        try:
            tf, im, sk, fl, _ = _import_one(
                args.source, args.keyword, token, args.profiles, args.workers,
                existing_keys, progress, args.dry_run,
            )
        except Exception as exc:
            print(f"[ERROR] 第 {i} 次导入异常: {exc}")
            total_failed += 1
            continue

        total_fetched += tf
        total_imported += im
        total_skipped += sk
        total_failed += fl

        if tf == 0:
            print(f"[WARN] 第 {i} 次未拉到数据，可能源已空或关键词无结果")

        print(
            f"[INFO] 本轮: 拉取={tf}, 导入={im}, 跳过={sk}, 失败={fl} | "
            f"累计: 导入={total_imported}, 跳过={total_skipped}, 失败={total_failed}"
        )

    elapsed = time.time() - start
    print("\n" + "=" * 60)
    print(f"自动导入完成（dry_run={args.dry_run}）")
    print(f"  计划: {args.count} 份 / {args.duration_minutes} 分钟")
    print(f"  实际: {total_imported} 导入, {total_skipped} 跳过, {total_failed} 失败")
    print(f"  拉取: {total_fetched}")
    print(f"  耗时: {elapsed:.2f}s")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
