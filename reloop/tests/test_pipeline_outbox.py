from __future__ import annotations

from unittest.mock import patch

from reloop.ingestion.delivery import DeliveryStore
from reloop.ingestion.pipeline import ingest_text


def test_write_mode_commits_outbox_without_direct_feishu_call(tmp_path):
    database = tmp_path / "pipeline.db"
    with (
        patch("reloop.ingestion.pipeline.DB_PATH", database),
        patch("reloop.ingestion.delivery.DB_PATH", database),
        patch("reloop.ingestion.pipeline.FeishuBaseAdapter") as adapter_class,
    ):
        result = ingest_text(
            "王小明\n13812345678\n字节跳动 产品经理",
            title="测试简历",
            dry_run=False,
        )

    assert result["ok"] is True
    assert result["action"] == "queued"
    assert result["cloud_status"] == "blocked"
    assert result["feishu_status"] == "blocked"
    adapter_class.return_value.create_record.assert_not_called()
    job = DeliveryStore(database).get(result["job_id"])
    assert job is not None
    assert job.fingerprint == result["fingerprint"]
    assert job.local_status == "queued"
