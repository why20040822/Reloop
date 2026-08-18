"""Recover phone/email for existing candidate records.

Usage:
    cd candidate-collector
    python3 scripts/recover_phones.py

The script:
1. Re-extracts phone/email from raw_text for every candidate.
2. Falls back to ingestion_log.phone when raw_text extraction fails.
3. Reports counts before/after.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "candidates.db"

PHONE_RE = __import__("re").compile(r"(?<![\d])1[3-9]\d{9}(?![\d])")
EMAIL_RE = __import__("re").compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


def extract_phone(text: str) -> str:
    match = PHONE_RE.search(text or "")
    return match.group(0) if match else ""


def extract_email(text: str) -> str:
    match = EMAIL_RE.search(text or "")
    return match.group(0) if match else ""


def main() -> int:
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        return 1

    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row

        # Ensure columns exist.
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(candidates)").fetchall()}
        if "phone" not in cols:
            conn.execute("ALTER TABLE candidates ADD COLUMN phone TEXT NOT NULL DEFAULT ''")
        if "email" not in cols:
            conn.execute("ALTER TABLE candidates ADD COLUMN email TEXT NOT NULL DEFAULT ''")
        conn.commit()

        # Build lookup from ingestion_log.
        log_phones: dict[str, str] = {}
        for row in conn.execute("SELECT fingerprint, phone FROM ingestion_log WHERE phone IS NOT NULL AND phone != ''").fetchall():
            log_phones[row["fingerprint"]] = row["phone"]

        rows = conn.execute("SELECT id, fingerprint, raw_text, phone, email FROM candidates").fetchall()
        updated = 0
        unchanged = 0
        for row in rows:
            raw = row["raw_text"] or ""
            phone = extract_phone(raw) or log_phones.get(row["fingerprint"], "")
            email = extract_email(raw)
            if phone != row["phone"] or email != row["email"]:
                conn.execute(
                    "UPDATE candidates SET phone=?, email=? WHERE id=?",
                    (phone, email, row["id"]),
                )
                updated += 1
            else:
                unchanged += 1
        conn.commit()

    print(f"Updated: {updated}, Unchanged: {unchanged}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
