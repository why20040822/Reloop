from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz
import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

import app
import ingestion.browser_capture as browser_capture
import ingestion.pipeline as pipeline
import adapters.feishu_base as feishu_base
from adapters.feishu_base import FeishuBaseAdapter
from ingestion.browser_capture import BrowserCapturePayload, build_candidate_from_capture, import_browser_capture
from models import CandidateRecord

# jiands 传入的 Otto1/Otto2 映射（本仓库默认映射是候选人主表，
# 这些测试针对 Otto 双表行为，显式指定映射文件）
OTTO_MAPPING = Path(__file__).resolve().parent / "config" / "feishu_field_mapping_otto1.json"


class FakeAdapter:
    table_id = "tbl-primary"

    def dry_run(self, record: CandidateRecord):
        return {"fields": {"姓名": record.name}}

    def record_exists(self, _record: CandidateRecord) -> bool:
        return False

    def create_record(self, record: CandidateRecord):
        return {
            "data": {"record_id_list": ["rec-created"]},
            "feishu_table_id": self.table_id,
            "attachment_uploaded": bool(record.original_attachment_path),
        }


class BrowserImportV2Tests(unittest.TestCase):
    def payload(self, **overrides):
        data = {
            "url": "https://app.ttcadvisory.com/app/talent/PL90001",
            "text": "张三\n某科技公司\n后端工程师\n本科\n工作经历足够用于结构化解析",
            "platform": "ttc",
            "source_candidate_id": "PL90001",
            "profile": {
                "cn_name": "张三",
                "phone": "13800138000",
                "current_company": "某科技公司",
                "current_title": "后端工程师",
            },
        }
        data.update(overrides)
        return BrowserCapturePayload(**data)

    def test_source_identity_precedes_phone_for_fingerprint(self):
        left = CandidateRecord(
            name="同名", phone="13800138000", source_platform="maimai", source_record_id="u-1"
        )
        right = CandidateRecord(
            name="同名", phone="13800138000", source_platform="maimai", source_record_id="u-2"
        )
        self.assertNotEqual(left.fingerprint_input(), right.fingerprint_input())

    def test_numeric_maimai_id_is_not_treated_as_ttc_pid(self):
        record = CandidateRecord(
            source_platform="maimai",
            source_type="browser_auto_import",
            source_record_id="123456789",
        )
        self.assertIsNone(record.ttc_pid)
        self.assertEqual(
            record.fingerprint_input(),
            "source_record|maimai|123456789",
        )

    def test_ttc_trailing_slash_is_normalized(self):
        record = CandidateRecord(
            source_url="https://app.ttcadvisory.com/app/talent/PL90001/",
        )
        self.assertEqual(record.source_platform, "ttc")
        self.assertEqual(
            record.source_url,
            "https://app.ttcadvisory.com/app/talent/PL90001",
        )

    def test_schema_validation_is_enabled_by_default(self):
        self.assertTrue(FeishuBaseAdapter(mapping_path=OTTO_MAPPING).validate_schema)

    def test_browser_page_origin_cannot_call_privileged_import(self):
        request = Request({
            "type": "http",
            "headers": [(b"origin", b"https://app.ttcadvisory.com")],
        })
        with self.assertRaises(HTTPException) as raised:
            app._require_extension_or_direct_request(request)
        self.assertEqual(raised.exception.status_code, 403)

    def test_extension_origin_can_call_privileged_import(self):
        request = Request({
            "type": "http",
            "headers": [(b"origin", b"chrome-extension://abcdefghijklmnopabcdefghijklmnop")],
        })
        app._require_extension_or_direct_request(request)

    def test_extension_private_network_preflight_is_allowed(self):
        client = TestClient(app.app)
        response = client.options(
            "/api/import-browser-capture-v2",
            headers={
                "Origin": "chrome-extension://abcdefghijklmnopabcdefghijklmnop",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
                "Access-Control-Request-Private-Network": "true",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("access-control-allow-private-network"), "true"
        )
        self.assertEqual(
            response.headers.get("access-control-allow-origin"),
            "chrome-extension://abcdefghijklmnopabcdefghijklmnop",
        )

    def test_signed_pdf_url_is_not_leaked_in_download_error(self):
        request = httpx.Request("GET", "https://cdn.example/resume.pdf?secret=token")
        response = httpx.Response(403, request=request)
        error = httpx.HTTPStatusError("forbidden", request=request, response=response)
        message = app._safe_pdf_download_error(error)
        self.assertEqual(message, "PDF 下载返回 HTTP 403")
        self.assertNotIn("secret", message)

    def test_no_pdf_adds_explicit_fallback_note(self):
        record = build_candidate_from_capture(self.payload())
        self.assertEqual(record.source_record_id, "PL90001")
        self.assertEqual(record.name, "张三")
        self.assertIn("未获取到PDF原件", record.notes or "")

    def test_original_pdf_is_preserved_and_hashed(self):
        with tempfile.TemporaryDirectory() as directory:
            pdf_path = Path(directory) / "original.pdf"
            document = fitz.open()
            page = document.new_page()
            page.insert_text((72, 72), "Resume PDF original")
            document.save(pdf_path)
            document.close()
            expected = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
            record = build_candidate_from_capture(self.payload(), attachment_path=pdf_path)
            self.assertEqual(record.original_attachment_path, str(pdf_path.resolve()))
            self.assertEqual(record.attachment_sha256, expected)
            self.assertEqual(record.name, "张三")

    def test_import_persists_platform_table_and_attachment_state(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "test.db"
            with patch.object(browser_capture, "DB_PATH", db_path), patch.object(pipeline, "DB_PATH", db_path):
                result = import_browser_capture(self.payload(), feishu_adapter=FakeAdapter())
                self.assertTrue(result["ok"])
                self.assertEqual(result["feishu_table_id"], "tbl-primary")
                with browser_capture._db_conn() as connection:
                    row = connection.execute("SELECT * FROM ingestion_log").fetchone()
                self.assertEqual(row["source_platform"], "ttc")
                self.assertEqual(row["source_record_id"], "PL90001")
                self.assertEqual(row["attachment_status"], "none")

    def test_duplicate_returns_existing_record_and_table(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "test.db"
            with patch.object(browser_capture, "DB_PATH", db_path), patch.object(pipeline, "DB_PATH", db_path):
                created = import_browser_capture(self.payload(), feishu_adapter=FakeAdapter())
                duplicate = import_browser_capture(self.payload(), feishu_adapter=FakeAdapter())

        self.assertEqual(created["action"], "created")
        self.assertEqual(duplicate["action"], "skipped_duplicate")
        self.assertEqual(duplicate["feishu_record_id"], "rec-created")
        self.assertEqual(duplicate["feishu_table_id"], "tbl-primary")

    def test_private_pdf_url_is_rejected(self):
        with self.assertRaises(ValueError):
            app._validate_public_https_url("https://127.0.0.1/resume.pdf")

    def test_server_pdf_download_is_limited_to_platform_dns_zones(self):
        self.assertTrue(app._platform_allows_remote_pdf(
            "https://res.ttcadvisory.com/resume.pdf", "ttc"
        ))
        self.assertTrue(app._platform_allows_remote_pdf(
            "https://api.maimai.cn/resume.pdf", "maimai"
        ))
        self.assertFalse(app._platform_allows_remote_pdf(
            "https://ttcadvisory.com.evil.example/resume.pdf", "ttc"
        ))
        self.assertFalse(app._platform_allows_remote_pdf(
            "https://cdn.example/resume.pdf", "maimai"
        ))

    def test_invalid_pdf_magic_is_rejected(self):
        with self.assertRaises(ValueError):
            app._persist_pdf_bytes(b"not a pdf", "resume.pdf", "PL1")

    def test_otto1_lock_routes_create_to_otto2(self):
        adapter = FeishuBaseAdapter(mapping_path=OTTO_MAPPING, validate_schema=False)
        calls = []

        class Lock:
            def __init__(self, path, *, operation):
                self.path = path
                self.operation = operation

            def __enter__(self):
                if self.path == feishu_base.TTC_SYNC_LOCK_PATH:
                    raise feishu_base.LockHeldError("occupied")
                return self

            def __exit__(self, *_args):
                return None

        def fake_create(instance, _record):
            calls.append(instance.table_id)
            return {"data": {"record_id_list": ["rec-fallback"]}}

        with patch.object(feishu_base, "ExclusiveSyncLock", Lock), patch.object(
            FeishuBaseAdapter, "_create_record_unlocked", fake_create
        ):
            result = adapter.create_record(CandidateRecord(name="备用表测试"))

        self.assertEqual(calls, ["tblEHeMS9wk6g0ui"])
        self.assertEqual(result["feishu_table_id"], "tblEHeMS9wk6g0ui")
        self.assertEqual(result["fallback_reason"], "otto1_lock_held")


if __name__ == "__main__":
    unittest.main()
