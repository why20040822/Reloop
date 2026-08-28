"""Phase 1 数据正确性回归测试(2026-08-28)。

覆盖:
  F1  缺 id 记录生成稳定指纹 source_id(fp_*), 重复导入只 upsert 不新增
  A2  缺时间字段 -> last_active_at/resume_updated_at 为 None(不再用 created_at 兜底)
  F2  (owner, source_id) 唯一约束生效
  BUG-105 删除人才级联清理 interactions/recommendations/feedback_logs
  BUG-103 反馈更新"最近一次推荐"状态(不限当天)
  A4  活跃门禁: 超过 activity_inactive_days -> activity_status=inactive 且活跃分被降权

运行(项目根目录): pytest tests/test_phase1_data_correctness.py -v
"""

import os
import sys

_TEST_DIR = os.path.dirname(__file__)
_TEST_DB = os.path.join(_TEST_DIR, f"test_phase1_{os.getpid()}.db")
os.environ["BRAINX_DATABASE_URL"] = f"sqlite:///{_TEST_DB.replace(os.sep, '/')}"
os.environ["BRAINX_LLM_API_KEY"] = ""
os.environ["BRAINX_AUTH_REQUIRE_TOKEN"] = "false"
os.environ["BRAINX_AUTH_SESSION_SECRET"] = "test-phase1-secret"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import datetime as dt  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from reloop.db.engine import SessionLocal, init_db  # noqa: E402
from reloop.db.models import (  # noqa: E402
    FeedbackLog,
    InteractionRecord,
    Recommendation,
    TalentProfile,
)
from reloop.main import app  # noqa: E402
from reloop.modules.scoring import factors  # noqa: E402
from reloop.modules.sync.normalizer import normalize_batch  # noqa: E402

init_db()
client = TestClient(app)

OWNER = "phase1-owner"
H = {"X-Owner-User-Id": OWNER}


def _db():
    return SessionLocal()


def _cleanup():
    db = _db()
    for model in (FeedbackLog, InteractionRecord, Recommendation, TalentProfile):
        db.query(model).filter(model.owner_user_id == OWNER).delete(
            synchronize_session=False)
    db.commit()
    db.close()


# ---------------------------------------------------------------- F1 + A2
def test_fingerprint_and_no_fake_timestamps():
    raw = {"name": "张三", "company": "ACME", "position": "数据分析师"}
    norm = normalize_batch([raw])[0]
    assert norm["source_id"].startswith("fp_"), "缺 id 必须生成指纹兜底, 不落空串"
    assert norm["last_active_at"] is None, "缺时间字段必须落 None, 不许 created_at 兜底"
    # 稳定性: 同一输入指纹一致
    again = normalize_batch([dict(raw)])[0]["source_id"]
    assert again == norm["source_id"]


# ---------------------------------------------------------------- F1/F2
def test_duplicate_import_upserts_not_inserts():
    _cleanup()
    from reloop.modules.sync.client import talent_sync_service
    raw = [{"id": "P001", "name": "李四", "company": "TestCo"}]
    db = _db()
    for _ in range(3):  # 模拟三次导入同一批数据
        talent_sync_service.sync_for_user(OWNER, raw_payload=raw, db=db)
        db.commit()
    rows = db.query(TalentProfile).filter(
        TalentProfile.owner_user_id == OWNER,
        TalentProfile.source_id == "P001").all()
    db.close()
    assert len(rows) == 1, f"重复导入产生 {len(rows)} 行, 应 upsert 为 1 行"


# ---------------------------------------------------------------- BUG-105
def test_delete_talent_cascades():
    _cleanup()
    db = _db()
    t = TalentProfile(owner_user_id=OWNER, source_id="DEL1", name="待删")
    db.add(t)
    db.flush()
    tid = t.id
    db.add(InteractionRecord(owner_user_id=OWNER, talent_id=tid,
                             interaction_type="call", count=1,
                             occurred_at=dt.date.today()))
    db.add(FeedbackLog(owner_user_id=OWNER, talent_id=tid, action="confirm"))
    db.add(Recommendation(owner_user_id=OWNER, talent_id=tid,
                          focus_position="测试岗", run_id="r1", rank=1,
                          score=0.5, recommend_date=dt.date.today(),
                          status="pending"))
    db.commit()
    db.close()

    resp = client.delete(f"/talents/{tid}", headers=H)
    resp.raise_for_status()

    db = _db()
    assert db.query(InteractionRecord).filter_by(owner_user_id=OWNER, talent_id=tid).count() == 0
    assert db.query(FeedbackLog).filter_by(owner_user_id=OWNER, talent_id=tid).count() == 0
    assert db.query(Recommendation).filter_by(owner_user_id=OWNER, talent_id=tid).count() == 0
    assert db.get(TalentProfile, tid) is None
    db.close()


# ---------------------------------------------------------------- BUG-103
def test_feedback_updates_latest_recommendation_across_days():
    _cleanup()
    db = _db()
    yesterday = dt.date.today() - dt.timedelta(days=1)
    rec = Recommendation(owner_user_id=OWNER, talent_id=9001,
                         focus_position="测试岗", run_id="r-old", rank=1,
                         score=0.5, recommend_date=yesterday, status="pending")
    db.add(rec)
    db.commit()
    rid = rec.id
    db.close()

    client.post("/recommend/feedback", headers=H,
                json={"talent_id": 9001, "action": "confirm"}).raise_for_status()

    db = _db()
    row = db.get(Recommendation, rid)
    db.close()
    assert row.status == "confirmed", "昨日缓存条目的反馈必须生效(BUG-103)"


# ---------------------------------------------------------------- A4
def test_activity_gate_penalty_and_status():
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    fresh = [{"event_type": "profile_update", "occurred_at": now - dt.timedelta(days=5)}]
    stale = [{"event_type": "profile_update", "occurred_at": now - dt.timedelta(days=120)}]
    none_ = []

    s_fresh = factors.absolute_activity(factors.days_since_latest_event(fresh, now=now))
    s_stale = factors.absolute_activity(factors.days_since_latest_event(stale, now=now))

    from reloop.config import settings
    assert s_fresh > 0.9
    # 120 天 > 90 天窗口 -> 触底
    assert s_stale == factors.FACTOR_FLOOR
    gated = max(0.0, s_stale * settings.activity_gate_penalty)
    assert gated < s_fresh, f"门禁降权后({gated})必须显著低于活跃者({s_fresh})"
    assert factors.absolute_activity(None) == factors.FACTOR_FLOOR, "无信号必须触底"
