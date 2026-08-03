"""One-shot outbox worker used by cron/daemon wrappers."""

from __future__ import annotations

import logging
from typing import Any

from reloop.domain.models import CandidateRecord
from reloop.ingestion.delivery import DeliveryStore, deliver_once
from reloop.sinks.feishu.feishu_base import FeishuBaseAdapter
from reloop.sinks.rds.client import upsert_candidate

logger = logging.getLogger(__name__)


class _RdsSink:
    def upsert_candidate(self, record: CandidateRecord) -> dict[str, Any]:
        return upsert_candidate(record)


def run_once(*, limit: int = 10, store: DeliveryStore | None = None) -> list[dict[str, Any]]:
    outbox = store or DeliveryStore()
    rds = _RdsSink()
    feishu = FeishuBaseAdapter()
    results = []
    for job in outbox.claim(limit=limit):
        result = deliver_once(job, outbox, rds, feishu)
        results.append({
            "job_id": result.id,
            "fingerprint": result.fingerprint,
            "local_status": result.local_status,
            "cloud_status": result.cloud_status,
            "feishu_status": result.feishu_status,
            "last_error": result.last_error,
        })
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for item in run_once():
        logger.info("delivery result: %s", item)
