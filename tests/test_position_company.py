"""Contracts for company-scoped position identity and ID-based recommendations."""

import copy
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from reloop.config import settings
from reloop.db.engine import SessionLocal, init_db
from reloop.db.models import Position, RecommendRun, User
from reloop.main import app
from reloop.modules.positions.jd_parser import DeepSeekJDParser, build_jd_messages
from reloop.modules.recommend.engine import RecommendEngine, recommend_engine
from reloop.modules.profile.llm import llm_service
from reloop.schemas.jd import JDAnalysis
from reloop.schemas.talent import PositionCreate


VALID_ANALYSIS = {
    "title": "平台产品负责人",
    "summary": "负责平台产品规划和交付。",
    "responsibilities": ["制定产品策略"],
    "required_skills": ["产品规划"],
    "preferred_skills": ["数据分析"],
    "experience": "5 年以上产品经验",
    "education": "本科及以上",
    "location": "上海",
    "industry_keywords": ["企业服务"],
    "salary_range": "面议",
    "team_size": "5 人",
    "reporting_line": "产品总监",
    "language_requirements": ["中文"],
}

@pytest.fixture
def owner(monkeypatch):
    monkeypatch.setattr(settings, "auth_allow_guest", False)
    monkeypatch.setattr(settings, "auth_require_token", False)
    init_db()
    db = SessionLocal()
    try:
        db.query(RecommendRun).delete()
        db.query(Position).delete()
        db.query(User).delete()
        db.commit()
    finally:
        db.close()
    monkeypatch.setattr(llm_service, "embed", lambda value: [0.0])
    return {"X-Owner-User-Id": "company-owner"}


def _create_position(client, headers, **body):
    response = client.post("/positions", headers=headers, json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_jd_analysis_normalizes_explicit_company_and_absent_company_to_null():
    present = copy.deepcopy(VALID_ANALYSIS)
    present["company_name"] = "  远景科技  "

    assert JDAnalysis.model_validate(present).company_name == "远景科技"
    assert JDAnalysis.model_validate(VALID_ANALYSIS).company_name is None
    assert "仅提取 JD 中明确写出的招聘公司" in build_jd_messages("岗位 JD")[0]["content"]


def test_parser_returns_explicit_company_or_null_when_it_is_absent():
    present = copy.deepcopy(VALID_ANALYSIS)
    present["company_name"] = "远景科技"
    absent = copy.deepcopy(VALID_ANALYSIS)
    absent["company_name"] = None

    present_parser = DeepSeekJDParser(
        api_key="test-key",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"choices": [{"message": {"content": json.dumps({"analysis": present, "source_text": "职位描述"})}}]},
                request=request,
            )
        ),
    )
    absent_parser = DeepSeekJDParser(
        api_key="test-key",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"choices": [{"message": {"content": json.dumps({"analysis": absent, "source_text": "职位描述"})}}]},
                request=request,
            )
        ),
    )

    assert present_parser.parse("远景科技正在招聘产品负责人").analysis.company_name == "远景科技"
    assert absent_parser.parse("现招聘产品负责人").analysis.company_name is None


def test_position_blank_company_is_normalized_and_overrides_parsed_company(owner):
    analysis = copy.deepcopy(VALID_ANALYSIS)
    analysis["company_name"] = "解析出的公司"
    with TestClient(app) as client:
        created = _create_position(
            client,
            owner,
            position_name="产品负责人",
            company_name="   ",
            jd_text="raw jd",
            jd_analysis=analysis,
        )

    assert created["company_name"] is None
    assert created["jd_analysis"]["company_name"] is None
    db = SessionLocal()
    try:
        saved = db.query(Position).one()
        assert saved.company_name is None
        assert saved.jd_analysis["company_name"] is None
    finally:
        db.close()


def test_position_title_whitespace_replaces_same_company_position(owner):
    with TestClient(app) as client:
        original = _create_position(
            client, owner, position_name="  产品负责人  ", company_name="远景科技", jd_text="v1"
        )
        replacement = _create_position(
            client, owner, position_name="产品负责人", company_name="远景科技", jd_text="v2"
        )
        active = client.get("/positions", headers=owner).json()

    assert replacement["position_name"] == "产品负责人"
    assert [position["id"] for position in active] == [replacement["id"]]
    db = SessionLocal()
    try:
        assert db.get(Position, original["id"]).is_active == 0
    finally:
        db.close()


def test_position_rejects_blank_title(owner):
    with TestClient(app) as client:
        response = client.post(
            "/positions",
            headers=owner,
            json={"position_name": "   ", "company_name": "远景科技"},
        )

    assert response.status_code == 422
    db = SessionLocal()
    try:
        assert db.query(Position).count() == 0
    finally:
        db.close()


def test_parsed_and_submitted_company_names_reject_values_over_128_characters():
    analysis = copy.deepcopy(VALID_ANALYSIS)
    analysis["company_name"] = "x" * 129

    with pytest.raises(ValueError):
        JDAnalysis.model_validate(analysis)
    with pytest.raises(ValueError):
        PositionCreate.model_validate({"position_name": "产品负责人", "company_name": "x" * 129})


def test_same_company_replaces_only_that_company_position(owner):
    with TestClient(app) as client:
        original = _create_position(
            client, owner, position_name="产品负责人", company_name="远景科技", jd_text="v1"
        )
        other_company = _create_position(
            client, owner, position_name="产品负责人", company_name="北辰资本", jd_text="v1"
        )
        replacement = _create_position(
            client, owner, position_name="产品负责人", company_name="  远景科技  ", jd_text="v2"
        )
        active = client.get("/positions", headers=owner).json()

    assert {position["id"] for position in active} == {other_company["id"], replacement["id"]}
    db = SessionLocal()
    try:
        assert db.get(Position, original["id"]).is_active == 0
        assert db.get(Position, other_company["id"]).is_active == 1
    finally:
        db.close()


def test_init_db_adds_company_column_idempotently(tmp_path, monkeypatch):
    import reloop.db.engine as engine_module

    legacy_engine = create_engine(f"sqlite:///{tmp_path / 'legacy-company.db'}")
    with legacy_engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE positions (
                    id INTEGER PRIMARY KEY,
                    owner_user_id VARCHAR(64) NOT NULL,
                    position_name VARCHAR(128) NOT NULL,
                    jd_text TEXT,
                    jd_analysis JSON,
                    jd_analysis_version VARCHAR(32),
                    jd_embedding JSON,
                    is_active INTEGER,
                    created_at DATETIME
                )
                """
            )
        )

    monkeypatch.setattr(engine_module, "engine", legacy_engine)
    engine_module.init_db()
    engine_module.init_db()

    columns = [column["name"] for column in inspect(legacy_engine).get_columns("positions")]
    assert columns.count("company_name") == 1


def test_recommend_position_id_wins_over_title_for_compute_and_result(owner, monkeypatch):
    db = SessionLocal()
    try:
        db.add_all(
            [
                Position(owner_user_id="company-owner", position_name="标题 A", company_name="甲", is_active=1),
                Position(owner_user_id="company-owner", position_name="标题 B", company_name="乙", is_active=1),
            ]
        )
        db.commit()
        target_id = db.query(Position).filter(Position.position_name == "标题 B").one().id
    finally:
        db.close()

    calls = []

    def fake_compute(db, owner_user_id, position_name=None, **kwargs):
        calls.append(("compute", owner_user_id, position_name, kwargs.get("position_id")))
        return {"ok": True}

    def fake_result(db, owner_user_id, position_name=None, **kwargs):
        calls.append(("result", owner_user_id, position_name, kwargs.get("position_id")))
        return {"ok": True}

    monkeypatch.setattr(recommend_engine, "compute", fake_compute)
    monkeypatch.setattr(recommend_engine, "result_of", fake_result)
    with TestClient(app) as client:
        computed = client.post(
            f"/recommend/compute?position_name=%E6%A0%87%E9%A2%98%20A&position_id={target_id}",
            headers=owner,
        )
        polled = client.get(
            f"/recommend/result?position_name=%E6%A0%87%E9%A2%98%20A&position_id={target_id}",
            headers=owner,
        )

    assert computed.status_code == 200
    assert polled.status_code == 200
    assert calls == [
        ("compute", "company-owner", "标题 A", target_id),
        ("result", "company-owner", "标题 A", target_id),
    ]


@pytest.mark.parametrize("foreign,inactive", [(True, False), (False, True)])
def test_recommend_rejects_foreign_or_inactive_position_id(owner, foreign, inactive):
    db = SessionLocal()
    try:
        position = Position(
            owner_user_id="another-owner" if foreign else "company-owner",
            position_name="产品负责人",
            company_name="远景科技",
            is_active=0 if inactive else 1,
        )
        db.add(position)
        db.commit()
        position_id = position.id
    finally:
        db.close()

    with TestClient(app) as client:
        computed = client.post(f"/recommend/compute?position_id={position_id}", headers=owner)
        polled = client.get(f"/recommend/result?position_id={position_id}", headers=owner)

    assert computed.status_code == 404
    assert polled.status_code == 404


def test_recommend_legacy_title_lookup_remains_available(owner):
    db = SessionLocal()
    try:
        position = Position(
            owner_user_id="company-owner",
            position_name="产品负责人",
            company_name="远景科技",
            is_active=1,
        )
        db.add(position)
        db.commit()
    finally:
        db.close()

    lookup_db = SessionLocal()
    try:
        resolved = RecommendEngine()._resolve_position(
            lookup_db, "company-owner", position_name="产品负责人"
        )
    finally:
        lookup_db.close()

    assert resolved is not None
    assert resolved.id == position.id


def test_recommend_cache_key_isolated_by_position_id_and_company():
    first = Position(id=10, position_name="产品负责人", company_name="远景科技", jd_text="JD")
    second = Position(id=11, position_name="产品负责人", company_name="远景科技", jd_text="JD")
    same_position_different_company = Position(
        id=10, position_name="产品负责人", company_name="北辰资本", jd_text="JD"
    )

    first_key = RecommendEngine._cache_key("owner", first, "pool")
    assert first_key != RecommendEngine._cache_key("owner", second, "pool")
    assert first_key != RecommendEngine._cache_key("owner", same_position_different_company, "pool")
