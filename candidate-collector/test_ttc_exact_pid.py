from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ingestion.pipeline as pipeline
import ingestion.browser_capture as browser_capture
from adapters.feishu_base import FeishuBaseAdapter, TTC_SYNC_LOCK_PATH
from models import CandidateRecord

# jiands 传入的 Otto1/Otto2 映射（本仓库默认映射是候选人主表，
# 这些测试针对 Otto 双表行为，显式指定映射文件）
OTTO_MAPPING = Path(__file__).resolve().parent / "config" / "feishu_field_mapping_otto1.json"


class TtcIdentityTests(unittest.TestCase):
    def test_canonical_ttc_url_derives_source_record_id_and_wins_fingerprint(self) -> None:
        record = CandidateRecord(
            source_url="https://app.ttcadvisory.com/app/talent/PL1833858043295301632",
            attachment_sha256="attachment-hash",
            phone="13812345678",
        )

        self.assertEqual(record.source_record_id, "PL1833858043295301632")
        self.assertEqual(record.ttc_pid, "PL1833858043295301632")
        self.assertEqual(record.fingerprint_input(), "ttc_pid|PL1833858043295301632")

    def test_noncanonical_url_does_not_create_a_ttc_identity(self) -> None:
        record = CandidateRecord(
            source_url=(
                "https://app.ttcadvisory.com/app/talent/"
                "PL1833858043295301632?from=search"
            ),
            attachment_sha256="attachment-hash",
        )

        self.assertIsNone(record.source_record_id)
        self.assertIsNone(record.ttc_pid)
        self.assertEqual(record.fingerprint_input(), "sha256|attachment-hash")

    def test_conflicting_explicit_pid_and_canonical_url_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CandidateRecord(
                source_record_id="PL1929736208728313856",
                source_url=(
                    "https://app.ttcadvisory.com/app/talent/"
                    "PL1833858043295301632"
                ),
            )

    def test_pid_conflict_introduced_after_initialization_is_rejected(self) -> None:
        record = CandidateRecord(source_record_id="PL1929736208728313856")
        record.source_url = (
            "https://app.ttcadvisory.com/app/talent/PL1833858043295301632"
        )

        with self.assertRaises(ValueError):
            _ = record.ttc_pid

    def test_explicit_ttc_source_record_id_is_a_stable_identity_without_url(self) -> None:
        record = CandidateRecord(
            source_record_id="PL1929736208728313856",
            name="显式来源记录",
        )

        self.assertEqual(record.ttc_pid, "PL1929736208728313856")
        self.assertEqual(record.fingerprint_input(), "ttc_pid|PL1929736208728313856")


class TtcRemoteDedupTests(unittest.TestCase):
    def setUp(self) -> None:
        self._lock_tmp = tempfile.TemporaryDirectory()
        self._lock_patch = patch(
            "adapters.feishu_base.TTC_SYNC_LOCK_PATH",
            Path(self._lock_tmp.name) / "ttc_sync.lock",
        )
        self._fallback_lock_patch = patch(
            "adapters.feishu_base.FALLBACK_SYNC_LOCK_PATH",
            Path(self._lock_tmp.name) / "otto2.lock",
        )
        self._schema_patch = patch.object(
            FeishuBaseAdapter,
            "_preflight_schema",
            return_value=None,
        )
        self._lock_patch.start()
        self._fallback_lock_patch.start()
        self._schema_patch.start()

    def tearDown(self) -> None:
        self._schema_patch.stop()
        self._fallback_lock_patch.stop()
        self._lock_patch.stop()
        self._lock_tmp.cleanup()

    @staticmethod
    def _empty_pid_response(adapter: FeishuBaseAdapter) -> dict[str, object]:
        spec = adapter.mapping["fields"]["ttc_pid"]
        return {
            "data": {
                "field_id_list": [spec["field_id"]],
                "fields": [spec["name"]],
                "data": [],
                "record_id_list": [],
            }
        }

    def test_shared_sync_lock_path_is_the_unified_repo_lock(self) -> None:
        expected = Path(__file__).resolve().parents[1] / "data" / "ttc_sync.lock"

        self.assertTrue(TTC_SYNC_LOCK_PATH.is_absolute())
        self.assertEqual(TTC_SYNC_LOCK_PATH, expected)

    def test_ttc_create_holds_the_shared_sync_lock_around_exact_lookup(self) -> None:
        record = CandidateRecord(
            source_url="https://app.ttcadvisory.com/app/talent/PL1929736208728313856"
        )
        adapter = FeishuBaseAdapter(mapping_path=OTTO_MAPPING)
        events: list[str] = []

        class Lock:
            def __init__(self, path: Path, *, operation: str) -> None:
                self.path = path
                self.operation = operation

            def __enter__(self) -> None:
                events.append(f"enter:{self.operation}")

            def __exit__(self, *_args: object) -> None:
                events.append("exit")

        with patch("adapters.feishu_base.ExclusiveSyncLock", Lock), patch.object(
            adapter,
            "_create_record_unlocked",
            side_effect=lambda _record: events.append("write") or {"ok": True},
        ):
            adapter.create_record(record)

        self.assertEqual(events, ["enter:candidate-collector", "write", "exit"])

    def test_non_ttc_create_holds_the_shared_sync_lock_too(self) -> None:
        record = CandidateRecord(name="非 TTC 候选人")
        adapter = FeishuBaseAdapter(mapping_path=OTTO_MAPPING)
        events: list[str] = []

        class Lock:
            def __init__(self, path: Path, *, operation: str) -> None:
                self.path = path
                self.operation = operation

            def __enter__(self) -> None:
                events.append(f"enter:{self.operation}")

            def __exit__(self, *_args: object) -> None:
                events.append("exit")

        with patch("adapters.feishu_base.ExclusiveSyncLock", Lock), patch.object(
            adapter,
            "_create_record_unlocked",
            side_effect=lambda _record: events.append("write") or {"ok": True},
        ):
            adapter.create_record(record)

        self.assertEqual(events, ["enter:candidate-collector", "write", "exit"])

    def test_attachment_failure_never_deletes_the_created_record(self) -> None:
        adapter = FeishuBaseAdapter(mapping_path=OTTO_MAPPING)
        commands: list[str] = []

        def run_cli(*args: str, **_kwargs: object) -> dict[str, object]:
            commands.append(args[0])
            if args[0] == "+record-batch-create":
                return {"data": {"record_id_list": ["rec_keep_me"]}}
            if args[0] == "+record-upload-attachment":
                raise RuntimeError("ambiguous upload failure")
            return {}

        with tempfile.TemporaryDirectory() as tmpdir:
            attachment = Path(tmpdir) / "resume.pdf"
            attachment.write_bytes(b"resume")
            record = CandidateRecord(
                name="附件失败也保留行",
                original_attachment_path=str(attachment),
            )
            with patch.object(adapter, "_run_cli", side_effect=run_cli):
                with self.assertRaisesRegex(RuntimeError, "ambiguous upload failure"):
                    adapter.create_record(record)

        self.assertEqual(
            commands,
            ["+record-batch-create", "+record-upload-attachment"],
        )
        self.assertNotIn("+record-delete", commands)

    def test_direct_attachment_upload_holds_the_shared_sync_lock(self) -> None:
        adapter = FeishuBaseAdapter(mapping_path=OTTO_MAPPING)
        events: list[str] = []

        class Lock:
            def __init__(self, path: Path, *, operation: str) -> None:
                self.path = path
                self.operation = operation

            def __enter__(self) -> None:
                events.append(f"enter:{self.operation}")

            def __exit__(self, *_args: object) -> None:
                events.append("exit")

        with patch("adapters.feishu_base.ExclusiveSyncLock", Lock), patch.object(
            adapter,
            "_upload_attachment_unlocked",
            side_effect=lambda *_args: events.append("upload") or "file_token",
        ):
            token = adapter.upload_attachment(
                "/tmp/resume.pdf",
                "rec_1",
                "fld_resume",
            )

        self.assertEqual(token, "file_token")
        self.assertEqual(events, ["enter:candidate-collector", "upload", "exit"])

    def test_attachment_retry_reads_back_matching_hash_before_append(self) -> None:
        adapter = FeishuBaseAdapter(mapping_path=OTTO_MAPPING)
        sha_spec = adapter.mapping["fields"]["attachment_sha256"]
        attachment_spec = adapter.mapping["fields"]["resume_attachment"]
        response = {
            "data": {
                "field_id_list": [sha_spec["field_id"], attachment_spec["field_id"]],
                "fields": [sha_spec["name"], attachment_spec["name"]],
                "data": [["abc123", [{"file_token": "file_existing"}]]],
                "record_id_list": ["rec_1"],
            }
        }
        with patch.object(adapter, "_run_cli", return_value=response), patch.object(
            adapter,
            "_upload_attachment_unlocked",
        ) as upload:
            token = adapter.upload_attachment(
                "/tmp/not-read-because-remote-exists.pdf",
                "rec_1",
                attachment_spec["field_id"],
                expected_sha256="abc123",
            )
        self.assertEqual(token, "already-present")
        upload.assert_not_called()

    def test_missing_attachment_fails_before_feishu_create(self) -> None:
        adapter = FeishuBaseAdapter(mapping_path=OTTO_MAPPING)
        record = CandidateRecord(
            name="附件已删除",
            original_attachment_path="/tmp/definitely-missing-ttc-resume.pdf",
        )
        with patch.object(adapter, "_run_cli") as run_cli:
            with self.assertRaises(FileNotFoundError):
                adapter.create_record(record)
        run_cli.assert_not_called()

    def test_ambiguous_network_create_is_not_retried(self) -> None:
        adapter = FeishuBaseAdapter(mapping_path=OTTO_MAPPING)
        result = unittest.mock.Mock(
            returncode=0,
            stdout='{"error":{"type":"network"}}',
            stderr="",
        )

        with patch(
            "adapters.feishu_base.subprocess.run",
            return_value=result,
        ) as run, patch("time.sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, "ambiguous write"):
                adapter.create_record(CandidateRecord(name="不盲重试"))

        self.assertEqual(run.call_count, 1)
        sleep.assert_not_called()

    def test_rate_limited_attachment_write_is_not_retried(self) -> None:
        adapter = FeishuBaseAdapter(mapping_path=OTTO_MAPPING)
        result = unittest.mock.Mock(
            returncode=0,
            stdout='{"error":{"code":800004135}}',
            stderr="",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            attachment = Path(tmpdir) / "resume.pdf"
            attachment.write_bytes(b"resume")
            with patch(
                "adapters.feishu_base.subprocess.run",
                return_value=result,
            ) as run, patch("time.sleep") as sleep:
                with self.assertRaisesRegex(RuntimeError, "ambiguous write"):
                    adapter.upload_attachment(
                        attachment,
                        "rec_1",
                        "fld_resume",
                    )

        self.assertEqual(run.call_count, 1)
        sleep.assert_not_called()

    def test_ambiguous_read_can_retry_safely(self) -> None:
        pid = "PL1833858043295301632"
        record = CandidateRecord(source_record_id=pid)
        adapter = FeishuBaseAdapter(mapping_path=OTTO_MAPPING)
        pid_field = adapter.mapping["fields"]["ttc_pid"]
        network_result = unittest.mock.Mock(
            returncode=0,
            stdout='{"error":{"type":"network"}}',
            stderr="",
        )
        exact_result = unittest.mock.Mock(
            returncode=0,
            stdout=json.dumps(
                {
                    "data": {
                        "field_id_list": [pid_field["field_id"]],
                        "fields": [pid_field["name"]],
                        "data": [[pid]],
                        "record_id_list": ["rec_exact_pid"],
                    }
                },
                ensure_ascii=False,
            ),
            stderr="",
        )

        with patch(
            "adapters.feishu_base.subprocess.run",
            side_effect=[network_result, exact_result],
        ) as run, patch("time.sleep") as sleep:
            self.assertTrue(adapter.record_exists(record))

        self.assertEqual(run.call_count, 2)
        sleep.assert_called_once_with(2)

    def test_record_exists_uses_exact_talent_url_filter_and_verifies_returned_cell(self) -> None:
        canonical_url = "https://app.ttcadvisory.com/app/talent/PL1833858043295301632"
        record = CandidateRecord(name="同名候选人", source_url=canonical_url)
        adapter = FeishuBaseAdapter(mapping_path=OTTO_MAPPING)
        link_field = adapter.mapping["fields"]["original_talent_link"]
        response = {
            "data": {
                "field_id_list": [link_field["field_id"]],
                "fields": [link_field["name"]],
                "data": [[canonical_url]],
                "record_id_list": ["rec_exact_pid"],
            }
        }

        with patch.object(
            adapter,
            "_run_cli",
            side_effect=[self._empty_pid_response(adapter), response],
        ) as run_cli:
            self.assertTrue(adapter.record_exists(record))

        self.assertEqual(run_cli.call_count, 2)
        args = run_cli.call_args_list[-1].args
        self.assertEqual(args[0], "+record-list")
        filter_json = args[args.index("--filter-json") + 1]
        self.assertIn('"=="', filter_json)
        self.assertIn(canonical_url, filter_json)
        self.assertNotIn("+record-search", args)
        first_args = run_cli.call_args_list[0].args
        self.assertEqual(
            first_args[first_args.index("--field-id") + 1],
            adapter.mapping["fields"]["ttc_pid"]["field_id"],
        )

    def test_near_match_from_remote_is_not_a_duplicate_and_never_falls_back_to_name(self) -> None:
        canonical_url = "https://app.ttcadvisory.com/app/talent/PL1833858043295301632"
        record = CandidateRecord(name="会重名", source_url=canonical_url)
        adapter = FeishuBaseAdapter(mapping_path=OTTO_MAPPING)
        link_field = adapter.mapping["fields"]["original_talent_link"]
        response = {
            "data": {
                "field_id_list": [link_field["field_id"]],
                "fields": [link_field["name"]],
                "data": [[canonical_url + "/"]],
                "record_id_list": ["rec_near_match"],
            }
        }

        with patch.object(
            adapter,
            "_run_cli",
            side_effect=[self._empty_pid_response(adapter), response],
        ) as run_cli:
            self.assertFalse(adapter.record_exists(record))

        self.assertEqual(run_cli.call_count, 2)
        self.assertEqual(run_cli.call_args_list[-1].args[0], "+record-list")

    def test_incomplete_filtered_page_without_exact_match_fails_closed(self) -> None:
        canonical_url = "https://app.ttcadvisory.com/app/talent/PL1833858043295301632"
        record = CandidateRecord(source_url=canonical_url)
        adapter = FeishuBaseAdapter(mapping_path=OTTO_MAPPING)
        link_field = adapter.mapping["fields"]["original_talent_link"]
        response = {
            "data": {
                "field_id_list": [link_field["field_id"]],
                "fields": [link_field["name"]],
                "data": [[canonical_url + "/"]],
                "record_id_list": ["rec_unrelated"],
                "has_more": True,
            }
        }

        with patch.object(
            adapter,
            "_run_cli",
            side_effect=[self._empty_pid_response(adapter), response],
        ):
            with self.assertRaises(RuntimeError):
                adapter.record_exists(record)

    def test_multiple_exact_pid_rows_fail_closed(self) -> None:
        canonical_url = "https://app.ttcadvisory.com/app/talent/PL1833858043295301632"
        record = CandidateRecord(source_url=canonical_url)
        adapter = FeishuBaseAdapter(mapping_path=OTTO_MAPPING)
        link_field = adapter.mapping["fields"]["original_talent_link"]
        response = {
            "data": {
                "field_id_list": [link_field["field_id"]],
                "fields": [link_field["name"]],
                "data": [[canonical_url], [canonical_url]],
                "record_id_list": ["rec_duplicate_1", "rec_duplicate_2"],
            }
        }

        with patch.object(
            adapter,
            "_run_cli",
            side_effect=[self._empty_pid_response(adapter), response],
        ):
            with self.assertRaisesRegex(RuntimeError, "Multiple exact TTC"):
                adapter.record_exists(record)

    def test_mapped_ttc_pid_field_is_preferred_over_talent_url(self) -> None:
        pid = "PL1833858043295301632"
        record = CandidateRecord(source_record_id=pid)
        adapter = FeishuBaseAdapter(mapping_path=OTTO_MAPPING)
        adapter.mapping["fields"]["ttc_pid"] = {
            "name": "TTC PID",
            "field_id": "fld_ttc_pid",
            "type": "text",
            "candidate_field": "source_record_id",
        }
        response = {
            "data": {
                "field_id_list": ["fld_ttc_pid"],
                "fields": ["TTC PID"],
                "data": [[pid]],
                "record_id_list": ["rec_by_pid"],
            }
        }

        with patch.object(adapter, "_run_cli", return_value=response) as run_cli:
            self.assertTrue(adapter.record_exists(record))

        self.assertEqual(run_cli.call_count, 1)
        args = run_cli.call_args.args
        self.assertEqual(args[args.index("--field-id") + 1], "fld_ttc_pid")
        self.assertIn(pid, args[args.index("--filter-json") + 1])

    def test_create_record_is_idempotent_even_when_caller_skips_precheck(self) -> None:
        canonical_url = "https://app.ttcadvisory.com/app/talent/PL1929736208728313856"
        record = CandidateRecord(name="重复运行", source_url=canonical_url)
        adapter = FeishuBaseAdapter(mapping_path=OTTO_MAPPING)
        link_field = adapter.mapping["fields"]["original_talent_link"]
        response = {
            "data": {
                "field_id_list": [link_field["field_id"]],
                "fields": [link_field["name"]],
                "data": [[canonical_url]],
                "record_id_list": ["rec_already_there"],
            }
        }

        with patch.object(
            adapter,
            "_run_cli",
            side_effect=[self._empty_pid_response(adapter), response],
        ) as run_cli:
            result = adapter.create_record(record)

        self.assertTrue(result["idempotent_existing"])
        self.assertEqual(result["data"]["record_id_list"], ["rec_already_there"])
        self.assertEqual(run_cli.call_count, 2)
        self.assertNotIn("+record-batch-create", run_cli.call_args_list[-1].args)


class TtcLocalDedupTests(unittest.TestCase):
    def test_local_dedup_matches_same_pid_but_allows_same_person_fields_with_new_pid(self) -> None:
        first = CandidateRecord(
            name="同名候选人",
            phone="13812345678",
            attachment_sha256="same-file",
            source_url="https://app.ttcadvisory.com/app/talent/PL1833858043295301632",
        )
        second = CandidateRecord(
            name=first.name,
            phone=first.phone,
            attachment_sha256=first.attachment_sha256,
            source_url="https://app.ttcadvisory.com/app/talent/PL1929736208728313856",
        )

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            pipeline, "DB_PATH", Path(tmpdir) / "candidates.db"
        ):
            pipeline.init_ingestion_tables()
            with sqlite3.connect(pipeline.DB_PATH) as conn:
                conn.execute(
                    """
                    INSERT INTO ingestion_log (
                        fingerprint, attachment_sha256, phone, name,
                        feishu_write_status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'success', datetime('now'), datetime('now'))
                    """,
                    (
                        pipeline.record_fingerprint(first),
                        first.attachment_sha256,
                        first.phone,
                        first.name,
                    ),
                )

            self.assertIsNotNone(pipeline.local_duplicate_exists(first))
            self.assertIsNone(pipeline.local_duplicate_exists(second))

    def test_ingest_file_reports_remote_pid_as_skipped_not_created(self) -> None:
        record = CandidateRecord(
            name="已经存在",
            source_url="https://app.ttcadvisory.com/app/talent/PL1833858043295301632",
        )
        adapter = unittest.mock.Mock()
        # pipeline 投递层经 upsert_record 写入（指纹判重，内部回退 create_record）
        adapter.upsert_record.return_value = {
            "data": {"record_id_list": ["rec_existing"]},
            "idempotent_existing": True,
            "ttc_pid": record.ttc_pid,
        }
        adapter.dry_run.return_value = {"action": "dry_run"}

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            pipeline, "DB_PATH", Path(tmpdir) / "candidates.db"
        ), patch.object(
            pipeline, "parse_resume_file", return_value=record
        ), patch.object(
            pipeline, "FeishuBaseAdapter", return_value=adapter
        ), patch.object(
            # 单测不触达真实 RDS
            pipeline, "_sync_to_cloud", return_value={"status": "success"}
        ):
            result = pipeline.ingest_file(
                Path(tmpdir) / "unused.pdf",
                dry_run=False,
                check_feishu_exists=False,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "skipped_duplicate_feishu")
        self.assertEqual(result["feishu_record_id"], "rec_existing")

    def test_ingest_file_derives_source_record_id_after_source_url_override(self) -> None:
        record = CandidateRecord(name="后设来源链接")
        canonical_url = "https://app.ttcadvisory.com/app/talent/PL1929736208728313856"
        adapter = unittest.mock.Mock()
        adapter.dry_run.return_value = {"action": "dry_run"}

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            pipeline, "DB_PATH", Path(tmpdir) / "candidates.db"
        ), patch.object(
            pipeline, "parse_resume_file", return_value=record
        ), patch.object(
            pipeline, "FeishuBaseAdapter", return_value=adapter
        ):
            result = pipeline.ingest_file(
                Path(tmpdir) / "unused.pdf",
                dry_run=True,
                source_url=canonical_url,
            )
            with sqlite3.connect(pipeline.DB_PATH) as conn:
                logged_source_record_id = conn.execute(
                    "SELECT source_record_id FROM ingestion_log"
                ).fetchone()[0]

        self.assertEqual(
            result["candidate"]["source_record_id"],
            "PL1929736208728313856",
        )
        self.assertEqual(logged_source_record_id, "PL1929736208728313856")


class TtcBrowserCaptureTests(unittest.TestCase):
    def test_idempotent_adapter_response_is_reported_as_skipped(self) -> None:
        adapter = unittest.mock.Mock()
        adapter.create_record.return_value = {
            "data": {"record_id_list": ["rec_existing"]},
            "idempotent_existing": True,
            "ttc_pid": "PL1833858043295301632",
        }
        adapter.dry_run.return_value = {"action": "dry_run"}
        payload = browser_capture.BrowserCapturePayload(
            url="https://app.ttcadvisory.com/app/talent/PL1833858043295301632",
            text="候选人资料内容足够用于浏览器导入测试",
            dry_run=False,
            check_feishu_exists=False,
        )

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            pipeline, "DB_PATH", Path(tmpdir) / "candidates.db"
        ), patch.object(
            browser_capture, "DB_PATH", Path(tmpdir) / "candidates.db"
        ):
            result = browser_capture.import_browser_capture(
                payload,
                feishu_adapter=adapter,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "skipped_duplicate_feishu")
        self.assertEqual(result["feishu_record_id"], "rec_existing")

    def test_new_adapter_response_remains_created(self) -> None:
        adapter = unittest.mock.Mock()
        adapter.create_record.return_value = {
            "data": {"record_id_list": ["rec_new"]},
        }
        adapter.dry_run.return_value = {"action": "dry_run"}
        payload = browser_capture.BrowserCapturePayload(
            url="https://example.com/candidate/new",
            text="候选人资料内容足够用于普通浏览器导入测试",
            dry_run=False,
        )

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(
            pipeline, "DB_PATH", Path(tmpdir) / "candidates.db"
        ), patch.object(
            browser_capture, "DB_PATH", Path(tmpdir) / "candidates.db"
        ):
            result = browser_capture.import_browser_capture(
                payload,
                feishu_adapter=adapter,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "created")
        self.assertEqual(result["feishu_record_id"], "rec_new")


if __name__ == "__main__":
    unittest.main()
