"""Integration tests for review endpoints using FastAPI TestClient."""

import json
import unittest
import uuid
from contextlib import closing

from fastapi.testclient import TestClient

from reloop.api.main import app as http_app
from reloop.ingestion.delivery import DeliveryStore
from reloop.ingestion.pipeline import _db_conn, init_ingestion_tables


class ReviewApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_ingestion_tables()
        DeliveryStore()
        # Start with empty tables so reprocess_existing on app startup has no stale data.
        with closing(_db_conn()) as conn:
            conn.execute("DELETE FROM candidates")
            conn.execute("DELETE FROM ingestion_log")
            conn.execute("DELETE FROM ingestion_jobs")
            conn.commit()
        cls.client = TestClient(http_app)

    def setUp(self) -> None:
        # Ensure each test in this class starts from a clean state.
        DeliveryStore()
        with closing(_db_conn()) as conn:
            conn.execute("DELETE FROM candidates")
            conn.execute("DELETE FROM ingestion_log")
            conn.execute("DELETE FROM ingestion_jobs")
            conn.commit()

    def test_review_v1_queue_and_reject(self) -> None:
        text = """王小明
13812345678
wangxm@example.com

工作经历
字节跳动 产品经理 2020.03 - 至今

教育经历
北京大学 本科 2016.09 - 2020.07
"""
        resp = self.client.post("/api/import-text", json={"text": text, "title": "测试简历"})
        self.assertEqual(resp.status_code, 200)
        candidate = resp.json()["candidate"]
        candidate_id = candidate["id"]
        self.assertEqual(candidate["name"], "王小明")

        resp = self.client.get("/api/review-v1/queue?limit=10")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        ids = {item["id"] for item in data["items"]}
        self.assertIn(candidate_id, ids)

        resp = self.client.get(f"/api/review-v1/{candidate_id}")
        self.assertEqual(resp.status_code, 200)
        detail = resp.json()
        self.assertTrue(detail["ok"])
        self.assertEqual(detail["candidate"]["name"], "王小明")

        resp = self.client.post(f"/api/review-v1/{candidate_id}/reject", json={"reason": "测试驳回"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["action"], "rejected")

        resp = self.client.get("/api/review-v1/queue?limit=10")
        self.assertEqual(resp.status_code, 200)
        ids = {item["id"] for item in resp.json()["items"]}
        self.assertNotIn(candidate_id, ids)

    def test_review_v1_detail_not_found(self) -> None:
        resp = self.client.get("/api/review-v1/999999")
        self.assertEqual(resp.status_code, 404)

    def test_quality_stats_endpoint(self) -> None:
        resp = self.client.get("/api/quality/stats")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertIn("field_completeness", data)
        self.assertIn("pending_review_count", data)

    def test_review_v1_approve_converts_work_experience_dicts(self) -> None:
        resp = self.client.post("/api/import-text", json={"text": "王小明 13812345678", "title": "测试"})
        self.assertEqual(resp.status_code, 200)
        candidate_id = resp.json()["candidate"]["id"]

        resp = self.client.post(
            f"/api/review-v1/{candidate_id}/approve",
            json={
                "current_company": "字节跳动",
                "work_experiences": [
                    {"company": "字节跳动", "role": "产品经理", "period": "2020.03 - 至今"}
                ],
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["action"], "approved")
        self.assertEqual(resp.json()["delivery"], "queued")
        job = DeliveryStore().get(resp.json()["job_id"])
        self.assertIsNotNone(job)
        self.assertEqual(job.payload["current_company"], "字节跳动")
        self.assertEqual(job.payload["work_experiences"][0]["role"], "产品经理")

        # Verify local candidates table was updated with corrections.
        detail = self.client.get(f"/api/review-v1/{candidate_id}").json()
        self.assertEqual(detail["review_status"], "approved")
        self.assertEqual(detail["candidate"]["current_company"], "字节跳动")
        self.assertEqual(len(detail["candidate"]["work_experiences"]), 1)

    def test_review_v1_approve_corrects_education(self) -> None:
        resp = self.client.post("/api/import-text", json={"text": "王小明 13812345678", "title": "测试"})
        self.assertEqual(resp.status_code, 200)
        candidate_id = resp.json()["candidate"]["id"]

        resp = self.client.post(
            f"/api/review-v1/{candidate_id}/approve",
            json={
                "school": "北京大学",
                "education": {"school": "北京大学", "degree": "本科", "graduation_year": 2020},
            },
        )
        self.assertEqual(resp.status_code, 200)
        job = DeliveryStore().get(resp.json()["job_id"])
        self.assertIsNotNone(job)
        self.assertEqual(job.payload["school"], "北京大学")
        self.assertEqual(job.payload["education"]["degree"], "本科")

    def test_review_v1_approve_marks_corrected_fields_verified(self) -> None:
        resp = self.client.post("/api/import-text", json={"text": "王小明 13812345678", "title": "测试"})
        self.assertEqual(resp.status_code, 200)
        candidate_id = resp.json()["candidate"]["id"]

        resp = self.client.post(
            f"/api/review-v1/{candidate_id}/approve",
            json={"name": "王大明", "current_company": "字节跳动"},
        )
        job = DeliveryStore().get(resp.json()["job_id"])
        self.assertIsNotNone(job)
        self.assertEqual(job.payload["name"], "王大明")
        self.assertEqual(job.payload["parse_confidence"], 1.0)
        name_conf = next(fc for fc in job.payload["field_confidences"] if fc["field"] == "name")
        self.assertEqual(name_conf["confidence"], 1.0)
        self.assertEqual(name_conf["note"], "human verified")
        company_conf = next(fc for fc in job.payload["field_confidences"] if fc["field"] == "current_company")
        self.assertEqual(company_conf["confidence"], 1.0)

    def test_review_v2_approve_updates_top_level_columns(self) -> None:
        init_ingestion_tables()
        fingerprint = f"test-fingerprint-{uuid.uuid4().hex}"
        with closing(_db_conn()) as conn:
            conn.execute(
                """
                INSERT INTO ingestion_log (
                    fingerprint, name, phone, current_company, current_title,
                    feishu_write_status, review_status, dry_run_payload, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                """,
                (
                    fingerprint,
                    "旧姓名",
                    "13800000000",
                    "旧公司",
                    "旧职位",
                    "dry_run",
                    "pending",
                    json.dumps({
                        "candidate": {
                            "name": "旧姓名",
                            "phone": "13800000000",
                            "current_company": "旧公司",
                            "current_title": "旧职位",
                        }
                    }),
                ),
            )
            conn.commit()
            log_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        resp = self.client.post(
            f"/api/review/{log_id}/approve",
            json={
                "name": "新姓名",
                "current_company": "新公司",
                "work_experiences": [
                    {"company": "新公司", "role": "新职位", "period": "2020.03 - 至今"}
                ],
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["action"], "approved")
        self.assertEqual(resp.json()["delivery"], "queued")
        job = DeliveryStore().get(resp.json()["job_id"])
        self.assertIsNotNone(job)
        self.assertEqual(job.payload["name"], "新姓名")

        with closing(_db_conn()) as conn:
            row = conn.execute(
                "SELECT name, current_company, current_title FROM ingestion_log WHERE id=?",
                (log_id,),
            ).fetchone()
            self.assertEqual(row["name"], "新姓名")
            self.assertEqual(row["current_company"], "新公司")
            self.assertEqual(row["current_title"], "新职位")


if __name__ == "__main__":
    unittest.main()
