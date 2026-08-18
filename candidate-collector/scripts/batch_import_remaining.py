"""Batch import all remaining local PDF resumes into Feishu Base.

Usage:
    cd candidate-collector
    python3 scripts/batch_import_remaining.py [--limit N]
"""
from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingestion.pipeline import ingest_file


ROOT = Path(__file__).resolve().parent.parent.parent
RESUME_DIR = ROOT / "简历数据"
DB_PATH = ROOT / "candidate-collector" / "data" / "candidates.db"


def already_ingested_sha256s() -> set[str]:
    if not DB_PATH.exists():
        return set()
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT attachment_sha256 FROM ingestion_log WHERE attachment_sha256 IS NOT NULL"
    ).fetchall()
    conn.close()
    return {r[0] for r in rows if r[0]}


def remaining_pdfs() -> list[Path]:
    known = already_ingested_sha256s()
    result = []
    for pdf in sorted(RESUME_DIR.glob("*.pdf")):
        sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
        if sha not in known:
            result.append(pdf)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="批量导入剩余简历到飞书")
    parser.add_argument("--limit", type=int, default=0, help="最多导入数量，0 表示全部")
    parser.add_argument("--delay", type=float, default=1.0, help="每次写入间隔秒数")
    args = parser.parse_args()

    pdfs = remaining_pdfs()
    if args.limit > 0:
        pdfs = pdfs[:args.limit]
    total = len(pdfs)
    print(f"剩余待导入简历：{total}")

    success = 0
    failed = 0
    skipped = 0
    for idx, pdf in enumerate(pdfs, 1):
        print(f"[{idx}/{total}] {pdf.name} ...", end=" ")
        try:
            result = ingest_file(str(pdf), dry_run=False)
            action = result.get("action", "unknown")
            if action == "created":
                print("成功")
                success += 1
            elif action in ("skipped_duplicate", "skipped_duplicate_feishu"):
                print("跳过重复")
                skipped += 1
            else:
                print(f"其他：{action}")
                skipped += 1
        except Exception as exc:
            print(f"失败：{exc}")
            failed += 1
        if idx < total:
            time.sleep(args.delay)

    print(f"\n完成：成功 {success}，跳过 {skipped}，失败 {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
