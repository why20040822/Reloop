"""框架改造①(2026-08-28) 测试: JD 解析产物接入匹配链路。

覆盖: build_jd_features 规范化 / skill_coverage_detail 覆盖率+命中清单 /
match_score_structured_detail 解析字段直通 / cosine 维度失配防护 /
batch_match_scores 结构化技能 prompt。全部离线(LLM key 为空)可跑。
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("BRAINX_DATABASE_URL", "sqlite:///./test_local.db")
os.environ.setdefault("BRAINX_LLM_API_KEY", "")
os.environ.setdefault("BRAINX_AUTH_REQUIRE_TOKEN", "false")

from reloop.core.jd_features import build_jd_features  # noqa: E402
from reloop.core.matching import (  # noqa: E402
    cosine_similarity,
    match_score_structured_detail,
    normalize_skills,
    skill_coverage_detail,
)

JD_ANALYSIS = {
    "title": "后端开发工程师",
    "required_skills": ["Python", "SQL", "Kafka"],
    "preferred_skills": ["K8s", "未提供"],
    "experience": "3-5年",
    "education": "本科及以上",
}


# ---------- build_jd_features ----------

def test_features_from_analysis():
    f = build_jd_features("后端开发", "负责服务端研发", JD_ANALYSIS)
    assert f.source == "analysis"
    assert "python" in f.skill_list and "sql" in f.skill_list and "kafka" in f.skill_list
    assert "kubernetes" in f.skill_list, "preferred_skills 应并入(k8s 别名归一)"
    assert "未提供" not in f.skill_list, "占位符应剔除"
    assert f.years_min == 3.0, "3-5年应取下限 3"
    assert f.edu_min == "本科"


def test_features_fallback_without_analysis():
    f = build_jd_features("数据分析", "要求 5 年 经验 本科", None)
    assert f.source == "raw"
    assert f.skill_list == []
    assert f.years_min == 5.0, "无解析时正则兜底"
    assert f.edu_min == "本科"


def test_features_alias_and_suffix_normalization():
    f = build_jd_features("前端", None, {
        "required_skills": ["JS", "vue.js", "python开发"], "preferred_skills": [],
    })
    assert f.skill_list == ["javascript", "vue", "python"], "别名+后缀归一"


# ---------- skill_coverage_detail ----------

def test_coverage_and_hits():
    score, hits = skill_coverage_detail(
        ["Python", "SQL", "Kafka"], ["python开发", "MySQL", "SQL"])
    assert score == 2 / 3, "命中 python/sql 两项, 覆盖率=2/3"
    assert hits == ["python", "sql"]


def test_coverage_no_jd_skills_returns_none():
    assert skill_coverage_detail([], ["python"])[0] is None


# ---------- match_score_structured_detail ----------

def _talent_kwargs(skills):
    return dict(
        talent_position="后端开发", talent_skills=skills, talent_tags=[],
        talent_work_years=4.0, talent_education="本科",
    )


def test_parsed_skills_directly_consumed():
    kw = {"position_name": "后端开发工程师", "jd_text": "负责后端", "jd_keywords": []}
    hit = match_score_structured_detail(
        **kw, jd_skills=["Python", "SQL", "Kafka"], **_talent_kwargs(["python", "sql"]))
    miss = match_score_structured_detail(
        **kw, jd_skills=["Python", "SQL", "Kafka"], **_talent_kwargs(["运营"]))
    assert hit["dims"]["skill"] == round(2 / 3, 4)
    assert hit["skill_hits"] == ["python", "sql"]
    assert hit["dims"]["skill"] > miss["dims"]["skill"], "命中者 skill 分应更高"


def test_years_edu_from_analysis_beats_regex():
    # 解析字段 3 年 vs 原文正则会扫出 10 年 —— 解析字段应优先
    d = match_score_structured_detail(
        "岗位", "需要 10 年以上经验", [],
        talent_position=None, talent_skills=[], talent_tags=[],
        talent_work_years=4.0, talent_education="本科",
        years_min=3.0, edu_min="本科")
    assert d["dims"]["years"] == 1.0, "4 年 > 解析下限 3 年应满分"
    assert d["dims"]["edu"] == 1.0


def test_cosine_mismatch_is_none_not_zero():
    assert cosine_similarity([0.1] * 256, [0.1] * 2048) is None, "维度失配应为缺失维"
    d = match_score_structured_detail(
        "岗位", None, [],
        talent_position=None, talent_skills=[], talent_tags=[],
        talent_work_years=None, talent_education=None,
        jd_embedding=[0.1] * 256, resume_embedding=[0.1] * 2048)
    assert d["dims"]["semantic"] is None, "失配不应静默清零"


# ---------- batch_match_scores prompt(离线) ----------

def test_batch_match_prompt_contains_structured_skills():
    from reloop.modules.profile.llm import BATCH_MATCH_PROMPT
    prompt = BATCH_MATCH_PROMPT.format(
        position_name="后端", jd_text="jd",
        candidates="1. 张三", skills_block="【技能】python\n\n")
    assert "【技能】python" in prompt


# ---------- 算法护栏: v2 默认 / 自检回退 v1 / 开关手动切换 ----------

def test_rank_dispatch_v2_by_default(monkeypatch):
    """默认 v2: match_detail 存在(覆盖率命中清单), 走解析特征。"""
    from reloop.modules.recommend.engine import recommend_engine
    assert recommend_engine is not None
    from reloop.services import recommend_service as rs
    eng = rs.recommend_engine
    db, owner, pos, talents = _fixture_pool()
    ranked = eng._rank(db, owner, talents, pos, use_llm=False)
    assert ranked, "应有排序结果"
    top = ranked[0].breakdown
    assert top.match_detail is not None, "v2 应携带 match_detail"
    assert "skill_hits" in (top.match_detail or {})


def test_rank_fallback_on_v2_crash(monkeypatch):
    """v2 抛异常 -> 自动回退 v1: 仍出结果, 但无 match_detail。"""
    from reloop.services import recommend_service as rs
    eng = rs.recommend_engine
    monkeypatch.setattr(rs, "build_jd_features",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("v2 boom")))
    db, owner, pos, talents = _fixture_pool()
    ranked = eng._rank(db, owner, talents, pos, use_llm=False)
    assert ranked, "v2 崩溃后 v1 兜底仍应出结果"
    assert all(r.breakdown.match_detail is None for r in ranked), "v1 无 match_detail"


def test_rank_fallback_on_selfcheck_fail(monkeypatch):
    """v2 产出越界分 -> 自检拦截 -> 回退 v1。"""
    from reloop.services import recommend_service as rs
    eng = rs.recommend_engine

    def bad_v2(*a, **k):
        return [(999, rs.FactorScores(activity=0.5, match=7.0))]
    monkeypatch.setattr(eng, "_rank_v2", bad_v2)
    db, owner, pos, talents = _fixture_pool()
    ranked = eng._rank(db, owner, talents, pos, use_llm=False)
    assert ranked and ranked[0].breakdown.match <= 1.0, "自检拦截后应由 v1 兜底"
    assert all(r.breakdown.match_detail is None for r in ranked)


def test_rank_flag_off_uses_v1(monkeypatch):
    """BRAINX_MATCH_ALGO_V2=False -> 直接走 v1, 不进 v2。"""
    from reloop.services import recommend_service as rs
    eng = rs.recommend_engine
    monkeypatch.setattr(rs.settings, "match_algo_v2", False)
    called = {"v2": False}

    def spy_v2(*a, **k):
        called["v2"] = True
        return []
    monkeypatch.setattr(eng, "_rank_v2", spy_v2)
    db, owner, pos, talents = _fixture_pool()
    ranked = eng._rank(db, owner, talents, pos, use_llm=False)
    assert not called["v2"], "开关关闭时不应进 v2"
    assert ranked and all(r.breakdown.match_detail is None for r in ranked)


def _fixture_pool():
    """最小人才池 + 带解析产物的岗位(SQLite 内存库, 离线)。"""
    from reloop.db.engine import SessionLocal, Base, engine as _engine
    from reloop.db.models import Position, TalentProfile, User
    Base.metadata.create_all(_engine)
    db = SessionLocal()
    owner = "guard_test_owner"
    if db.query(User).filter(User.user_id == owner).first() is None:
        db.add(User(user_id=owner)); db.commit()
    for r in db.query(TalentProfile).filter(TalentProfile.owner_user_id == owner).all():
        db.delete(r)
    for r in db.query(Position).filter(Position.owner_user_id == owner).all():
        db.delete(r)
    db.commit()
    rows = [
        TalentProfile(owner_user_id=owner, name="甲", position="后端开发",
                      skills=["python", "kafka"], work_years=4.0, education="本科"),
        TalentProfile(owner_user_id=owner, name="乙", position="运营",
                      skills=["新媒体"], work_years=1.0, education="大专"),
    ]
    db.add_all(rows)
    db.add(Position(owner_user_id=owner, position_name="高级后端开发工程师",
                    jd_text="负责服务端研发, 精通 Python",
                    jd_analysis={"required_skills": ["Python", "SQL"],
                                 "preferred_skills": [], "experience": "3年",
                                 "education": "本科"}))
    db.commit()
    talents = db.query(TalentProfile).filter(TalentProfile.owner_user_id == owner).all()
    pos = db.query(Position).filter(Position.owner_user_id == owner).first()
    return db, owner, pos, talents


# ---------- 改造②: 向量来源标记 + 独立 embed 端点 ----------

def test_embed_with_source_offline_marks_hash():
    """LLM key 为空(离线) -> embed_with_source 返回 ('hash') 且向量非空。"""
    from reloop.modules.profile.llm import llm_service
    vec, src = llm_service.embed_with_source("某候选人画像文本")
    assert src == "hash"
    assert len(vec) == 256, "离线兜底应为 256 维哈希向量"


def test_embed_batch_with_source_offline_marks_hash():
    from reloop.modules.profile.llm import llm_service
    out = llm_service.embed_batch_with_source(["a", "b"])
    assert len(out) == 2
    assert all(src == "hash" for _, src in out)


def test_embed_endpoint_fallback_to_chat_config():
    """未配置 embed 独立端点时回落 chat 配置(旧行为)。"""
    from reloop.modules.profile.llm import LLMService
    s = LLMService()
    assert s.embed_base_url == s.base_url
    assert s.embed_api_key == s.api_key


def test_embed_endpoint_override():
    """配置独立 embed 端点后, embed 走新端点且与 chat 端点解耦。"""
    from reloop.modules.profile.llm import LLMService
    from reloop.config import settings
    old = (settings.llm_embed_base_url, settings.llm_embed_api_key)
    try:
        settings.llm_embed_base_url = "https://open.bigmodel.cn/api/paas/v4"
        settings.llm_embed_api_key = "fake-bigmodel-key"
        s = LLMService()
        assert s.embed_base_url == "https://open.bigmodel.cn/api/paas/v4"
        assert s.embed_api_key == "fake-bigmodel-key"
        assert s.base_url != s.embed_base_url, "chat 端点不受影响"
    finally:
        settings.llm_embed_base_url, settings.llm_embed_api_key = old


def test_structuring_writes_embedding_source():
    """同步落库路径应写入 embedding_source(离线=hash)。"""
    from reloop.db.engine import SessionLocal, Base, engine as _engine
    from reloop.db.models import TalentProfile
    Base.metadata.create_all(_engine)
    db = SessionLocal()
    owner = "emb_src_test"
    from reloop.db.models import User
    if db.query(User).filter(User.user_id == owner).first() is None:
        db.add(User(user_id=owner)); db.commit()
    for r in db.query(TalentProfile).filter(TalentProfile.owner_user_id == owner).all():
        db.delete(r)
    db.commit()
    row = rs_structuring(db, owner)
    try:
        assert row.resume_embedding and len(row.resume_embedding) == 256
        assert row.embedding_source == "hash"
    finally:
        db.close()


def rs_structuring(db, owner):
    from reloop.modules.profile.structuring import structuring_service
    return structuring_service.enrich_and_save(
        db, owner, {"name": "测试", "summary": "五年后端经验, 精通 Python"},
        source_id="emb-src-1", commit=True)
