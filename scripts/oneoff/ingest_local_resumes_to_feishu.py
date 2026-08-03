#!/usr/bin/env python3
# ONE-OFF (2026-08-03)
# Input: inspect --help and the operator invocation record before running.
# Execution: do not rerun without explicit operator confirmation.

"""Batch ingest local resumes into the TTC Feishu Base with historical dedup.

Workflow:
  1. Read the source talent base (historical read-only Kimi table).
  2. Build a deduplication index from name+company / phone.
  3. Scan a local directory of resumes.
  4. Parse each resume with the unified parser.
  5. Skip duplicates found in the source base.
  6. Dry-run preview (default) or write to the configured target Base.

Examples:
    # Preview what would be imported without touching the Base
    python scripts/oneoff/ingest_local_resumes_to_feishu.py --resume-dir ../简历数据 --limit 10

    # Actually import after preview looks good
    python scripts/oneoff/ingest_local_resumes_to_feishu.py --resume-dir ../简历数据 --write --limit 50
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path
from typing import Any

from reloop.sinks.feishu.feishu_base import FeishuBaseAdapter
from reloop.sinks.feishu.feishu_reader import FeishuBaseReader
from reloop.ingestion.delivery import DeliveryStore
from reloop.ingestion.pipeline import DB_PATH, init_ingestion_tables, local_duplicate_exists, record_fingerprint
from reloop.domain.models import CandidateRecord
from reloop.parsing.unified_parser import parse_resume_file

REPO_ROOT = Path(__file__).resolve().parents[2]


DEFAULT_SOURCE_BASE_TOKEN = os.getenv("TTC_SOURCE_BASE_TOKEN", "")
DEFAULT_SOURCE_TABLE_ID = "tblyT3bebRJsyHar"
DEFAULT_SOURCE_VIEW_ID = "vewirJbTf2"

DEFAULT_RESUME_DIR = REPO_ROOT / "简历数据"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "ingest_reports"

SUPPORTED_SUFFIXES = {".pdf", ".doc", ".docx", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"}


def _db_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _record_to_log(
    record: CandidateRecord,
    fingerprint: str,
    feishu_record_id: str | None = None,
    status: str = "dry_run",
    error: str | None = None,
    job_id: int | None = None,
) -> None:
    """Persist the result of processing a resume to the local ingestion log."""
    payload: dict[str, Any] = {"candidate": record.model_dump()}
    if job_id is not None:
        payload["job_id"] = job_id
    if error:
        payload["error"] = error
    with closing(_db_conn()) as conn:
        conn.execute(
            """
            INSERT INTO ingestion_log (
                fingerprint, attachment_sha256, phone, name, current_company,
                current_title, feishu_record_id, feishu_write_status, review_status,
                error_message, dry_run_payload, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            ON CONFLICT(fingerprint) DO UPDATE SET
                phone=excluded.phone,
                name=excluded.name,
                current_company=excluded.current_company,
                current_title=excluded.current_title,
                feishu_record_id=excluded.feishu_record_id,
                feishu_write_status=excluded.feishu_write_status,
                review_status=excluded.review_status,
                error_message=excluded.error_message,
                dry_run_payload=excluded.dry_run_payload,
                updated_at=datetime('now')
            """,
            (
                fingerprint,
                record.attachment_sha256,
                record.phone,
                record.name,
                record.current_company,
                record.current_title,
                feishu_record_id,
                status,
                "pending",
                error,
                json.dumps(payload, ensure_ascii=False, default=str),
            ),
        )
        conn.commit()


def find_resume_files(root: Path, limit: int = 0, offset: int = 0) -> list[Path]:
    """Recursively find supported resume files under root."""
    if root.is_file():
        return [root]
    files = [
        p for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES
    ]
    files = sorted(set(files), key=lambda p: str(p))
    if offset > 0:
        files = files[offset:]
    if limit > 0:
        files = files[:limit]
    return files


def normalize_phone(value: str | None) -> str:
    if not value:
        return ""
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        return digits
    return ""


def normalize_name(value: str | None) -> str:
    return (value or "").strip().lower() if value else ""


def is_duplicate_in_base(record: CandidateRecord, dedup_index: dict[str, list[dict[str, Any]]]) -> dict[str, Any] | None:
    """Return the matching base record if this candidate already exists."""
    phone = normalize_phone(record.phone)
    if phone:
        matches = dedup_index.get(f"phone:{phone}")
        if matches:
            return {"by": "phone", "phone": phone, "record": matches[0]}

    name = normalize_name(record.name)
    company = normalize_name(record.current_company)
    title = normalize_name(record.current_title)

    if name and company:
        matches = dedup_index.get(f"name_company:{name}|{company}")
        if matches:
            return {"by": "name_company", "name": name, "company": company, "record": matches[0]}

    if name and title:
        matches = dedup_index.get(f"name_title:{name}|{title}")
        if matches:
            return {"by": "name_title", "name": name, "title": title, "record": matches[0]}

    return None


def load_target_dedup_index(adapter: FeishuBaseAdapter) -> dict[str, list[dict[str, Any]]]:
    """Build an in-memory dedup index from the target Base.

    This avoids a Feishu search API call for every resume, which frequently
    triggers rate limits on large imports.
    """
    print(f"[INFO] Reading target base for local dedup: {adapter.base_token}/{adapter.table_id}")
    reader = FeishuBaseReader(base_token=adapter.base_token, table_id=adapter.table_id)
    candidate_field_map = {
        spec["name"]: spec.get("candidate_field")
        for spec in adapter.mapping["fields"].values()
    }

    # Determine which target fields correspond to name/phone/company.
    name_field = next(
        (name for name, cf in candidate_field_map.items() if cf == "name"),
        None,
    )
    phone_field = next(
        (name for name, cf in candidate_field_map.items() if cf == "phone"),
        None,
    )
    company_field = next(
        (name for name, cf in candidate_field_map.items() if cf == "current_company"),
        None,
    )
    title_field = next(
        (name for name, cf in candidate_field_map.items() if cf == "current_title"),
        None,
    )

    selected_fields = [f for f in [name_field, phone_field, company_field, title_field] if f]
    if not selected_fields:
        return {}

    records = reader.list_records(field_ids=selected_fields, ignore_view=True)
    index: dict[str, list[dict[str, Any]]] = {}

    def add(key: str, record: dict[str, Any]) -> None:
        index.setdefault(key, []).append(record)

    for rec in records:
        name = normalize_name(rec.get(name_field))
        phone = normalize_phone(rec.get(phone_field))
        company = normalize_name(rec.get(company_field))
        title = normalize_name(rec.get(title_field))

        if phone:
            add(f"phone:{phone}", rec)
        if name and company:
            add(f"name_company:{name}|{company}", rec)
        elif name and title:
            add(f"name_title:{name}|{title}", rec)
        if name:
            add(f"name:{name}", rec)

    print(f"[INFO] Built target dedup index with {len(index)} keys from {len(records)} records")
    return index


def is_duplicate_in_target_index(
    record: CandidateRecord,
    index: dict[str, list[dict[str, Any]]],
) -> dict[str, Any] | None:
    """Return the matching target record if this candidate already exists locally."""
    phone = normalize_phone(record.phone)
    if phone:
        matches = index.get(f"phone:{phone}")
        if matches:
            return {"by": "phone", "phone": phone, "record": matches[0]}

    name = normalize_name(record.name)
    company = normalize_name(record.current_company)
    title = normalize_name(record.current_title)

    if name and company:
        matches = index.get(f"name_company:{name}|{company}")
        if matches:
            return {"by": "name_company", "name": name, "company": company, "record": matches[0]}

    if name and title:
        matches = index.get(f"name_title:{name}|{title}")
        if matches:
            return {"by": "name_title", "name": name, "title": title, "record": matches[0]}

    if name:
        matches = index.get(f"name:{name}")
        if matches:
            return {"by": "name", "name": name, "record": matches[0]}

    return None


def load_dedup_index(
    base_token: str,
    table_id: str,
    view_id: str | None,
) -> dict[str, list[dict[str, Any]]]:
    print(f"[INFO] Reading source base for dedup: {base_token}/{table_id} (view={view_id})")
    reader = FeishuBaseReader(base_token=base_token, table_id=table_id, view_id=view_id)
    index = reader.build_dedup_index()
    print(f"[INFO] Built dedup index with {len(index)} keys")
    return index


def ingest_batch(args: argparse.Namespace) -> int:
    resume_dir = Path(args.resume_dir).expanduser().resolve()
    if not resume_dir.exists():
        print(f"[ERROR] Resume directory not found: {resume_dir}", file=sys.stderr)
        return 1

    files = find_resume_files(resume_dir, args.limit, args.offset)
    if not files:
        print(f"[WARN] No resume files found under {resume_dir}", file=sys.stderr)
        return 0

    print(f"[INFO] Found {len(files)} resume files to process")

    # Initialize local ingestion tables for persistence/dry-run records.
    init_ingestion_tables()

    # Load historical dedup index from the read-only source base.
    dedup_index = load_dedup_index(
        base_token=args.source_base_token,
        table_id=args.source_table_id,
        view_id=args.source_view_id,
    )

    # Target Base writer: use CLI override if provided, otherwise config file.
    mapping_path = Path(args.target_mapping_path) if args.target_mapping_path else None
    adapter = FeishuBaseAdapter(
        mapping_path=mapping_path,
        base_token=args.target_base_token,
        table_id=args.target_table_id,
    )
    print(f"[INFO] Target Base: {adapter.base_token}/{adapter.table_id}")

    # Load target Base dedup index into memory to avoid search API rate limits.
    target_dedup_index = load_target_dedup_index(adapter)

    stats = {
        "total": len(files),
        "parsed": 0,
        "duplicate": 0,
        "local_duplicate": 0,
        "failed": 0,
        "created": 0,
        "dry_run": 0,
    }
    report: list[dict[str, Any]] = []
    start = time.time()

    for idx, path in enumerate(files, start=1):
        item: dict[str, Any] = {
            "index": idx,
            "path": str(path),
            "ok": False,
            "action": None,
        }
        fingerprint = ""
        try:
            record = parse_resume_file(path)
            fingerprint = record_fingerprint(record)
            stats["parsed"] += 1
            item["candidate"] = {
                "name": record.name,
                "phone": record.phone,
                "company": record.current_company,
                "title": record.current_title,
                "school": record.school,
            }

            # Local SQLite dedup.
            # In dry-run mode, skip anything already processed to avoid noise.
            # In write mode, only skip records that were successfully written
            # (or confirmed as target duplicates); dry-run / failed / source-dup
            # entries are allowed to be re-processed.
            local_dup = local_duplicate_exists(record)
            terminal_statuses = {"success", "skipped_target_duplicate"}
            if local_dup and (
                not args.write
                or local_dup.get("feishu_write_status") in terminal_statuses
            ):
                stats["local_duplicate"] += 1
                item["ok"] = True
                item["action"] = "skipped_local_duplicate"
                item["duplicate"] = local_dup.get("fingerprint")
                # Persist local skip so the next run does not re-scan this file.
                _record_to_log(record, fingerprint, status="skipped_local_duplicate")
                print(f"[{idx}/{len(files)}] SKIP local dup: {path.name}")
                report.append(item)
                continue

            # Source Base dedup (historical Kimi table).
            base_dup = is_duplicate_in_base(record, dedup_index)
            if base_dup:
                stats["duplicate"] += 1
                item["ok"] = True
                item["action"] = "skipped_source_duplicate"
                item["duplicate_by"] = base_dup["by"]
                item["duplicate_record"] = base_dup["record"]
                # Persist the skip so we do not re-check it every run.
                _record_to_log(record, fingerprint, status="skipped_source_duplicate")
                print(f"[{idx}/{len(files)}] SKIP source dup ({base_dup['by']}): {path.name}")
                report.append(item)
                continue

            if args.write:
                target_dup = is_duplicate_in_target_index(record, target_dedup_index)
                if not target_dup and args.target_check_api:
                    target_dup = adapter.record_exists(record)
                if target_dup:
                    stats["duplicate"] += 1
                    item["ok"] = True
                    item["action"] = "skipped_target_duplicate"
                    _record_to_log(record, fingerprint, status="skipped_target_duplicate")
                    print(f"[{idx}/{len(files)}] SKIP target dup ({target_dup.get('by')}): {path.name}")
                    report.append(item)
                    continue
                job = DeliveryStore().enqueue(record, fingerprint=fingerprint)
                stats["created"] += 1
                item["ok"] = True
                item["action"] = "queued"
                item["job_id"] = job.id
                _record_to_log(record, fingerprint, status="blocked", job_id=job.id)
                print(f"[{idx}/{len(files)}] QUEUED job {job.id}: {path.name}")
            else:
                payload = adapter.dry_run(record)
                stats["dry_run"] += 1
                item["ok"] = True
                item["action"] = "dry_run"
                item["feishu_payload"] = payload
                _record_to_log(record, fingerprint, status="dry_run")
                print(f"[{idx}/{len(files)}] DRY-RUN: {path.name}")

        except Exception as exc:
            stats["failed"] += 1
            item["error"] = str(exc)
            item["action"] = "failed"
            if fingerprint:
                try:
                    _record_to_log(record, fingerprint, status="failed", error=str(exc))
                except Exception:
                    pass
            print(f"[{idx}/{len(files)}] FAIL: {path.name} -> {exc}", file=sys.stderr)

        report.append(item)

        # Throttle Feishu API calls to avoid rate limits and network congestion.
        if args.write and idx < len(files):
            time.sleep(5)

    elapsed = round(time.time() - start, 2)

    summary = {
        "meta": {
            "resume_dir": str(resume_dir),
            "source_base_token": args.source_base_token,
            "source_table_id": args.source_table_id,
            "source_view_id": args.source_view_id,
            "target_base_token": adapter.base_token,
            "target_table_id": adapter.table_id,
            "write_mode": args.write,
            "elapsed_seconds": elapsed,
        },
        "stats": stats,
        "report": report,
    }

    DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    mode = "write" if args.write else "dry_run"
    report_path = DEFAULT_OUTPUT_DIR / f"ingest_local_{mode}_{int(time.time())}.json"
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    print("\n" + "=" * 60)
    print(f"Batch ingest complete (mode={'WRITE' if args.write else 'DRY-RUN'})")
    print(f"  Total files:   {stats['total']}")
    print(f"  Parsed:        {stats['parsed']}")
    print(f"  Created:       {stats['created']}")
    print(f"  Dry-run:       {stats['dry_run']}")
    print(f"  Source dup:    {stats['duplicate']}")
    print(f"  Local dup:     {stats['local_duplicate']}")
    print(f"  Failed:        {stats['failed']}")
    print(f"  Elapsed:       {elapsed}s")
    print(f"  Report:        {report_path}")
    print("=" * 60)
    return 0


def _extract_record_id(resp: dict[str, Any]) -> str | None:
    data = resp.get("data", {})
    if isinstance(data, dict):
        record_id_list = data.get("record_id_list")
        if isinstance(record_id_list, list) and record_id_list:
            return record_id_list[0]
        records = data.get("records", [])
        if records and records[0].get("record_id"):
            return records[0]["record_id"]
        return data.get("record_id")
    if isinstance(data, list) and data:
        return data[0].get("record_id")
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Batch ingest local resumes into TTC Feishu Base",
    )
    parser.add_argument("--resume-dir", default=str(DEFAULT_RESUME_DIR), help="Local resume directory")
    parser.add_argument("--limit", type=int, default=0, help="Max files to process (0 = unlimited)")
    parser.add_argument("--offset", type=int, default=0, help="Skip first N files")
    parser.add_argument(
        "--source-base-token",
        default=DEFAULT_SOURCE_BASE_TOKEN,
        help="Read-only source Base token for historical dedup",
    )
    parser.add_argument(
        "--source-table-id",
        default=DEFAULT_SOURCE_TABLE_ID,
        help="Read-only source table ID",
    )
    parser.add_argument(
        "--source-view-id",
        default=DEFAULT_SOURCE_VIEW_ID,
        help="Read-only source view ID",
    )
    parser.add_argument("--write", action="store_true", help="Actually create records in target Base")
    parser.add_argument("--no-local-dedup", action="store_true", help="Skip local SQLite dedup")
    parser.add_argument(
        "--target-check-api",
        action="store_true",
        help="Also call Feishu search API when local target index does not find a duplicate",
    )
    parser.add_argument(
        "--target-base-token",
        default=None,
        help="Override target Base token (default: from field mapping config)",
    )
    parser.add_argument(
        "--target-table-id",
        default=None,
        help="Override target table ID (default: from field mapping config)",
    )
    parser.add_argument(
        "--target-mapping-path",
        default=None,
        help="Path to a custom Feishu field mapping JSON for the target table",
    )
    args = parser.parse_args(argv)
    return ingest_batch(args)


if __name__ == "__main__":
    raise SystemExit(main())
