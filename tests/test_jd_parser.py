"""Contracts for backend-only DeepSeek JD parsing and persistence."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from reloop.config import settings
from reloop.db.engine import SessionLocal, init_db
from reloop.db.models import Position, User
from reloop.main import app
from reloop.modules.positions.jd_parser import (
    DeepSeekJDParser,
    JDParserError,
    JDParserUnavailable,
)


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
        db.query(Position).delete()
        db.query(User).delete()
        db.commit()
    finally:
        db.close()
    return {"X-Owner-User-Id": "jd-parser-owner"}


def test_parse_jd_sends_backend_key_and_validates_json():
    seen_headers = {}
    seen_payload = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen_headers["Authorization"] = request.headers["Authorization"]
        seen_payload.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(VALID_ANALYSIS)}}]},
        )

    parser = DeepSeekJDParser(
        api_key="test-deepseek-key",
        base_url="https://deepseek.example/v1",
        transport=httpx.MockTransport(handle),
    )

    result = parser.parse("负责平台产品，要求 5 年经验")

    assert result.title == "平台产品负责人"
    assert result.required_skills == ["产品规划"]
    assert seen_headers["Authorization"] == "Bearer test-deepseek-key"
    assert seen_payload["response_format"] == {"type": "json_object"}


def test_parse_jd_rejects_missing_key_without_http_call():
    def fail_if_called(request: httpx.Request) -> httpx.Response:
        raise AssertionError("the HTTP transport must not be called without a key")

    parser = DeepSeekJDParser(api_key="", transport=httpx.MockTransport(fail_if_called))

    with pytest.raises(JDParserUnavailable):
        parser.parse("职位描述")


def test_parse_jd_sanitizes_upstream_error_without_leaking_key():
    configured_key = "test-deepseek-key"
    upstream_body = "provider failure details"

    parser = DeepSeekJDParser(
        api_key=configured_key,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(500, text=upstream_body, request=request)
        ),
    )

    with pytest.raises(JDParserError) as exc_info:
        parser.parse("职位描述")

    assert configured_key not in str(exc_info.value)
    assert upstream_body not in str(exc_info.value)


def test_parse_endpoint_does_not_create_position(owner, monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "")
    db = SessionLocal()
    try:
        before = db.query(Position).count()
    finally:
        db.close()

    with TestClient(app) as client:
        response = client.post("/positions/parse-jd", headers=owner, json={"jd_text": "职位描述"})

    db = SessionLocal()
    try:
        assert response.status_code == 503
        assert db.query(Position).count() == before
    finally:
        db.close()


def test_parse_endpoint_rejects_blank_and_over_50000_character_jd(owner):
    with TestClient(app) as client:
        blank = client.post("/positions/parse-jd", headers=owner, json={"jd_text": "   "})
        oversized = client.post(
            "/positions/parse-jd", headers=owner, json={"jd_text": "x" * 50001}
        )

    assert blank.status_code == 422
    assert oversized.status_code == 422


def test_position_saves_raw_and_structured_jd_atomically(owner):
    with TestClient(app) as client:
        response = client.post(
            "/positions",
            headers=owner,
            json={
                "position_name": "平台产品负责人",
                "jd_text": "raw jd",
                "jd_analysis": VALID_ANALYSIS,
            },
        )

    assert response.status_code == 200, response.text
    assert response.json()["jd_analysis"]["title"] == "平台产品负责人"

    db = SessionLocal()
    try:
        saved = db.query(Position).one()
        assert saved.jd_text == "raw jd"
        assert saved.jd_analysis["title"] == "平台产品负责人"
        assert saved.jd_analysis_version == "deepseek-v1"
    finally:
        db.close()


def test_structured_jd_requires_raw_jd(owner):
    with TestClient(app) as client:
        response = client.post(
            "/positions",
            headers=owner,
            json={
                "position_name": "平台产品负责人",
                "jd_text": "  ",
                "jd_analysis": VALID_ANALYSIS,
            },
        )

    db = SessionLocal()
    try:
        assert response.status_code == 422
        assert db.query(Position).count() == 0
    finally:
        db.close()


def test_init_db_adds_jd_analysis_columns_idempotently(tmp_path, monkeypatch):
    import reloop.db.engine as engine_module

    legacy_engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with legacy_engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE positions (
                    id INTEGER PRIMARY KEY,
                    owner_user_id VARCHAR(64) NOT NULL,
                    position_name VARCHAR(128) NOT NULL,
                    jd_text TEXT,
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
    assert columns.count("jd_analysis") == 1
    assert columns.count("jd_analysis_version") == 1
