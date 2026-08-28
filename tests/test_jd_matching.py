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
