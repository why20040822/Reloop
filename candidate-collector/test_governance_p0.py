"""P0 治理回归测试：quality 闸门 / 指纹统一 / transform 修复 / 统一入口。

跑法：cd candidate-collector && .venv/bin/python -m pytest test_governance_p0.py -q
（端到端用例需要 .env 里的 RDS 凭据，自动 skip 无凭据环境）
"""
from __future__ import annotations

import hashlib
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import CandidateRecord
from quality import RAW_TEXT_MIN_CHARS, evaluate_quality
from cloud_sync.config import rds_configured
from cloud_sync.transform import candidate_record_to_cloud, sqlite_row_to_cloud


# ── quality.py 纯函数 ─────────────────────────────────────────────

def _full_text() -> str:
    return "这是一份完整简历。" * 30  # > RAW_TEXT_MIN_CHARS


def test_quality_full_marks():
    record = CandidateRecord(
        name="张三",
        phone="13800138000",
        raw_text=_full_text(),
        expected_title="产品经理",
        expected_salary="30-40K",
    )
    score, missing = evaluate_quality(record)
    assert score == 1.0
    assert missing == []


def test_quality_all_missing():
    record = CandidateRecord(name="张三", raw_text="")
    score, missing = evaluate_quality(record)
    assert score == 0.0
    assert set(missing) == {"complete_resume", "phone", "intent", "salary_level"}


def test_quality_raw_text_fallback():
    """结构化列为空时，raw_text 关键词兜底意向/薪资。"""
    record = CandidateRecord(
        name="李四",
        phone="13900139000",
        raw_text=_full_text() + "\n求职意向：品牌总监\n期望薪资：40-50K",
    )
    score, missing = evaluate_quality(record)
    assert score == 1.0
    assert missing == []


def test_quality_short_resume_not_complete():
    record = CandidateRecord(
        name="王五",
        phone="13700137000",
        raw_text="x" * (RAW_TEXT_MIN_CHARS - 1),
        expected_title="顾问",
        expected_salary="20K",
    )
    score, missing = evaluate_quality(record)
    assert score == 0.75
    assert missing == ["complete_resume"]


def test_quality_dict_input():
    score, missing = evaluate_quality({"raw_text": _full_text(), "phone": "13111111111"})
    assert score == 0.5
    assert set(missing) == {"intent", "salary_level"}


# ── R5 指纹统一 ───────────────────────────────────────────────────

def test_fingerprint_unified_across_entries():
    """同一个人，不同入口构造的 CandidateRecord → 同一行指纹。"""
    base = dict(name="赵六", phone="13600136000", current_company="Acme", current_title="顾问")
    via_mcp = CandidateRecord(**base, source_platform="manual", source_type="manual")
    via_pipeline = CandidateRecord(**base, source_platform="boss", source_type="browser_capture")

    fp1 = candidate_record_to_cloud(via_mcp)["fingerprint"]
    fp2 = candidate_record_to_cloud(via_pipeline)["fingerprint"]
    expected = hashlib.sha256(via_mcp.fingerprint_input().encode("utf-8")).hexdigest()
    assert fp1 == fp2 == expected


def test_fingerprint_ignores_browser_capture_fingerprint():
    """extra.browser_capture_fingerprint 不再充当行指纹（R5）。"""
    record = CandidateRecord(
        name="赵六", phone="13600136000",
        extra={"browser_capture_fingerprint": "legacy-browser-fp"},
    )
    row = candidate_record_to_cloud(record)
    assert row["fingerprint"] != "legacy-browser-fp"
    assert row["fingerprint"] == hashlib.sha256(
        record.fingerprint_input().encode("utf-8")
    ).hexdigest()


def test_fingerprint_source_record_id_chain():
    record = CandidateRecord(
        name="钱七", source_platform="ttc_daemon", source_record_id="cand_abc123"
    )
    row = candidate_record_to_cloud(record)
    expected = hashlib.sha256(b"source_record|ttc_daemon|cand_abc123").hexdigest()
    assert row["fingerprint"] == expected


# ── transform.py 修复回归 ─────────────────────────────────────────

def test_sqlite_row_to_cloud_no_nameerror():
    """修复前此调用必崩（activity_score/signals 两个 NameError）。"""
    row = {
        "id": 42, "fingerprint": "legacy-fp", "name": "测试",
        "platform": "local_file", "raw_text": "内容",
    }
    cloud = sqlite_row_to_cloud(row)
    assert cloud["fingerprint"] == "legacy-fp"
    assert cloud["activity_score"] == 0
    assert cloud["activity_signals"] == "{}"


def test_sqlite_row_to_cloud_no_str_id_fingerprint():
    """str(id) 自造指纹已移除，走规范兜底链。"""
    row = {"id": 42, "name": "测试", "current_company": "公司", "phone": "13500135000"}
    cloud = sqlite_row_to_cloud(row)
    assert cloud["fingerprint"] != "42"
    assert cloud["fingerprint"] == hashlib.sha256(b"phone|13500135000").hexdigest()


def test_candidate_record_to_cloud_intent_columns():
    record = CandidateRecord(
        name="孙八", expected_title="投资经理", opportunity_intent="考虑机会"
    )
    row = candidate_record_to_cloud(record)
    assert row["expected_title"] == "投资经理"
    assert row["opportunity_intent"] == "考虑机会"


# ── client.py R7：错误抛出 ────────────────────────────────────────

def test_upsert_raises_on_row_error():
    """行级失败必须抛 UpsertError（R7），不再静默 errors+=1。"""
    pytest.importorskip("pymysql")
    if not rds_configured():
        pytest.skip("RDS 未配置")
    from cloud_sync.client import CloudSyncClient, UpsertError

    with pytest.raises(UpsertError):
        CloudSyncClient().upsert_candidates([{"name": "缺 fingerprint 的坏行"}])


# ── 端到端：统一入口写 live RDS ──────────────────────────────────

@pytest.mark.skipif(not rds_configured(), reason="RDS 未配置")
def test_entry_end_to_end_live():
    """entry.ingest_record 写测试人 → 回读验证质量列 → 清理。"""
    from cloud_sync.client import get_conn
    from ingestion.entry import ingest_record

    marker = uuid.uuid4().hex[:8]
    record = CandidateRecord(
        name=f"治理探针{marker}",
        phone="13000000000",
        raw_text=_full_text() + "\n求职意向：架构师\n期望薪资：50K",
        source_platform="governance_probe",
        source_type="governance_probe",
        source_record_id=f"probe-{marker}",
    )
    result = ingest_record(record)
    try:
        assert result.stats["errors"] == 0
        assert result.quality_score == 1.0
        assert result.cloud_record_id

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT quality_score, missing_fields, activity_score, visibility "
                    "FROM cloud_candidates WHERE fingerprint = %s",
                    (result.fingerprint,),
                )
                row = cur.fetchone()
        assert row is not None
        assert float(row[0]) == 1.0
        assert row[1] == "[]"
        assert row[2] >= 0  # 6 列已补回，可正常读写
        assert row[3] == "team"
    finally:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM cloud_candidates WHERE fingerprint = %s",
                    (result.fingerprint,),
                )
