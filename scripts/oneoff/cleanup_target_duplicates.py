#!/usr/bin/env python3
# ONE-OFF (2026-08-03)
# Input: inspect --help and the operator invocation record before running.
# Execution: do not rerun without explicit operator confirmation.

"""Clean up duplicate records in the target Base after test imports.

Keeps the oldest record for each name and deletes newer duplicates.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import argparse

BASE_TOKEN = "DIIdbR2c8ax8bTsZoNKcnX6enSe"
TABLE_ID = "tblWFuBQrPmllE9W"


def _run_cli(*args: str) -> dict[str, Any]:
    result = subprocess.run(
        ["lark-cli", "base", *args, "--format", "json", "--as", "user"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout)
    return json.loads(result.stdout)


def list_all_records(base_token: str, table_id: str) -> list[dict[str, Any]]:
    """Return all records with record_id, name and created_at."""
    records: list[dict[str, Any]] = []
    offset = 0
    page_size = 200
    while True:
        resp = _run_cli(
            "+record-list",
            "--base-token", base_token,
            "--table-id", table_id,
            "--field-id", "fldzfT0qEZ",      # 姓名
            "--field-id", "fld0XiaNkt",      # 创建时间
            "--limit", str(page_size),
            "--offset", str(offset),
        )
        data = resp.get("data", {})
        rows = data.get("data", [])
        ids = data.get("record_id_list", [])
        if not rows:
            break
        for idx, row in enumerate(rows):
            record_id = ids[idx] if idx < len(ids) else None
            name = row[0] if row else None
            created_at = row[1] if len(row) > 1 else None
            records.append({
                "record_id": record_id,
                "name": name,
                "created_at": created_at,
            })
        offset += len(rows)
        if len(rows) < page_size:
            break
    return records


def delete_records(base_token: str, table_id: str, record_ids: list[str]) -> None:
    if not record_ids:
        return
    ids_args = []
    for rid in record_ids:
        ids_args.extend(["--record-id", rid])
    resp = _run_cli(
        "+record-delete",
        "--base-token", base_token,
        "--table-id", table_id,
        *ids_args,
        "--yes",
    )
    print("Deleted:", resp.get("data", {}).get("record_id_list"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean duplicates in a Feishu Base table")
    parser.add_argument("--base-token", default=BASE_TOKEN)
    parser.add_argument("--table-id", default=TABLE_ID)
    args = parser.parse_args()

    records = list_all_records(args.base_token, args.table_id)
    print(f"Total records: {len(records)}")

    # Group by name.
    by_name: dict[str, list[dict[str, Any]]] = {}
    for rec in records:
        name = rec.get("name") or ""
        if not name:
            continue
        by_name.setdefault(name, []).append(rec)

    to_delete: list[str] = []
    for name, group in by_name.items():
        if len(group) <= 1:
            continue
        # Keep oldest created_at; fall back to record_id ordering.
        sorted_group = sorted(
            group,
            key=lambda r: (r.get("created_at") or "", r.get("record_id") or ""),
        )
        print(f"{name}: {len(group)} duplicates, keeping {sorted_group[0]['record_id']}")
        for rec in sorted_group[1:]:
            rid = rec.get("record_id")
            if rid:
                to_delete.append(rid)

    if not to_delete:
        print("No duplicates found.")
        return 0

    print(f"\nDeleting {len(to_delete)} duplicate records...")
    delete_records(args.base_token, args.table_id, to_delete)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
