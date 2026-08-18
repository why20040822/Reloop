"""End-to-end acceptance tests for the candidate collector pipeline.

These tests exercise the full flow: PDF parse -> CandidateRecord -> Feishu
payload -> dry-run / write.  They do not replace unit tests; they verify that
the modules wired together produce sensible output.
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ingestion.pipeline as pipeline
from adapters.feishu_base import FeishuBaseAdapter
from ingestion.pipeline import (
    _extract_record_id,
    init_ingestion_tables,
    ingest_file,
    ingest_text,
    local_duplicate_exists,
)
from models import CandidateRecord
from parsers.unified_parser import parse_resume_file, parse_resume_text


RESUME_DIR = Path(__file__).resolve().parent.parent / "简历数据"
SAMPLE_PDF = RESUME_DIR / "个人简历_张佩柔.pdf"


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.TemporaryDirectory()
        self._db_patch = patch.object(
            pipeline, "DB_PATH", Path(self._temp_dir.name) / "candidates.db"
        )
        self._db_patch.start()
        init_ingestion_tables()

    def tearDown(self):
        self._db_patch.stop()
        self._temp_dir.cleanup()

    def test_pdf_parse_produces_candidate_record(self):
        if not SAMPLE_PDF.is_file():
            self.skipTest(f"Sample PDF not found: {SAMPLE_PDF}")
        record = parse_resume_file(SAMPLE_PDF)
        self.assertIsInstance(record, CandidateRecord)
        self.assertEqual(record.name, "张佩柔")
        self.assertEqual(record.phone, "18818265709")
        self.assertIn("@", record.email or "")
        self.assertTrue(record.current_company)
        self.assertTrue(record.raw_text)

    def test_text_parse_extracts_phone_and_company(self):
        text = """
王小明
电话：13812345678
邮箱：wxm@example.com
工作经验：8年
字节跳动 | 后端开发工程师 | 2020-至今
"""
        record = parse_resume_text(text)
        self.assertEqual(record.name, "王小明")
        self.assertEqual(record.phone, "13812345678")
        self.assertIn("字节跳动", record.current_company or "")

    def test_feishu_payload_contains_required_fields(self):
        if not SAMPLE_PDF.is_file():
            self.skipTest(f"Sample PDF not found: {SAMPLE_PDF}")
        record = parse_resume_file(SAMPLE_PDF)
        adapter = FeishuBaseAdapter()
        payload = adapter.build_payload(record)
        self.assertIn(adapter.mapping["fields"]["name"]["field_id"], payload)
        self.assertIn(adapter.mapping["fields"]["phone"]["field_id"], payload)
        self.assertIn(adapter.mapping["fields"]["current_company"]["field_id"], payload)

    def test_ingest_file_dry_run_returns_payload(self):
        # Use a resume that has not been written to Feishu yet.
        pdf = RESUME_DIR / "简历_脱敏.pdf"
        if not pdf.is_file():
            pdf = SAMPLE_PDF
        result = ingest_file(pdf, dry_run=True)
        self.assertTrue(result["ok"])
        self.assertIn("action", result)
        self.assertIn("candidate", result)
        if result["action"] == "dry_run":
            self.assertIn("feishu_payload", result)

    def test_database_has_ingestion_log(self):
        db_path = pipeline.DB_PATH
        if not db_path.exists():
            self.skipTest("Database not initialized")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("ingestion_log", tables)
        conn.close()


TEXT_WITH_PHONE = """
王小明
电话：13812345678
邮箱：wxm@example.com
字节跳动 | 后端开发工程师 | 2020-至今
"""


class PipelineDedupTests(unittest.TestCase):
    """去重与幂等：用临时 DB 隔离，不污染真实 candidates.db。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_db_path = pipeline.DB_PATH
        pipeline.DB_PATH = Path(self._tmp.name) / "test.db"
        init_ingestion_tables()

    def tearDown(self):
        pipeline.DB_PATH = self._orig_db_path
        self._tmp.cleanup()

    def _insert_log(self, phone: str, status: str) -> None:
        import sqlite3 as _sq
        from contextlib import closing

        with closing(_sq.connect(pipeline.DB_PATH)) as conn:
            conn.execute(
                """INSERT INTO ingestion_log (
                       fingerprint, phone, name, current_company,
                       feishu_write_status, review_status, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, 'pending', datetime('now'), datetime('now'))""",
                (f"fp-{phone}-{status}", phone, "王小明", "字节跳动", status),
            )
            conn.commit()

    def _fetch_status(self) -> list[str]:
        import sqlite3 as _sq
        from contextlib import closing

        with closing(_sq.connect(pipeline.DB_PATH)) as conn:
            rows = conn.execute(
                "SELECT feishu_write_status FROM ingestion_log ORDER BY id"
            ).fetchall()
        return [r[0] for r in rows]

    def test_dry_run_and_failed_are_not_duplicates(self):
        # dry_run / failed 记录必须允许重试，不算重复
        self._insert_log("13812345678", "dry_run")
        self._insert_log("13812345678", "failed")
        record = CandidateRecord(phone="13812345678", name="王小明", current_company="字节跳动")
        self.assertIsNone(local_duplicate_exists(record))

    def test_success_is_duplicate(self):
        self._insert_log("13812345678", "success")
        record = CandidateRecord(phone="13812345678")
        dup = local_duplicate_exists(record)
        self.assertIsNotNone(dup)
        self.assertEqual(dup["feishu_write_status"], "success")

    def test_ingest_text_write_is_idempotent(self):
        # 相同文本重复真实写入：第二次命中去重，不再创建飞书记录
        with mock.patch.object(
            FeishuBaseAdapter, "upsert_record", return_value={"data": {"record_id": "rec_1"}}
        ) as create, mock.patch.object(
            pipeline, "_sync_to_cloud", return_value={"status": "success"}
        ):
            first = ingest_text(TEXT_WITH_PHONE, dry_run=False)
            self.assertTrue(first["ok"])
            self.assertEqual(first["action"], "created")
            second = ingest_text(TEXT_WITH_PHONE, dry_run=False)
            self.assertTrue(second["ok"])
            self.assertEqual(second["action"], "skipped_duplicate")
            self.assertEqual(create.call_count, 1)
        self.assertEqual(self._fetch_status(), ["success"])

    def test_ingest_text_dry_run_then_real_write_allowed(self):
        # dry_run 后应允许转为真实写入
        with mock.patch.object(
            FeishuBaseAdapter, "upsert_record", return_value={"data": {"record_id": "rec_2"}}
        ), mock.patch.object(
            pipeline, "_sync_to_cloud", return_value={"status": "success"}
        ):
            preview = ingest_text(TEXT_WITH_PHONE, dry_run=True)
            self.assertEqual(preview["action"], "dry_run")
            real = ingest_text(TEXT_WITH_PHONE, dry_run=False)
            self.assertEqual(real["action"], "created")
        self.assertEqual(self._fetch_status(), ["success"])

    def test_missing_record_id_marks_failed(self):
        # 飞书响应缺 record_id 时不得记为 success，且保留响应摘要
        with mock.patch.object(
            FeishuBaseAdapter, "upsert_record", return_value={"data": {}}
        ), mock.patch.object(
            pipeline, "_sync_to_cloud", return_value={"status": "success"}
        ):
            result = ingest_text(TEXT_WITH_PHONE, dry_run=False)
            self.assertTrue(result["ok"])
            self.assertEqual(result["action"], "queued_for_retry")
            self.assertEqual(result["delivery"]["state"], "partial")
            self.assertIn("record_id", result["delivery"]["feishu_error"])
        self.assertEqual(self._fetch_status(), ["failed"])
        # 失败后允许重试
        record = CandidateRecord(phone="13812345678")
        self.assertIsNone(local_duplicate_exists(record))

    def test_extract_record_id_variants(self):
        # 单条创建 / 批量创建 data.records / data 为列表 三种形态
        self.assertEqual(_extract_record_id({"data": {"record_id": "r1"}}), "r1")
        self.assertEqual(
            _extract_record_id({"data": {"records": [{"record_id": "r2"}]}}), "r2"
        )
        self.assertEqual(_extract_record_id({"data": [{"record_id": "r3"}]}), "r3")
        self.assertIsNone(_extract_record_id({"data": {}}))
        self.assertIsNone(_extract_record_id({}))


if __name__ == "__main__":
    unittest.main()
