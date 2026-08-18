"""Read-only Feishu (Lark) Bitable adapter for historical talent bases.

This module is intentionally read-only: it fetches existing records from a
source Base so the ingestion pipeline can deduplicate local resumes before
writing to a separate target Base.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any


class FeishuBaseReader:
    """Read-only reader for a Feishu Bitable.

    Uses ``lark-cli base +record-list`` and ``+field-list`` under the hood,
    which reuses the user's existing lark-cli authentication.
    """

    def __init__(
        self,
        base_token: str,
        table_id: str,
        view_id: str | None = None,
    ):
        self.base_token = base_token
        self.table_id = table_id
        self.view_id = view_id

    @staticmethod
    def _run_cli(*args: str) -> dict[str, Any]:
        cmd = ["lark-cli", "base", *args, "--as", "user", "--format", "json"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"lark-cli failed: {result.stderr or result.stdout}")
        stdout = result.stdout.strip()
        if stdout.startswith("```"):
            lines = stdout.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            stdout = "\n".join(lines)
        if not stdout:
            return {}
        return json.loads(stdout)

    def list_fields(self) -> list[dict[str, Any]]:
        resp = self._run_cli(
            "+field-list",
            "--base-token", self.base_token,
            "--table-id", self.table_id,
        )
        return resp.get("data", {}).get("fields", [])

    def list_records(
        self,
        page_size: int = 200,
        field_ids: list[str] | None = None,
        ignore_view: bool = False,
    ) -> list[dict[str, Any]]:
        """Read all records and return them as a list of field-name dicts.

        The lark-cli JSON format returns records as arrays ordered by the
        table's field order, so we first fetch the field list to map positions
        back to names.
        """
        fields = self.list_fields()
        if field_ids:
            fields = [f for f in fields if f["id"] in field_ids or f["name"] in field_ids]
        field_names = [f["name"] for f in fields]

        records: list[dict[str, Any]] = []
        offset = 0
        while True:
            args = [
                "+record-list",
                "--base-token", self.base_token,
                "--table-id", self.table_id,
                "--limit", str(page_size),
                "--offset", str(offset),
            ]
            if self.view_id and not ignore_view:
                args.extend(["--view-id", self.view_id])
            for fid in (field_ids or []):
                args.extend(["--field-id", fid])

            resp = self._run_cli(*args)
            data = resp.get("data", {}) or {}
            rows = data.get("data", [])
            if not rows:
                break

            for row in rows:
                if not isinstance(row, list):
                    continue
                record: dict[str, Any] = {}
                for idx, name in enumerate(field_names):
                    if idx < len(row):
                        record[name] = row[idx]
                    else:
                        record[name] = None
                records.append(record)

            # lark-cli returns arrays when using --field-id projection and a flat
            # list otherwise; either way, len(rows) tells us how many we got.
            offset += len(rows)
            if len(rows) < page_size:
                break

        return records

    def build_dedup_index(
        self,
    ) -> dict[str, list[dict[str, Any]]]:
        """Return a deduplication index keyed by phone and name+company.

        The index maps:
          - ``phone:<digits>`` -> list of matching records
          - ``name_company:<name>|<company>`` -> list of matching records

        Note: We intentionally do not pass ``self.view_id`` here because the
        historical source view is a form view and does not support record_query.
        """
        # Read only the fields we need for dedup.
        records = self.list_records(field_ids=["姓名", "电话", "公司", "就职岗位"], ignore_view=True)
        index: dict[str, list[dict[str, Any]]] = {}

        def add(key: str, record: dict[str, Any]) -> None:
            index.setdefault(key, []).append(record)

        for rec in records:
            name = _norm(str(rec.get("姓名") or ""))
            phone = _digits(str(rec.get("电话") or ""))
            company = _norm(str(rec.get("公司") or ""))
            title = _norm(str(rec.get("就职岗位") or ""))

            if phone:
                add(f"phone:{phone}", rec)
            if name and company:
                add(f"name_company:{name}|{company}", rec)
            elif name and title:
                # Fallback: name + title is weaker but still useful.
                add(f"name_title:{name}|{title}", rec)

        return index


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def _digits(value: str) -> str:
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        return digits
    return ""


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Read-only Feishu Base record reader")
    parser.add_argument("--base-token", required=True)
    parser.add_argument("--table-id", required=True)
    parser.add_argument("--view-id", default=None)
    parser.add_argument("--output", default=None, help="JSON output path")
    args = parser.parse_args()

    reader = FeishuBaseReader(args.base_token, args.table_id, args.view_id)
    records = reader.list_records()
    print(f"Read {len(records)} records")
    if args.output:
        Path(args.output).write_text(
            json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"Saved to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
