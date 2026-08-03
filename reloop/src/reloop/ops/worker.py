"""One-shot outbox worker used by cron/daemon wrappers."""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from contextlib import closing
from typing import Any

from reloop.config import DB_PATH
from reloop.domain.models import CandidateRecord
from reloop.ingestion.delivery import DeliveryStore, deliver_once
from reloop.sinks.feishu.feishu_base import FeishuBaseAdapter
from reloop.sinks.rds.client import upsert_candidate

logger = logging.getLogger(__name__)


class _RdsSink:
    def upsert_candidate(self, record: CandidateRecord) -> dict[str, Any]:
        return upsert_candidate(record)


def _sync_ingestion_log(result: Any) -> None:
    """Mirror delivery state for the legacy review/quality views."""

    if result.cloud_status != "success":
        status = "failed"
    elif result.feishu_status == "success":
        status = "success"
    elif result.feishu_status == "failed":
        status = "failed"
    else:
        status = "blocked"
    try:
        with closing(sqlite3.connect(DB_PATH)) as connection:
            connection.execute(
                """UPDATE ingestion_log SET
                   feishu_record_id=?, feishu_write_status=?, error_message=?,
                   updated_at=datetime('now') WHERE fingerprint=?""",
                (result.feishu_record_id, status, result.last_error, result.fingerprint),
            )
            connection.commit()
    except sqlite3.Error:
        logger.exception("failed to mirror delivery state for job_id=%s", result.id)


def run_once(*, limit: int = 10, store: DeliveryStore | None = None) -> list[dict[str, Any]]:
    outbox = store or DeliveryStore()
    rds = _RdsSink()
    feishu = FeishuBaseAdapter()
    results = []
    for job in outbox.claim(limit=limit):
        result = deliver_once(job, outbox, rds, feishu)
        _sync_ingestion_log(result)
        results.append({
            "job_id": result.id,
            "fingerprint": result.fingerprint,
            "local_status": result.local_status,
            "cloud_status": result.cloud_status,
            "feishu_status": result.feishu_status,
            "last_error": result.last_error,
        })
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reloop ingestion outbox worker")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args(argv)
    print(json.dumps(run_once(limit=args.limit), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
