#!/usr/bin/env python3
# ONE-OFF (2026-08-03)
# Input: inspect --help and the operator invocation record before running.
# Execution: do not rerun without explicit operator confirmation.

"""Import candidates from a scoring report PDF into the TTC Feishu Base.

The PDF is expected to be a table produced by the TTC talent scoring pipeline,
with one row per candidate containing: rank, name, company, title, age,
years, location, education, score, recommendation, best JD match, evidence,
links and dimension details.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import pdfplumber

REPO_ROOT = Path(__file__).resolve().parents[2]

from reloop.sinks.feishu.feishu_base import FeishuBaseAdapter
from reloop.sinks.feishu.feishu_reader import FeishuBaseReader
from reloop.ingestion.pipeline import init_ingestion_tables, record_fingerprint
from reloop.domain.models import CandidateRecord, Education


def normalize_phone(value: str | None) -> str:
    if not value:
        return ""
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        return digits
    return ""


def normalize_name(value: str | None) -> str:
    return (value or "").strip().lower() if value else ""


def load_target_dedup_index(adapter: FeishuBaseAdapter) -> dict[str, list[dict[str, Any]]]:
    """Build an in-memory dedup index from the target Base."""
    print(f"[INFO] Reading target base for local dedup: {adapter.base_token}/{adapter.table_id}")
    reader = FeishuBaseReader(base_token=adapter.base_token, table_id=adapter.table_id)
    candidate_field_map = {
        spec["name"]: spec.get("candidate_field")
        for spec in adapter.mapping["fields"].values()
    }
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


def _record_to_log(
    record: CandidateRecord,
    fingerprint: str,
    feishu_record_id: str | None = None,
    status: str = "dry_run",
    error: str | None = None,
) -> None:
    """Persist the result of processing a scoring report row to the local ingestion log."""
    import sqlite3
    from contextlib import closing

    DB_PATH = REPO_ROOT / "reloop" / "data" / "candidates.db"
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"candidate": record.model_dump()}
    if error:
        payload["error"] = error
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
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

DEFAULT_PDF_PATH = (
    "/Users/ashley/Library/Containers/com.tencent.xinWeChat/Data/Documents/"
    "xwechat_files/wxid_vokrhy499am222_8b61/temp/RWTemp/2026-07/"
    "38b7028c-2919-4a9b-b6ba-b06397ecf362/评分简历.pdf"
)
DEFAULT_MAPPING_PATH = REPO_ROOT / "reloop" / "config" / "feishu_field_mapping_candidate.json"


def _clean_cell(cell: Any) -> str:
    if cell is None:
        return ""
    return re.sub(r"\s+", " ", str(cell).replace("\n", " ")).strip()


def _extract_rows(pdf_path: Path) -> list[list[str]]:
    rows: list[list[str]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables() or []:
                for row in table:
                    if not row:
                        continue
                    first = _clean_cell(row[0])
                    if not first or first in ("排名", "排 名"):
                        continue
                    # Must start with an integer rank.
                    if not re.match(r"^\d+", first):
                        continue
                    rows.append([_clean_cell(cell) for cell in row])
    return rows


def _parse_education(text: str) -> Education:
    """Best-effort parse '学校·专业·学历' into Education."""
    parts = [p.strip() for p in text.split("·")]
    school = parts[0] if parts else None
    major = parts[1] if len(parts) > 1 else None
    degree = parts[2] if len(parts) > 2 else None
    return Education(school=school, major=major, degree=degree)


def row_to_candidate(row: list[str], source_path: Path) -> CandidateRecord:
    """Convert a scoring report table row to a CandidateRecord."""
    if len(row) < 15:
        raise ValueError(f"Unexpected row length: {len(row)} -> {row}")

    rank = row[0]
    name = row[1]
    company = row[2]
    title = row[3]
    age = row[4]
    years = row[5]
    location = row[6]
    education_text = row[7]
    # row[8] is usually "附件"
    score = row[9]
    recommendation = row[10]
    best_jd = row[11]
    evidence = row[12]
    links = row[13]
    dimensions = row[14]

    # Clean name.
    name = re.sub(r"[（(].*?[)）]", "", name).strip()
    if not name or "未提供" in name:
        name = f"未命名-{rank}"

    education = _parse_education(education_text)

    notes_parts = [
        f"排名: {rank}",
        f"得分: {score}",
        f"推荐: {recommendation}",
        f"最匹配JD: {best_jd}",
        f"最近公司加分: {evidence}",
        f"链接: {links}",
        f"维度详情: {dimensions}",
    ]

    return CandidateRecord(
        name=name,
        current_company=company or None,
        current_title=title or None,
        current_location=location or None,
        education=education,
        school=education.school,
        degree=education.degree,
        expected_title=best_jd or None,
        expected_location=location or None,
        opportunity_intent="是" if recommendation in ("强推", "推荐") else None,
        notes="\n".join(notes_parts),
        raw_text="\n".join(notes_parts),
        source_platform="scoring_report",
        source_type="scoring_report",
        source_url=str(source_path),
        parser_name="scoring_report_parser",
        parser_version="1.0",
        parse_confidence=float(score) / 100.0 if score and score.replace(".", "").isdigit() else None,
    )


def ingest_report(args: argparse.Namespace) -> int:
    pdf_path = Path(args.pdf_path).expanduser().resolve()
    if not pdf_path.is_file():
        print(f"[ERROR] PDF not found: {pdf_path}", file=sys.stderr)
        return 1

    print(f"[INFO] Extracting rows from {pdf_path}")
    rows = _extract_rows(pdf_path)
    print(f"[INFO] Extracted {len(rows)} candidate rows")

    if not rows:
        print("[WARN] No candidates found in PDF", file=sys.stderr)
        return 0

    init_ingestion_tables()

    adapter = FeishuBaseAdapter(mapping_path=args.mapping_path)
    print(f"[INFO] Target Base: {adapter.base_token}/{adapter.table_id}")
    target_index = load_target_dedup_index(adapter)

    stats = {
        "total": len(rows),
        "parsed": 0,
        "created": 0,
        "duplicate": 0,
        "failed": 0,
    }
    report: list[dict[str, Any]] = []

    for idx, row in enumerate(rows, start=1):
        item: dict[str, Any] = {"index": idx, "row": row[:5], "ok": False}
        try:
            record = row_to_candidate(row, pdf_path)
            stats["parsed"] += 1
            item["candidate"] = {
                "name": record.name,
                "company": record.current_company,
                "title": record.current_title,
                "school": record.school,
            }

            fingerprint = record_fingerprint(record)

            # Check target Base duplicate.
            target_dup = is_duplicate_in_target_index(record, target_index)
            if target_dup:
                stats["duplicate"] += 1
                item["ok"] = True
                item["action"] = "skipped_target_duplicate"
                _record_to_log(record, fingerprint, status="skipped_target_duplicate")
                print(f"[{idx}/{len(rows)}] SKIP target dup ({target_dup['by']}): {record.name}")
                report.append(item)
                continue

            if args.write:
                result = adapter.create_record(record)
                record_id = _extract_record_id(result)
                stats["created"] += 1
                item["ok"] = True
                item["action"] = "created"
                item["feishu_record_id"] = record_id
                _record_to_log(record, fingerprint, feishu_record_id=record_id, status="success")
                print(f"[{idx}/{len(rows)}] CREATED {record_id}: {record.name}")
            else:
                payload = adapter.dry_run(record)
                item["ok"] = True
                item["action"] = "dry_run"
                item["feishu_payload"] = payload
                _record_to_log(record, fingerprint, status="dry_run")
                print(f"[{idx}/{len(rows)}] DRY-RUN: {record.name}")

        except Exception as exc:
            stats["failed"] += 1
            item["error"] = str(exc)
            item["action"] = "failed"
            print(f"[{idx}/{len(rows)}] FAIL: row {row[:5]} -> {exc}", file=sys.stderr)

        report.append(item)

        if args.write and idx < len(rows):
            time.sleep(5)

    # Save report.
    output_dir = REPO_ROOT / "data" / "ingest_reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    mode = "write" if args.write else "dry_run"
    report_path = output_dir / f"ingest_scoring_report_{mode}_{int(time.time())}.json"
    report_path.write_text(
        json.dumps(
            {"meta": {"pdf_path": str(pdf_path), "write_mode": args.write}, "stats": stats, "report": report},
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    print("\n" + "=" * 60)
    print(f"Scoring report ingest complete (mode={'WRITE' if args.write else 'DRY-RUN'})")
    print(f"  Total rows:  {stats['total']}")
    print(f"  Parsed:      {stats['parsed']}")
    print(f"  Created:     {stats['created']}")
    print(f"  Duplicate:   {stats['duplicate']}")
    print(f"  Failed:      {stats['failed']}")
    print(f"  Report:      {report_path}")
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
    parser = argparse.ArgumentParser(description="Import scoring report candidates into Feishu Base")
    parser.add_argument("--pdf-path", default=str(DEFAULT_PDF_PATH), help="Path to scoring report PDF")
    parser.add_argument("--mapping-path", default=str(DEFAULT_MAPPING_PATH), help="Feishu field mapping JSON")
    parser.add_argument("--write", action="store_true", help="Actually create records")
    args = parser.parse_args(argv)
    return ingest_report(args)


if __name__ == "__main__":
    raise SystemExit(main())
