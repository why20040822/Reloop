#!/usr/bin/env python3
# ONE-OFF (2026-08-03)
# Input: inspect --help and the operator invocation record before running.
# Execution: do not rerun without explicit operator confirmation.

"""
导入数据定期报告脚本。

生成本地 candidates 表的导入统计，保存到 data/bulk_import_resumes/periodic_report.json。
可由 CronCreate 定期调用，也可手动运行。
"""

import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

from ttc_daemon import db


def generate_report() -> dict:
    db.init_db()
    conn = db.get_conn()
    try:
        total = conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
        by_source = conn.execute("""
            SELECT
                CASE
                    WHEN json_extract(source_types, '$[0]') IS NULL THEN 'unknown'
                    ELSE json_extract(source_types, '$[0]')
                END as src,
                COUNT(*) as cnt
            FROM candidates
            GROUP BY src
        """).fetchall()

        today = datetime.now().strftime('%Y-%m-%d')
        today_count = conn.execute(
            "SELECT COUNT(*) FROM candidates WHERE date(created_at) = ?",
            (today,)
        ).fetchone()[0]

        last_24h = conn.execute(
            "SELECT COUNT(*) FROM candidates WHERE created_at >= datetime('now', '-1 day')"
        ).fetchone()[0]

        with_pdf = conn.execute(
            "SELECT COUNT(*) FROM candidates WHERE original_attachment_path IS NOT NULL AND original_attachment_path != ''"
        ).fetchone()[0]

        recent = conn.execute(
            "SELECT id, name, source_types, original_attachment_path, created_at FROM candidates ORDER BY created_at DESC LIMIT 10"
        ).fetchall()
    finally:
        conn.close()

    return {
        "generated_at": datetime.now().isoformat(),
        "total_candidates": total,
        "today_imported": today_count,
        "last_24h": last_24h,
        "with_pdf_attachment": with_pdf,
        "by_source": [{"source": r["src"], "count": r["cnt"]} for r in by_source],
        "recent": [
            {"id": r["id"], "name": r["name"], "source_types": r["source_types"],
             "has_pdf": bool(r["original_attachment_path"]), "created_at": r["created_at"]}
            for r in recent
        ],
    }


def main() -> int:
    report = generate_report()
    out_path = REPO_ROOT / "data" / "bulk_import_resumes" / "periodic_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    print(f"\n报告已保存: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
