"""公司人才库补充(v2.1) 测试: 实时拉共享池 + 差异对比 + 缓存 + 异常路径。全部离线可跑。"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("BRAINX_DATABASE_URL", "sqlite:///./test_local.db")
os.environ.setdefault("BRAINX_LLM_API_KEY", "")
os.environ.setdefault("BRAINX_AUTH_REQUIRE_TOKEN", "false")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from reloop.db.engine import SessionLocal, init_db  # noqa: E402
from reloop.db.models import TalentProfile  # noqa: E402
from reloop.main import app  # noqa: E402
import reloop.modules.sync.company_pool as cp  # noqa: E402

OWNER = "ou_sup_test"

FAKE_POOL = [
    {"source_id": "CS-1", "notes": "公司库最新备注：重点跟进", "seek_status": "在职看机会",
     "current_salary": "25k", "last_active_at": "2026-08-27T10:00:00",
     "skills": ["SQL", "Python"]},
    {"source_id": "OTHER-9", "notes": "别人的记录"},
]

call_counter = {"n": 0}


def _fake_fetch_talents(self, *args, **kwargs):
    call_counter["n"] += 1
    return [dict(item) for item in FAKE_POOL]


def _seed():
    init_db()
    db = SessionLocal()
    try:
        if db.query(TalentProfile).filter(TalentProfile.owner_user_id == OWNER).count():
            return
        db.add(TalentProfile(
            owner_user_id=OWNER, source_id="CS-1", name="张韵",
            company="字节跳动", position="商业分析师",
            notes="本地旧备注", seek_status="已离职找工作",
            current_salary="20k",
        ))
        db.add(TalentProfile(owner_user_id=OWNER, source_id="CS-2", name="李哲", company="腾讯"))
        db.add(TalentProfile(owner_user_id=OWNER, name="无映射的人"))  # source_id 缺失
        db.commit()
    finally:
        db.close()


def _reset_snapshot():
    cp._snapshot = {"fetched_at": None, "by_sid": {}, "total": 0}
    call_counter["n"] = 0


@pytest.fixture()
def client(monkeypatch):
    _seed()
    _reset_snapshot()
    monkeypatch.setattr(cp.TTCClient, "fetch_talents", _fake_fetch_talents)
    return TestClient(app)


def _lookup_talent_id(source_id: str) -> int:
    db = SessionLocal()
    try:
        row = (
            db.query(TalentProfile)
            .filter(TalentProfile.owner_user_id == OWNER, TalentProfile.source_id == source_id)
            .first()
        )
        assert row is not None, f"seed 缺失 source_id={source_id}"
        return row.id
    finally:
        db.close()


def test_supplement_found_with_diff(client):
    tid = _lookup_talent_id("CS-1")
    r = client.get(f"/talents/{tid}/company-supplement", headers={"X-Owner-User-Id": OWNER})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["found"] is True
    assert body["supplement"]["notes"] == "公司库最新备注：重点跟进"
    assert body["supplement"]["seek_status"] == "在职看机会"
    # 差异清单: 本地 notes/seek_status/current_salary 均落后于公司库
    diff_fields = {d["field"] for d in body["diff"]}
    assert {"notes", "seek_status", "current_salary"} <= diff_fields
    notes_diff = next(d for d in body["diff"] if d["field"] == "notes")
    assert notes_diff["local"] == "本地旧备注"
    assert notes_diff["company"] == "公司库最新备注：重点跟进"


def test_supplement_not_found_in_pool(client):
    tid = _lookup_talent_id("CS-2")
    r = client.get(f"/talents/{tid}/company-supplement", headers={"X-Owner-User-Id": OWNER})
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is False
    assert "未找到" in body["message"]
    assert body["pool_total"] == 2, "快照应包含公司池全量 2 条"


def test_supplement_missing_source_id(client):
    db = SessionLocal()
    try:
        row = (
            db.query(TalentProfile)
            .filter(TalentProfile.owner_user_id == OWNER, TalentProfile.source_id.is_(None))
            .first()
        )
        assert row is not None
        tid = row.id
    finally:
        db.close()
    r = client.get(f"/talents/{tid}/company-supplement", headers={"X-Owner-User-Id": OWNER})
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is False
    assert "source_id 缺失" in body["message"]


def test_snapshot_ttl_cache_and_force(client):
    tid = _lookup_talent_id("CS-1")
    client.get(f"/talents/{tid}/company-supplement", headers={"X-Owner-User-Id": OWNER})
    client.get(f"/talents/{tid}/company-supplement", headers={"X-Owner-User-Id": OWNER})
    assert call_counter["n"] == 1, "TTL 内第二次查看不应重新拉公司池"
    client.get(f"/talents/{tid}/company-supplement?force=true", headers={"X-Owner-User-Id": OWNER})
    assert call_counter["n"] == 2, "force=true 应强制刷新快照"


def test_owner_isolation(client):
    tid = _lookup_talent_id("CS-1")
    r = client.get(f"/talents/{tid}/company-supplement", headers={"X-Owner-User-Id": "ou_other"})
    assert r.status_code in (403, 404), "他人人才不可见(数据隔离)"
