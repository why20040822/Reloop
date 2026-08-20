"""全流程测试: 同步 -> 结构化 -> 入库 -> 设岗 -> 引擎计算 -> TopN。

验证整条数据链路能否跑通。使用 SQLite 内存级别文件库(不碰 RDS),
LLM/TTC 未配 Key 时自动走离线降级(哈希向量/规则抽取), 因此无需任何
外部凭据即可运行。

运行(项目根目录):
    conda activate reloop
    python tests/test_pipeline.py

也可用 pytest 运行: pytest tests/test_pipeline.py -v
"""

import os
import sys

# 必须在导入 reloop 之前设置: 覆盖为本地 SQLite, 不连 RDS
# 文件名带 PID: 避免旧 schema 残留文件(或并行运行)互相污染
_TEST_DIR = os.path.dirname(__file__)
_TEST_DB = os.path.join(_TEST_DIR, f"test_reloop_{os.getpid()}.db")
for _stale in [f for f in os.listdir(_TEST_DIR) if f.startswith("test_reloop") and f.endswith(".db")]:
    try:
        os.remove(os.path.join(_TEST_DIR, _stale))
    except OSError:
        pass
os.environ["BRAINX_DATABASE_URL"] = f"sqlite:///{_TEST_DB.replace(os.sep, '/')}"
os.environ["BRAINX_LLM_API_KEY"] = ""  # 强制离线模式

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import datetime as dt  # noqa: E402

from reloop.db.engine import SessionLocal, init_db  # noqa: E402
from reloop.modules.profile.structuring import structuring_service  # noqa: E402
from reloop.modules.recommend.engine import recommend_engine  # noqa: E402
from reloop.modules.sync.normalizer import (  # noqa: E402
    STANDARD_KEYS,
    normalize_batch,
    parse_work_years,
)
from reloop.db.models import InteractionRecord, Position, TalentProfile  # noqa: E402

OWNER = "ou_test_user_001"
OTHER = "ou_test_user_002"  # 验证数据隔离

# 模拟从 TTC 页面拿到/导出的原始 JSON(字段名故意混杂中英文, 贴近真实情况)
TTC_RAW = {
    "data": [
        {
            "id": "T001",
            "姓名": "张三",
            "base": "上海",
            "公司": "某互联网大厂",
            "职位": "资深HRBP",
            "经验": "8年3个月经验",
            "学历": "硕士",
            "技能": "组织发展, 人才盘点, 大模型",
            "最近活跃": "2天前",
            "备注": "关注新机会, 最近在看了几个机会",
        },
        {
            "id": "T002",
            "name": "李四",
            "baseLocation": "深圳",
            "currentCompany": "一家制造业上市公司",
            "title": "招聘经理",
            "workYears": "4年经验",
            "education": "本科",
            "skillTags": ["招聘", "校招"],
            "updatedAt": (dt.datetime.now() - dt.timedelta(days=60)).strftime("%Y-%m-%d"),
        },
        {
            "id": "T003",
            "name": "王五",
            "base地点": "北京",
            "公司": "初创公司",
            "职位": "HR专员",
            "工作年限": "11个月",
            "学历": "大专",
            "技能": "行政, 入离职办理",
            "最近活跃时间": "2026-08-10 12:00:00",
        },
        {
            "id": "T004",
            "name": "赵六",
            "base": "杭州",
            "公司": "独角兽公司",
            "职位": "HRBP",
            "经验": "5年经验",
            "学历": "硕士",
            "技能": "HRBP, 组织发展",
            "最近活跃": "10天前",
        },
    ]
}


def test_parse_work_years():
    assert parse_work_years("8年3个月经验") == 8.25
    assert parse_work_years("4年经验") == 4.0
    assert parse_work_years("11个月") == round(11 / 12, 2)
    assert parse_work_years(None) is None


def test_normalize_batch():
    talents = normalize_batch(TTC_RAW)
    assert len(talents) == 4
    for t in talents:
        # 标准结构化格式必须带齐后续算法需要的 key
        assert set(STANDARD_KEYS).issubset(t.keys())
    t1 = talents[0]
    assert t1["name"] == "张三" and t1["base_location"] == "上海"
    assert t1["work_years"] == 8.25 and t1["education"] == "硕士"
    assert t1["last_active_at"] is not None
    t3 = talents[2]
    assert t3["work_years"] == round(11 / 12, 2) and t3["base_location"] == "北京"
    return talents


def run_pipeline():
    # ---- 0. 建表 ----
    init_db()
    db = SessionLocal()
    try:
        # ---- 1. TTC 原始数据 -> 标准结构化格式 ----
        talents = test_normalize_batch()
        test_parse_work_years()
        print("[1] normalize OK: 4 条原始记录 -> 标准格式, keys =", list(STANDARD_KEYS)[:5], "...")

        # ---- 2. 结构化入库(规则+LLM增强+价值分+向量) ----
        for t in talents:
            structuring_service.enrich_and_save(db, OWNER, t)
        total = db.query(TalentProfile).filter(TalentProfile.owner_user_id == OWNER).count()
        assert total == 4, f"应入库 4 人, 实际 {total}"
        row = db.query(TalentProfile).filter(TalentProfile.source_id == "T001").first()
        assert row.value_score is not None and row.resume_embedding, "价值分/向量未生成"
        print(f"[2] structure+save OK: 入库 {total} 人, 张三 value={row.value_score:.3f}, "
              f"embedding_dim={len(row.resume_embedding)}")

        # ---- 3. 数据隔离验证 ----
        other_count = db.query(TalentProfile).filter(
            TalentProfile.owner_user_id == OTHER).count()
        assert other_count == 0, "数据隔离失败: 其他用户不应看到数据"
        print(f"[3] isolation OK: 用户 {OTHER} 视角下人才数 = {other_count}")

        # ---- 4. 设定当前岗位 ----
        db.add(Position(owner_user_id=OWNER, position_name="HRBP",
                        jd_text="HRBP 组织发展 人才盘点", is_active=1))
        db.commit()
        print("[4] position OK: 设定岗位 HRBP")

        # ---- 5. 补互动记录(张三: 昨天通话; 李四: 无) ----
        zhang = db.query(TalentProfile).filter(TalentProfile.source_id == "T001").first()
        db.add(InteractionRecord(owner_user_id=OWNER, talent_id=zhang.id,
                                 interaction_type="call", count=2,
                                 occurred_at=dt.date.today() - dt.timedelta(days=1)))
        db.commit()
        print("[5] interaction OK: 张三 昨天 2 通电话")

        # ---- 6. 两阶段引擎(粗筛+精算+缓存) ----
        # 6a. 首次计算(wait=True 同步精算): 返回最终结果
        result = recommend_engine.compute(db, OWNER, "HRBP", wait=True)
        assert "top3" in result and "top10" in result and "top_n" in result
        assert result["phase"] == "final", f"wait 模式应返回 final, 实际 {result.get('phase')}"
        assert result["position"] == "HRBP"
        assert result["shortlisted"] == 2, f"粗筛应命中张三+赵六, 实际 {result['shortlisted']}"
        print(f"[6] engine OK: 池 {result['total_pool']} 人, 粗筛 {result['shortlisted']} 人, "
              f"Top3={len(result['top3'])} Top10={len(result['top10'])}")

        # 张三(活跃+匹配+高价值+刚通话)应排第一, 赵六第二
        top = result["top3"]
        assert len(top) == 2, f"Top3 应有 2 人, 实际 {len(top)}"
        print("    排名 | 姓名 | 综合分 | 五因子明细")
        for it in top:
            b = it["score_breakdown"]
            print(f"    #{it['rank']} {it['name']} score={it['score']:.4f} "
                  f"act={b['activity']} match={b['match']} val={b['value']} "
                  f"rel={b['relationship']} tend={b['tendency']}")
        assert top[0]["name"] == "张三", "高活跃+高匹配+刚通话的张三应排第一"
        assert top[1]["name"] == "赵六"
        for it in top:
            assert it["contact_reason"], "联系理由未生成"

        # 6b. 二次计算: 同岗位同 JD 同数据 -> 命中缓存, 不重算
        result2 = recommend_engine.compute(db, OWNER, "HRBP")
        assert result2["phase"] == "final" and result2["cached"] is True, \
            f"二次计算应命中缓存, 实际 phase={result2.get('phase')} cached={result2.get('cached')}"
        assert result2["top3"][0]["name"] == top[0]["name"], "缓存结果应与首次一致"
        print("[6b] cache OK: 二次计算直接命中缓存(未重算)")

        # 6c. 轮询接口: 同一 cache_key 查询状态
        r = recommend_engine.result_of(db, OWNER, "HRBP")
        assert r["status"] == "done" and r["phase"] == "final"
        print("[6c] result_of OK: status=done")

        # 6d. 新岗位异步两阶段: 立即返回初筛(preview), 后台线程精算, 轮询到最终结果
        # (用能命中人才库的岗位; "数据分析"类岗位在纯 HR 测试库中会被噪声阈值正确剔除)
        db.add(Position(owner_user_id=OWNER, position_name="HR专员",
                        jd_text="行政 入离职办理", is_active=1))
        db.commit()
        prev = recommend_engine.compute(db, OWNER, "HR专员")  # 不 wait
        assert prev["phase"] == "preview" and prev["computing"] is True, \
            f"首次计算应秒回 preview, 实际 {prev.get('phase')}"
        assert prev["top_n"], "初筛应立即给出名单"
        import time as _time
        deadline = _time.time() + 60
        final = None
        while _time.time() < deadline:
            r = recommend_engine.result_of(db, OWNER, "HR专员")
            if r["status"] == "done" and r["phase"] == "final":
                final = r
                break
            assert r["status"] != "failed", f"后台精算失败: {r.get('message')}"
            _time.sleep(0.3)
        assert final is not None, "后台精算超时未完成"
        assert final["top_n"] and final["top_n"][0]["contact_reason"], "最终结果应有精算理由"
        print(f"[6d] two-phase OK: 初筛秒回 {len(prev['top_n'])} 人 -> 后台精算完成 "
              f"Top1={final['top_n'][0]['name']}")

        # ---- 7. 结果已落库(recommendations 表) ----
        from reloop.db.models import Recommendation

        recs = db.query(Recommendation).filter(
            Recommendation.owner_user_id == OWNER,
            Recommendation.run_id == result["run_id"],
        ).all()
        assert len(recs) == len(result["top_n"]), "推荐结果未完整落库"
        print(f"[7] persist OK: run_id={result['run_id'][:8]}..., 落库 {len(recs)} 条")

        # ---- 7b. 会话 token(飞书登录态) ----
        from reloop.modules.auth.feishu import (
            create_session_token,
            decode_ttc_jwt_unverified,
            verify_session_token,
        )

        tok = create_session_token("u123", ttl_hours=1)
        assert verify_session_token(tok) == "u123"
        assert verify_session_token(tok + "x") is None  # 篡改签名
        expired = create_session_token("u123", ttl_hours=-1)
        assert verify_session_token(expired) is None  # 过期
        assert decode_ttc_jwt_unverified("not.a.jwt") == {}
        print("[7b] auth token OK: 签发/校验/篡改/过期/解码 全部通过")

        # ---- 8. API 冒烟测试(HTTP 层, 含鉴权/隔离头) ----
        from fastapi.testclient import TestClient
        from reloop.main import app

        c = TestClient(app)
        assert c.get("/health").status_code == 200
        assert c.get("/talents").status_code == 401, "无隔离头应 401"
        r = c.get("/talents", headers={"X-Owner-User-Id": OWNER})
        assert r.status_code == 200 and len(r.json()) == 4
        r = c.post("/recommend/compute?position_name=HRBP", headers={"X-Owner-User-Id": OWNER})
        body = r.json()
        assert r.status_code == 200 and body["top3"][0]["name"] == "张三"
        assert body["phase"] == "final" and body["cached"] is True, "API 层应命中缓存"
        r = c.get("/recommend/result?position_name=HRBP", headers={"X-Owner-User-Id": OWNER})
        assert r.status_code == 200 and r.json()["status"] == "done"
        assert c.get("/openapi.json").status_code == 200
        print("[8] API smoke OK: /health 200, 无头 401(隔离), /talents 4人, "
              "/recommend/compute 缓存命中 Top1=张三, /recommend/result done, Swagger 可生成")

        print("\n=== 全流程测试通过: TTC同步 -> 结构化 -> 画像库 -> 设岗 -> 两阶段引擎 -> 缓存 -> TopN ===")
        return 0
    finally:
        db.close()
        try:
            if os.path.exists(_TEST_DB):
                os.remove(_TEST_DB)
        except OSError:
            pass  # 清理失败不影响测试结论


if __name__ == "__main__":
    sys.exit(run_pipeline())
