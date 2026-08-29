"""方案①: 详情接口返回完整 resume_text, 列表 slim 置空。"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("BRAINX_DATABASE_URL", "sqlite:///./test_local.db")
os.environ.setdefault("BRAINX_LLM_API_KEY", "")
os.environ.setdefault("BRAINX_AUTH_REQUIRE_TOKEN", "false")

from fastapi.testclient import TestClient  # noqa: E402

from reloop.db.engine import SessionLocal, init_db  # noqa: E402
from reloop.db.models import TalentProfile  # noqa: E402
from reloop.main import app  # noqa: E402

OWNER = "ou_resume_test"
FULL_TEXT = "张韵 | 字节跳动 商业分析师\n技能: SQL Python 大模型\n工作经历: 字节跳动 商业分析师 (2020.03-至今)\n负责增长分析…"


def _seed():
    init_db()
    db = SessionLocal()
    try:
        if not db.query(TalentProfile).filter(TalentProfile.owner_user_id == OWNER).first():
            db.add(TalentProfile(owner_user_id=OWNER, source_id="RT-1", name="张韵",
                                 company="字节跳动", resume_text=FULL_TEXT))
            db.add(TalentProfile(owner_user_id=OWNER, source_id="RT-2", name="无简历的人",
                                 resume_text=None))
            db.commit()
    finally:
        db.close()


def _client():
    return TestClient(app)


def test_detail_returns_full_resume_text():
    _seed()
    c = _client()
    db = SessionLocal()
    try:
        tid = db.query(TalentProfile).filter_by(owner_user_id=OWNER, source_id="RT-1").first().id
    finally:
        db.close()
    r = c.get(f"/talents/{tid}", headers={"X-Owner-User-Id": OWNER})
    assert r.status_code == 200
    body = r.json()
    assert body["resume_text"] == FULL_TEXT, "详情接口应返回完整简历文本"
    assert "工作经历" in body["resume_text"]


def test_detail_null_resume_text_ok():
    _seed()
    c = _client()
    db = SessionLocal()
    try:
        tid = db.query(TalentProfile).filter_by(owner_user_id=OWNER, source_id="RT-2").first().id
    finally:
        db.close()
    r = c.get(f"/talents/{tid}", headers={"X-Owner-User-Id": OWNER})
    assert r.status_code == 200
    assert r.json()["resume_text"] is None


def test_slim_list_blanks_resume_text():
    _seed()
    c = _client()
    r = c.get("/talents?slim=1", headers={"X-Owner-User-Id": OWNER})
    assert r.status_code == 200
    for item in r.json():
        assert item["resume_text"] is None, "slim 列表必须置空 resume_text(轻量载荷)"
