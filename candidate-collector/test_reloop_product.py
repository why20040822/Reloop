"""Executable acceptance tests for the production Reloop data contract."""
from __future__ import annotations

import csv
import importlib.util
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


COLLECTOR = Path(__file__).resolve().parent
ROOT = COLLECTOR.parent
sys.path.insert(0, str(COLLECTOR))

from activity import calculate_activity
from cloud_sync.transform import candidate_record_to_cloud
from models import CandidateRecord
from ingestion.delivery import DeliveryStore, DeliveryWorker


def load_wechat_importer():
    path = ROOT / "scripts" / "import_wechat_candidates.py"
    spec = importlib.util.spec_from_file_location("import_wechat_candidates", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class ActivityScoreTests(unittest.TestCase):
    def test_signal_score_and_cap_are_deterministic(self):
        now = datetime(2026, 8, 3, tzinfo=timezone.utc)
        score, last_active, breakdown = calculate_activity(
            {
                "resume_updated_at": "2026-07-20T00:00:00Z",
                "email_new_resume": True,
                "email_received_at": "2026-08-01T12:00:00Z",
                "recently_active": True,
                "recently_active_at": "2026-08-02T09:00:00Z",
            },
            starred=True,
            employment_status="在职-看机会",
            now=now,
        )
        self.assertEqual(score, 100)
        self.assertEqual(last_active, datetime(2026, 8, 2, 9, tzinfo=timezone.utc))
        self.assertEqual(sum(breakdown.values()), 130)

    def test_old_resume_does_not_receive_freshness_points(self):
        score, _, breakdown = calculate_activity(
            {"resume_updated_at": "2026-01-01"},
            now=datetime(2026, 8, 3, tzinfo=timezone.utc),
        )
        self.assertEqual(score, 0)
        self.assertNotIn("resume_updated_within_30d", breakdown)

    def test_candidate_cloud_contract_contains_reloop_fields(self):
        record = CandidateRecord(
            name="张三",
            phone="13812345678",
            employment_status="离职",
            owner="consultant-1",
            starred=True,
        )
        cloud = candidate_record_to_cloud(record)
        self.assertEqual(cloud["activity_score"], 60)
        self.assertEqual(cloud["owner"], "consultant-1")
        self.assertEqual(cloud["visibility"], "team")
        self.assertTrue(cloud["starred"])
        self.assertIn("consultant_starred", cloud["activity_signals"])


class WechatImportTests(unittest.TestCase):
    def test_dirty_duplicate_and_low_confidence_rows_enter_review_queue(self):
        importer = load_wechat_importer()
        rows = [
            {"姓名": "张三", "微信号": "wx_zhang", "当前公司": "A公司", "职位": "产品", "置信度": "高", "验证消息原文": "A公司产品"},
            {"姓名": "张三", "微信号": "wx_zhang", "当前公司": "A公司", "职位": "产品", "置信度": "高", "验证消息原文": "重复"},
            {"姓名": "李四", "当前公司": "B公司", "置信度": "低", "验证消息原文": "B公司"},
            {"姓名": "", "置信度": "高", "验证消息原文": "hello"},
        ]
        accepted, review = importer.prepare_import(rows, owner="consultant-1")
        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(review), 3)
        self.assertEqual(accepted[0].extra["wechat_id"], "wx_zhang")
        self.assertTrue(any("重复" in reason for reason in review[0]["reasons"]))

    def test_csv_reader_accepts_workbuddy_headers(self):
        importer = load_wechat_importer()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wechat.csv"
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["姓名", "微信号", "置信度", "验证消息原文"])
                writer.writeheader()
                writer.writerow({"姓名": "王五", "微信号": "wx_wang", "置信度": "中", "验证消息原文": "算法工程师"})
            accepted, review = importer.prepare_import(importer.read_rows(path), owner=None)
        self.assertEqual(len(accepted), 1)
        self.assertFalse(review)


class DurableDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = DeliveryStore(Path(self.temp.name) / "jobs.db")
        self.record = CandidateRecord(name="赵六", phone="13912345678")
        self.job_id = self.store.enqueue(self.record, "fingerprint-1")

    def tearDown(self):
        self.temp.cleanup()

    def test_feishu_is_blocked_until_cloud_succeeds(self):
        calls: list[str] = []

        def cloud(_: CandidateRecord):
            calls.append("cloud")
            return {"status": "failed", "error": "RDS unavailable"}

        def feishu(_: CandidateRecord):
            calls.append("feishu")
            return {"status": "success", "record_id": "rec1"}

        result = DeliveryWorker(self.store, cloud, feishu).deliver(self.job_id)
        self.assertEqual(calls, ["cloud"])
        self.assertEqual(result.state, "retrying")
        self.assertEqual(result.feishu_status, "blocked")

    def test_retry_resumes_without_rewriting_successful_cloud_sink(self):
        calls: list[str] = []

        def cloud(_: CandidateRecord):
            calls.append("cloud")
            return {"status": "success"}

        feishu_attempt = 0

        def feishu(_: CandidateRecord):
            nonlocal feishu_attempt
            feishu_attempt += 1
            calls.append("feishu")
            if feishu_attempt == 1:
                return {"status": "failed", "error": "rate limited"}
            return {"status": "success", "record_id": "rec2"}

        worker = DeliveryWorker(self.store, cloud, feishu)
        first = worker.deliver(self.job_id)
        second = worker.deliver(self.job_id)
        self.assertEqual(first.state, "partial")
        self.assertEqual(second.state, "completed")
        self.assertEqual(calls, ["cloud", "feishu", "feishu"])

    def test_repeated_enqueue_reuses_same_job(self):
        repeated = self.store.enqueue(self.record, "fingerprint-1")
        self.assertEqual(repeated, self.job_id)


if __name__ == "__main__":
    unittest.main()
