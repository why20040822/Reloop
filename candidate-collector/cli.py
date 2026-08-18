#!/usr/bin/env python3
"""CLI for ingesting resumes into the TTC Feishu Base.

Examples:
    # Preview what would be written (no Base changes)
    python3 cli.py ingest-file 简历数据/张三.pdf --dry-run

    # Actually create a Feishu Base record
    python3 cli.py ingest-file 简历数据/张三.pdf

    # Ingest raw text
    python3 cli.py ingest-text --title "BOSS在线简历" --source-url "https://..."
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ingestion.pipeline import ingest_file, ingest_text


def cmd_ingest_file(args: argparse.Namespace) -> int:
    path = Path(args.path)
    if not path.is_file():
        print(f"File not found: {path}", file=sys.stderr)
        return 1
    result = ingest_file(
        path,
        dry_run=args.dry_run,
        skip_duplicates=not args.no_dedup,
        check_feishu_exists=args.check_feishu_exists,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


def cmd_ingest_text(args: argparse.Namespace) -> int:
    text = args.text
    if args.file:
        text = Path(args.file).read_text(encoding="utf-8")
    if not text:
        print("No text provided", file=sys.stderr)
        return 1
    result = ingest_text(
        text,
        title=args.title,
        source_url=args.source_url,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TTC resume ingestion CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    file_parser = sub.add_parser("ingest-file", help="Ingest a local resume file")
    file_parser.add_argument("path", help="Path to PDF/DOC/DOCX/image resume")
    file_parser.add_argument("--dry-run", action="store_true", default=True, help="Preview payload without writing")
    file_parser.add_argument("--no-dedup", action="store_true", help="Skip duplicate detection")
    file_parser.add_argument("--check-feishu-exists", action="store_true", help="Query Feishu Base for duplicates")
    file_parser.add_argument("--write", dest="dry_run", action="store_false", help="Actually write to Feishu Base")
    file_parser.set_defaults(func=cmd_ingest_file)

    text_parser = sub.add_parser("ingest-text", help="Ingest raw resume text")
    text_parser.add_argument("--text", default="", help="Resume text (or use --file)")
    text_parser.add_argument("--file", help="Path to text file")
    text_parser.add_argument("--title", default="手动导入", help="Resume title")
    text_parser.add_argument("--source-url", default="", help="Source URL")
    text_parser.add_argument("--dry-run", action="store_true", default=True)
    text_parser.add_argument("--write", dest="dry_run", action="store_false")
    text_parser.set_defaults(func=cmd_ingest_text)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
