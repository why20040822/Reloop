"""Durable delivery outbox for candidate ingestion.

Parsing and delivery are separate concerns: a candidate is first persisted as
a job, then delivered to the canonical RDS store and finally projected to
Feishu. Jobs survive process crashes and can be retried without duplicating a
candidate in either sink.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from models import CandidateRecord


Sink = Callable[[CandidateRecord], dict[str, Any]]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat()


@dataclass(frozen=True)
class DeliveryResult:
    job_id: str
    state: str
    cloud_status: str
    feishu_status: str
    cloud_error: str | None = None
    feishu_error: str | None = None
    next_attempt_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class DeliveryStore:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def init(self) -> None:
        with closing(self.connect()) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ingestion_jobs (
                    job_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL UNIQUE,
                    candidate_json TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending',
                    cloud_status TEXT NOT NULL DEFAULT 'pending',
                    feishu_status TEXT NOT NULL DEFAULT 'blocked',
                    cloud_attempts INTEGER NOT NULL DEFAULT 0,
                    feishu_attempts INTEGER NOT NULL DEFAULT 0,
                    cloud_error TEXT,
                    feishu_error TEXT,
                    feishu_record_id TEXT,
                    next_attempt_at TEXT,
                    lease_owner TEXT,
                    lease_until TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_retry "
                "ON ingestion_jobs(state, next_attempt_at, lease_until)"
            )
            conn.commit()

    def enqueue(self, record: CandidateRecord, fingerprint: str) -> str:
        self.init()
        job_id = uuid.uuid4().hex
        payload = record.model_dump_json()
        now = iso()
        with closing(self.connect()) as conn:
            conn.execute(
                """
                INSERT INTO ingestion_jobs (
                    job_id, fingerprint, candidate_json, source_type,
                    state, cloud_status, feishu_status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'pending', 'pending', 'blocked', ?, ?)
                ON CONFLICT(fingerprint) DO UPDATE SET
                    candidate_json=CASE
                        WHEN ingestion_jobs.state='completed' THEN ingestion_jobs.candidate_json
                        ELSE excluded.candidate_json
                    END,
                    source_type=CASE
                        WHEN ingestion_jobs.state='completed' THEN ingestion_jobs.source_type
                        ELSE excluded.source_type
                    END,
                    state=CASE
                        WHEN ingestion_jobs.state='completed' THEN 'completed'
                        ELSE 'pending'
                    END,
                    next_attempt_at=NULL,
                    updated_at=excluded.updated_at
                """,
                (job_id, fingerprint, payload, record.source_type, now, now),
            )
            row = conn.execute(
                "SELECT job_id FROM ingestion_jobs WHERE fingerprint=?", (fingerprint,)
            ).fetchone()
            conn.commit()
        return str(row["job_id"])

    def get(self, job_id: str) -> dict[str, Any] | None:
        with closing(self.connect()) as conn:
            row = conn.execute("SELECT * FROM ingestion_jobs WHERE job_id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    def list(self, *, state: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = "SELECT * FROM ingestion_jobs"
        params: list[Any] = []
        if state:
            query += " WHERE state=?"
            params.append(state)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(limit, 500)))
        with closing(self.connect()) as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def stats(self) -> dict[str, int]:
        with closing(self.connect()) as conn:
            rows = conn.execute(
                "SELECT state, COUNT(*) AS count FROM ingestion_jobs GROUP BY state"
            ).fetchall()
        return {str(row["state"]): int(row["count"]) for row in rows}

    def retry(self, job_id: str) -> bool:
        with closing(self.connect()) as conn:
            affected = conn.execute(
                """
                UPDATE ingestion_jobs
                SET state='retrying', next_attempt_at=NULL,
                    lease_owner=NULL, lease_until=NULL, updated_at=?
                    ,cloud_attempts=CASE WHEN cloud_status='success' THEN cloud_attempts ELSE 0 END
                    ,feishu_attempts=CASE WHEN feishu_status='success' THEN feishu_attempts ELSE 0 END
                WHERE job_id=? AND state != 'completed'
                """,
                (iso(), job_id),
            ).rowcount
            conn.commit()
        return affected == 1

    def claim_due(self, owner: str, *, lease_seconds: int = 60) -> str | None:
        """Atomically lease one due job for a worker."""
        now = utc_now()
        with closing(self.connect()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT job_id FROM ingestion_jobs
                WHERE state IN ('pending','retrying','partial')
                  AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                  AND (lease_until IS NULL OR lease_until < ?)
                ORDER BY created_at ASC LIMIT 1
                """,
                (iso(now), iso(now)),
            ).fetchone()
            if not row:
                conn.commit()
                return None
            conn.execute(
                "UPDATE ingestion_jobs SET lease_owner=?, lease_until=?, updated_at=? WHERE job_id=?",
                (owner, iso(now + timedelta(seconds=lease_seconds)), iso(now), row["job_id"]),
            )
            conn.commit()
            return str(row["job_id"])

    def update(self, job_id: str, **values: Any) -> None:
        if not values:
            return
        values["updated_at"] = iso()
        assignments = ", ".join(f"{key}=?" for key in values)
        with closing(self.connect()) as conn:
            conn.execute(
                f"UPDATE ingestion_jobs SET {assignments} WHERE job_id=?",
                (*values.values(), job_id),
            )
            conn.commit()


class DeliveryWorker:
    def __init__(
        self,
        store: DeliveryStore,
        cloud_sink: Sink,
        feishu_sink: Sink,
        *,
        max_attempts: int = 8,
    ):
        self.store = store
        self.cloud_sink = cloud_sink
        self.feishu_sink = feishu_sink
        self.max_attempts = max_attempts

    @staticmethod
    def _retry_at(attempts: int) -> str:
        delay = min(3600, 2 ** min(attempts, 10))
        return iso(utc_now() + timedelta(seconds=delay))

    def deliver(self, job_id: str) -> DeliveryResult:
        job = self.store.get(job_id)
        if not job:
            raise KeyError(f"unknown ingestion job: {job_id}")
        record = CandidateRecord.model_validate_json(job["candidate_json"])

        cloud_status = job["cloud_status"]
        feishu_status = job["feishu_status"]
        cloud_error = job["cloud_error"]
        feishu_error = job["feishu_error"]

        if cloud_status != "success":
            attempts = int(job["cloud_attempts"]) + 1
            try:
                response = self.cloud_sink(record)
                if response.get("status") != "success":
                    raise RuntimeError(response.get("error") or response.get("reason") or str(response))
                cloud_status, cloud_error = "success", None
                feishu_status = "pending" if feishu_status == "blocked" else feishu_status
            except Exception as exc:
                cloud_status, cloud_error = "failed", str(exc)
            self.store.update(
                job_id,
                cloud_status=cloud_status,
                cloud_error=cloud_error,
                cloud_attempts=attempts,
                feishu_status=feishu_status,
            )
            if cloud_status != "success":
                terminal = attempts >= self.max_attempts
                state = "dead_letter" if terminal else "retrying"
                next_attempt = None if terminal else self._retry_at(attempts)
                self.store.update(
                    job_id, state=state, next_attempt_at=next_attempt,
                    lease_owner=None, lease_until=None,
                )
                return DeliveryResult(
                    job_id, state, cloud_status, feishu_status,
                    cloud_error=cloud_error, feishu_error=feishu_error,
                    next_attempt_at=next_attempt,
                )

        if feishu_status != "success":
            current = self.store.get(job_id) or job
            attempts = int(current["feishu_attempts"]) + 1
            try:
                response = self.feishu_sink(record)
                record_id = response.get("record_id")
                if response.get("status") != "success" or not record_id:
                    raise RuntimeError(response.get("error") or "Feishu did not return record_id")
                feishu_status, feishu_error = "success", None
                self.store.update(job_id, feishu_record_id=record_id)
            except Exception as exc:
                feishu_status, feishu_error = "failed", str(exc)
            self.store.update(
                job_id,
                feishu_status=feishu_status,
                feishu_error=feishu_error,
                feishu_attempts=attempts,
            )
            if feishu_status != "success":
                terminal = attempts >= self.max_attempts
                state = "dead_letter" if terminal else "partial"
                next_attempt = None if terminal else self._retry_at(attempts)
                self.store.update(
                    job_id, state=state, next_attempt_at=next_attempt,
                    lease_owner=None, lease_until=None,
                )
                return DeliveryResult(
                    job_id, state, cloud_status, feishu_status,
                    cloud_error=cloud_error, feishu_error=feishu_error,
                    next_attempt_at=next_attempt,
                )

        completed_at = iso()
        self.store.update(
            job_id, state="completed", next_attempt_at=None,
            lease_owner=None, lease_until=None, completed_at=completed_at,
        )
        return DeliveryResult(job_id, "completed", "success", "success")
