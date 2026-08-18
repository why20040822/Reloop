"""真实同步路径回归测试: 走 HTTP /sync/ttc/ingest, 用独立新会话断言真落库。

这补上了 test_pipeline.py 的盲区 —— 那个测试直接调 structuring_service,
绕过了真实接口用的 talent_sync_service; 本测试确保:
  1. /sync/ttc/ingest 的数据【真的落库】(用新会话查, 而非同会话缓存)
  2. 同步后每个人的 value_score / resume_embedding 【非空】(结构化生效)
  3. 推荐分数【有区分度】(不再因五因子全空恒等于 0.5)
  4. 粗筛【召回相关但异名】的候选人(修复整串子串匹配漏召回)

运行:
    python tests/test_sync_pipeline.py   # 或 pytest tests/test_sync_pipeline.py -v
"""

import os
import sys

_TEST_DB = os.path.join(os.path.dirname(__file__), "test_sync.db")
os.environ["BRAINX_DATABASE_URL"] = f"sqlite:///{_TEST_DB.replace(os.sep, '/')}"
os.environ["BRAINX_LLM_API_KEY"] = ""  # 强制离线降级

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from reloop.db.engine import SessionLocal, init_db  # noqa: E402
from reloop.db.models import TalentProfile  # noqa: E402
from reloop.main import app  # noqa: E402

OWNER = "ou_sync_test"
TALENTS = [
    {"id": "S1", "姓名": "张韵", "公司": "字节跳动", "职位": "商业分析师",
     "经验": "6年", "学历": "硕士", "技能": "SQL, Python, 大模型", "最近活跃": "1天前"},
    {"id": "S2", "姓名": "李哲", "公司": "腾讯", "职位": "数据产品经理",
     "经验": "8年", "学历": "本科", "技能": "数据分析, SQL", "最近活跃": "3天前"},
    {"id": "S3", "姓名": "王楠", "公司": "初创公司", "职位": "HR专员",
     "经验": "2年", "学历": "大专", "技能": "行政", "最近活跃": "20天前"},
]


def run() -> int:
    init_db()
    c = TestClient(app)
    H = {"X-Owner-User-Id": OWNER}

    # 1. 走真实 HTTP 同步接口
    r = c.post("/sync/ttc/ingest", headers=H, json={"talents": TALENTS})
    assert r.status_code == 200 and r.json()["synced"] == 3, r.text
    print("[1] ingest OK: synced=3")

    # 2. 独立新会话断言【真落库】+ 结构化字段非空
    db = SessionLocal()
    try:
        rows = db.query(TalentProfile).filter(
            TalentProfile.owner_user_id == OWNER).all()
        assert len(rows) == 3, f"应真落库 3 人, 实际 {len(rows)}(数据静默丢失回归!)"
        for row in rows:
            assert row.value_score is not None, f"{row.name} value_score 为空(结构化被跳过回归!)"
            assert row.resume_embedding, f"{row.name} resume_embedding 为空(向量未生成回归!)"
        print(f"[2] persisted OK: 新会话查到 3 人, value_score/embedding 全部非空")
    finally:
        db.close()

    # 3. 设岗 + 推荐: 召回相关异名候选人 + 分数有区分度
    c.post("/positions", headers=H,
           json={"position_name": "商业分析师", "jd_text": "数据分析 SQL Python 商业洞察"})
    rec = c.post("/recommend/compute?position_name=商业分析师", headers=H).json()
    assert rec["shortlisted"] >= 2, \
        f"粗筛应召回张韵+李哲(异名相关), 实际 {rec['shortlisted']}(漏召回回归!)"
    scores = [it["score"] for it in rec["top10"]]
    assert len(set(scores)) > 1, f"分数应有区分度, 实际全相等={scores}(五因子失效回归!)"
    assert set(scores) != {0.5}, "分数恒 0.5(结构化断裂回归!)"
    print(f"[3] recommend OK: shortlisted={rec['shortlisted']}, "
          f"scores={sorted(set(scores), reverse=True)} 有区分度")

    # 4. 互动反哺 + 反馈闭环
    tid = rec["top10"][0]["talent_id"]
    assert c.post(f"/talents/{tid}/interaction", headers=H,
                  json={"interaction_type": "call", "count": 2}).status_code == 200
    rec2 = c.post("/recommend/compute?position_name=商业分析师", headers=H).json()
    assert rec2["top10"][0]["score_breakdown"]["relationship"] > 0.5, "互动未反哺历史关系"
    assert c.post("/recommend/feedback", headers=H,
                  json={"talent_id": tid, "action": "confirm"}).json()["ok"]
    print("[4] interaction+feedback OK: 关系因子随互动升高, 反馈写回成功")

    print("\n=== 真实同步路径闭环测试通过: HTTP同步 -> 真落库 -> 结构化 -> 推荐区分 -> 反馈 ===")
    return 0


if __name__ == "__main__":
    try:
        code = run()
    finally:
        if os.path.exists(_TEST_DB):
            try:
                os.remove(_TEST_DB)
            except OSError:
                pass
    sys.exit(code)
