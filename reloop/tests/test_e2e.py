"""End-to-end acceptance tests for the candidate collector pipeline.

These tests exercise the full flow: PDF parse -> CandidateRecord -> Feishu
payload -> dry-run / write.  They do not replace unit tests; they verify that
the modules wired together produce sensible output.
"""
from __future__ import annotations

import sqlite3
import unittest

from reloop.config import DATA_DIR, REPOSITORY_ROOT
from reloop.domain.models import CandidateRecord
from reloop.ingestion.pipeline import ingest_file, init_ingestion_tables
from reloop.parsing.unified_parser import parse_resume_file, parse_resume_text
from reloop.sinks.feishu.feishu_base import FeishuBaseAdapter

RESUME_DIR = REPOSITORY_ROOT / "简历数据"
SAMPLE_PDF = RESUME_DIR / "个人简历_张佩柔.pdf"


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        init_ingestion_tables()

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
        self.assertIn(adapter.mapping["fields"]["company"]["field_id"], payload)

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
        db_path = DATA_DIR / "candidates.db"
        if not db_path.exists():
            self.skipTest("Database not initialized")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("candidates", tables)
        self.assertIn("ingestion_log", tables)
        conn.close()


if __name__ == "__main__":
    unittest.main()
