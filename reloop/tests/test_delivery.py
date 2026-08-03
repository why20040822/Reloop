from __future__ import annotations

import sqlite3

import pytest

from reloop.domain.models import CandidateRecord
from reloop.ingestion.delivery import DeliveryStore, LeaseLostError, deliver_once


class FakeRds:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls = 0

    def upsert_candidate(self, record: CandidateRecord) -> dict:
        self.calls += 1
        if self.error:
            raise self.error
        return {"ok": True}


class FakeFeishu:
    def __init__(self, response: dict | None = None, error: Exception | None = None):
        self.response = response or {"data": {"record_id_list": ["rec_1"]}}
        self.error = error
        self.calls = 0

    def create_record(self, record: CandidateRecord) -> dict:
        self.calls += 1
        if self.error:
            raise self.error
        return self.response


class ExistingFeishu(FakeFeishu):
    def find_record_id(self, record: CandidateRecord) -> str:
        return "rec_existing"


def record() -> CandidateRecord:
    return CandidateRecord(name="张三", phone="13812345678", raw_text="张三\n13812345678")


def test_duplicate_fingerprint_reuses_one_job(tmp_path):
    store = DeliveryStore(tmp_path / "outbox.db")
    fingerprint = record().fingerprint()
    first = store.enqueue(record(), fingerprint=fingerprint)
    second = store.enqueue(CandidateRecord(name="另一条", phone="13812345678"), fingerprint=fingerprint)

    assert first.id == second.id
    assert store.get_by_fingerprint(fingerprint).payload["name"] == "张三"


def test_rds_failure_blocks_feishu(tmp_path):
    store = DeliveryStore(tmp_path / "outbox.db")
    store.enqueue(record(), fingerprint=record().fingerprint())
    claimed = store.claim()[0]
    rds = FakeRds(RuntimeError("rds down"))
    feishu = FakeFeishu()

    result = deliver_once(claimed, store, rds, feishu)

    assert result.cloud_status == "failed"
    assert result.feishu_status == "blocked"
    assert rds.calls == 1
    assert feishu.calls == 0


def test_feishu_failure_retries_only_feishu(tmp_path):
    store = DeliveryStore(tmp_path / "outbox.db")
    store.enqueue(record(), fingerprint=record().fingerprint())
    claimed = store.claim()[0]
    rds = FakeRds()
    failing_feishu = FakeFeishu(error=RuntimeError("feishu down"))

    first = deliver_once(claimed, store, rds, failing_feishu)
    assert first.cloud_status == "success"
    assert first.feishu_status == "failed"
    assert rds.calls == 1
    assert failing_feishu.calls == 1

    retry = store.claim()[0]
    recovered_feishu = FakeFeishu()
    second = deliver_once(retry, store, rds, recovered_feishu)

    assert second.local_status == "delivered"
    assert second.cloud_status == "success"
    assert second.feishu_status == "success"
    assert rds.calls == 1
    assert recovered_feishu.calls == 1


def test_missing_feishu_record_id_is_not_success(tmp_path):
    store = DeliveryStore(tmp_path / "outbox.db")
    store.enqueue(record(), fingerprint=record().fingerprint())
    job = store.claim()[0]

    result = deliver_once(job, store, FakeRds(), FakeFeishu(response={"data": {}}))

    assert result.cloud_status == "success"
    assert result.feishu_status == "failed"
    assert result.local_status == "retry"


def test_expired_lease_recovers_after_process_crash(tmp_path):
    store = DeliveryStore(tmp_path / "outbox.db")
    store.enqueue(record(), fingerprint=record().fingerprint())
    claimed = store.claim(lease_seconds=300)[0]
    store.mark_cloud_success(claimed.id)

    with sqlite3.connect(tmp_path / "outbox.db") as connection:
        connection.execute("UPDATE ingestion_jobs SET lease_until=0 WHERE id=?", (claimed.id,))
        connection.commit()

    recovered = store.claim()[0]
    assert recovered.cloud_status == "success"
    assert recovered.feishu_status == "pending"

    rds = FakeRds()
    feishu = FakeFeishu()
    result = deliver_once(recovered, store, rds, feishu)
    assert result.local_status == "delivered"
    assert rds.calls == 0
    assert feishu.calls == 1


def test_feishu_existing_record_reconciles_without_create(tmp_path):
    store = DeliveryStore(tmp_path / "outbox.db")
    candidate = record()
    store.enqueue(candidate, fingerprint=candidate.fingerprint())
    job = store.claim()[0]

    result = deliver_once(job, store, FakeRds(), ExistingFeishu())

    assert result.local_status == "delivered"
    assert result.feishu_record_id == "rec_existing"


def test_stale_lease_cannot_update_reclaimed_job(tmp_path):
    store = DeliveryStore(tmp_path / "outbox.db")
    candidate = record()
    store.enqueue(candidate, fingerprint=candidate.fingerprint())
    first = store.claim(lease_seconds=1)[0]
    with sqlite3.connect(tmp_path / "outbox.db") as connection:
        connection.execute("UPDATE ingestion_jobs SET lease_until=0 WHERE id=?", (first.id,))
        connection.commit()
    second = store.claim()[0]

    with pytest.raises(LeaseLostError):
        store.mark_cloud_success(first.id, first.lease_token)
    assert store.get(second.id).lease_token == second.lease_token
