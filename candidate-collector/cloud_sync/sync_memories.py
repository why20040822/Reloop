"""Import historical conversation/memory data into cloud RDS PostgreSQL.

Supports:
    - A directory of .txt / .md / .json files (one conversation per file).
    - A single JSON file containing a list of conversation records.

Usage:
    cd /Users/ashley/Downloads/ttc的交易系统/candidate-collector
    python cloud_sync/sync_memories \
        --project ttc \
        --source-dir /path/to/conversations \
        --source claude

Environment:
    RDS_HOST, RDS_PORT, RDS_DB, RDS_USER, RDS_PASSWORD
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .client import CloudSyncClient
from .config import rds_configured


def _source_record_id(project: str, source: str, rel_path: str) -> str:
    """Stable idempotency key based on project + source + relative path."""
    raw = f"{project}:{source}:{rel_path}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _read_text_file(path: Path) -> dict | None:
    """Read a plain text/markdown file as a memory record."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        print(f"[warn] cannot read {path}: {exc}")
        return None

    if not text.strip():
        return None

    return {
        "content_type": "chat" if "chat" in path.name.lower() else "doc",
        "content_text": text,
        "metadata": {
            "filename": path.name,
            "size": len(text),
        },
    }


def _read_json_file(path: Path) -> list[dict]:
    """Read a JSON file and return memory records.

    Supports two shapes:
      1. A single object: {"content_text": "...", "content_type": "chat", ...}
      2. A list of objects.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[warn] cannot parse JSON {path}: {exc}")
        return []

    if isinstance(data, dict):
        data = [data]

    records: list[dict] = []
    for idx, item in enumerate(data):
        if not isinstance(item, dict):
            continue
        text = item.get("content_text") or item.get("text") or item.get("conversation")
        if not text:
            continue
        records.append({
            "content_type": item.get("content_type", "chat"),
            "content_text": text,
            "metadata": item.get("metadata", {}),
            "source_record_id": item.get("source_record_id") or f"{path.name}:{idx}",
        })
    return records


def _scan_directory(source_dir: Path, project: str, source: str) -> list[dict]:
    """Recursively scan a directory and convert files to memory rows."""
    rows: list[dict] = []
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file():
            continue

        rel = path.relative_to(source_dir).as_posix()
        records: list[dict] = []

        if path.suffix.lower() == ".json":
            records = _read_json_file(path)
            for r in records:
                r.setdefault("source_record_id", _source_record_id(project, source, f"{rel}:{r.get('source_record_id', '0')}"))
        elif path.suffix.lower() in (".txt", ".md", ".markdown"):
            record = _read_text_file(path)
            if record:
                record["source_record_id"] = _source_record_id(project, source, rel)
                records = [record]
        else:
            continue

        for r in records:
            r["project_id"] = project
            r["source"] = source
            rows.append(r)

    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="导入历史对话/记忆到云端 RDS")
    parser.add_argument("--project", required=True, help="项目标识，例如 ttc")
    parser.add_argument("--source-dir", required=True, type=Path, help="对话文件目录")
    parser.add_argument("--source", default="claude", help="来源标识：claude / opencode / codex / feishu")
    parser.add_argument("--content-type", default="chat", help="默认 content_type")
    parser.add_argument("--dry-run", action="store_true", help="预览但不写入")
    parser.add_argument("--ensure-schema", action="store_true", help="同步前先创建表")
    args = parser.parse_args()

    if not rds_configured():
        print("错误：RDS 环境变量未配置。请设置 RDS_HOST, RDS_DB, RDS_USER, RDS_PASSWORD。")
        return 1

    if not args.source_dir.exists():
        print(f"错误：目录不存在 {args.source_dir}")
        return 1

    client = CloudSyncClient()
    if args.dry_run:
        client.dry_run = True

    if args.ensure_schema:
        client.ensure_schema()

    rows = _scan_directory(args.source_dir, args.project, args.source)
    # Apply default content_type to records that didn't specify one.
    for r in rows:
        if not r.get("content_type"):
            r["content_type"] = args.content_type
        r.setdefault("metadata", {})

    print(f"扫描到记忆记录：{len(rows)}")
    if not rows:
        return 0

    stats = client.upsert_memories(rows)
    print(f"同步完成：新增 {stats['inserted']}，更新 {stats['updated']}，错误 {stats['errors']}")
    print(f"云端记忆总数：{client.count_memories()}")
    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
