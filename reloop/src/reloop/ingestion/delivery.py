"""Durable candidate delivery outbox.

Local parsing commits a job before any network call.  The worker then performs
the two external writes in order: RDS is the source of truth, and Feishu is a
projection that remains blocked until RDS has succeeded.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from reloop.config import DB_PATH
from reloop.domain.models import CandidateRecord


def _now() -> str:
    return datetime.now(UTC).isoformat()


class RdsSink(Protocol):
    def upsert_candidate(self, record: CandidateRecord) -> dict[str, Any]: ...


class FeishuSink(Protocol):
    def create_record(self, record: CandidateRecord) -> dict[str, Any]: ...


@dataclass(frozen=True)
class DeliveryJob:
    id: int
    fingerprint: str
    payload: dict[str, Any]
    local_status: str
    cloud_status: str
    feishu_status: str
    feishu_record_id: str | None
    attempts: int
    last_error: str | None


class DeliveryStore:
    """SQLite-backed outbox with idempotent enqueue and claim semantics."""

    def __init__(self, db_path: Path | str | None = None):
        self.db_path = Path(db_path or DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_tables()

    def _conn(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def init_tables(self) -> None:
        with closing(self._conn()) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ingestion_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fingerprint TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL,
                    local_status TEXT NOT NULL DEFAULT 'queued',
                    cloud_status TEXT NOT NULL DEFAULT 'blocked',
                    feishu_status TEXT NOT NULL DEFAULT 'blocked',
                    feishu_record_id TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    lease_until REAL,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_ready "
                "ON ingestion_jobs(local_status, cloud_status, feishu_status)"
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(ingestion_jobs)")}
            if "lease_until" not in columns:
                connection.execute("ALTER TABLE ingestion_jobs ADD COLUMN lease_until REAL")
            connection.commit()

    @staticmethod
    def _payload(record: CandidateRecord) -> str:
        return json.dumps(record.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)

    def enqueue(self, record: CandidateRecord, *, fingerprint: str) -> DeliveryJob:
        """Persist or reuse one job for a fingerprint.

        ``INSERT OR IGNORE`` plus a read-back means retries and duplicate source
        submissions always share the same durable job.
        """

        now = _now()
        with closing(self._conn()) as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO ingestion_jobs
                    (fingerprint, payload_json, local_status, cloud_status,
                     feishu_status, created_at, updated_at)
                VALUES (?, ?, 'queued', 'blocked', 'blocked', ?, ?)
                """,
                (fingerprint, self._payload(record), now, now),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM ingestion_jobs WHERE fingerprint = ?", (fingerprint,)
            ).fetchone()
        if row is None:
            raise RuntimeError(f"outbox enqueue lost job for fingerprint {fingerprint}")
        return self._to_job(row)

    def get(self, job_id: int) -> DeliveryJob | None:
        with closing(self._conn()) as connection:
            row = connection.execute("SELECT * FROM ingestion_jobs WHERE id = ?", (job_id,)).fetchone()
        return self._to_job(row) if row else None

    def get_by_fingerprint(self, fingerprint: str) -> DeliveryJob | None:
        with closing(self._conn()) as connection:
            row = connection.execute(
                "SELECT * FROM ingestion_jobs WHERE fingerprint = ?", (fingerprint,)
            ).fetchone()
        return self._to_job(row) if row else None

    def claim(self, *, limit: int = 1, lease_seconds: int = 300) -> list[DeliveryJob]:
        """Atomically claim jobs and make crashed claims recoverable.

        A worker may die after RDS succeeds but before Feishu is attempted.  A
        short lease makes that ``processing`` job claimable again without
        allowing two healthy workers to process it concurrently.
        """

        claimed: list[DeliveryJob] = []
        now = datetime.now(UTC).timestamp()
        lease_until = now + max(1, lease_seconds)
        with closing(self._conn()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT * FROM ingestion_jobs
                WHERE (
                    (
                        local_status IN ('queued', 'retry')
                        AND (cloud_status IN ('blocked', 'failed') OR feishu_status IN ('failed', 'blocked'))
                    )
                    OR (local_status = 'processing' AND lease_until IS NOT NULL AND lease_until <= ?)
                )
                ORDER BY id
                LIMIT ?
                """,
                (now, limit),
            ).fetchall()
            for row in rows:
                connection.execute(
                    """UPDATE ingestion_jobs
                       SET local_status = 'processing', attempts = attempts + 1,
                           lease_until = ?, updated_at = ? WHERE id = ?""",
                    (lease_until, _now(), row["id"]),
                )
            connection.commit()
            for row in rows:
                updated = connection.execute(
                    "SELECT * FROM ingestion_jobs WHERE id = ?", (row["id"],)
                ).fetchone()
                if updated:
                    claimed.append(self._to_job(updated))
        return claimed

    def reset_for_delivery(self, job_id: int, record: CandidateRecord) -> DeliveryJob:
        """Replace a reviewed payload and put its existing job back in the queue."""

        with closing(self._conn()) as connection:
            connection.execute(
                """UPDATE ingestion_jobs SET
                   payload_json=?, local_status='queued', cloud_status='blocked',
                   feishu_status='blocked', feishu_record_id=NULL, attempts=0,
                   lease_until=NULL, last_error=NULL, updated_at=?
                   WHERE id=?""",
                (self._payload(record), _now(), job_id),
            )
            connection.commit()
        job = self.get(job_id)
        if job is None:
            raise KeyError(f"unknown delivery job {job_id}")
        return job

    def mark_cloud_success(self, job_id: int) -> None:
        self._update(
            job_id,
            cloud_status="success",
            feishu_status="pending",
            last_error=None,
        )

    def mark_cloud_failure(self, job_id: int, error: str) -> None:
        self._update(
            job_id,
            local_status="retry",
            cloud_status="failed",
            feishu_status="blocked",
            lease_until=None,
            last_error=error,
        )

    def mark_feishu_success(self, job_id: int, record_id: str | None) -> None:
        self._update(
            job_id,
            local_status="delivered",
            cloud_status="success",
            feishu_status="success",
            feishu_record_id=record_id,
            lease_until=None,
            last_error=None,
        )

    def mark_feishu_failure(self, job_id: int, error: str) -> None:
        self._update(
            job_id,
            local_status="retry",
            cloud_status="success",
            feishu_status="failed",
            lease_until=None,
            last_error=error,
        )

    def _update(self, job_id: int, **values: Any) -> None:
        values["updated_at"] = _now()
        columns = ", ".join(f"{key} = ?" for key in values)
        with closing(self._conn()) as connection:
            connection.execute(
                f"UPDATE ingestion_jobs SET {columns} WHERE id = ?",
                (*values.values(), job_id),
            )
            connection.commit()

    @staticmethod
    def _to_job(row: sqlite3.Row) -> DeliveryJob:
        return DeliveryJob(
            id=row["id"],
            fingerprint=row["fingerprint"],
            payload=json.loads(row["payload_json"]),
            local_status=row["local_status"],
            cloud_status=row["cloud_status"],
            feishu_status=row["feishu_status"],
            feishu_record_id=row["feishu_record_id"],
            attempts=row["attempts"],
            last_error=row["last_error"],
        )


def _record_from_job(job: DeliveryJob) -> CandidateRecord:
    return CandidateRecord.model_validate(job.payload)


def deliver_once(job: DeliveryJob, store: DeliveryStore, rds: RdsSink, feishu: FeishuSink) -> DeliveryJob:
    """Deliver one claimed job while preserving the two-sink state machine."""

    record = _record_from_job(job)
    current = store.get(job.id) or job
    if current.cloud_status != "success":
        try:
            rds.upsert_candidate(record)
        except Exception as exc:
            store.mark_cloud_failure(job.id, str(exc))
            return store.get(job.id) or job
        store.mark_cloud_success(job.id)

    current = store.get(job.id) or job
    if current.feishu_status != "success":
        try:
            response = feishu.create_record(record)
            record_id = _extract_record_id(response)
        except Exception as exc:
            store.mark_feishu_failure(job.id, str(exc))
            return store.get(job.id) or job
        if not record_id:
            store.mark_feishu_failure(job.id, f"Feishu response has no record_id: {response}")
            return store.get(job.id) or job
        store.mark_feishu_success(job.id, record_id)
    return store.get(job.id) or job


def _extract_record_id(response: dict[str, Any]) -> str | None:
    data = response.get("data", {}) if isinstance(response, dict) else {}
    if isinstance(data, dict):
        values = data.get("record_id_list")
        if isinstance(values, list) and values:
            return str(values[0])
        records = data.get("records")
        if isinstance(records, list) and records and isinstance(records[0], dict):
            record_id = records[0].get("record_id")
            return str(record_id) if record_id else None
        record_id = data.get("record_id")
        return str(record_id) if record_id else None
    return None


__all__ = ["DeliveryJob", "DeliveryStore", "deliver_once"]
