"""Contracts for backend-only DeepSeek JD parsing and persistence."""

import copy
import base64
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, text

from reloop.config import Settings, settings
from reloop.db.engine import SessionLocal, init_db
from reloop.db.models import Position, User
from reloop.main import app
from reloop.modules.auth.feishu import create_session_token
from reloop.modules.positions.jd_parser import (
    DeepSeekJDParser,
    JDParserError,
    JDParserUnavailable,
)
from reloop.modules.profile.llm import llm_service
from reloop.schemas.jd import JDAnalysis, JDParseRequest


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

VALID_PARSE_RESPONSE = {
    "analysis": VALID_ANALYSIS,
    "source_text": "从图片转写出的职位描述",
}
IMAGE_DATA_URL = "data:image/png;base64,iVBORw0KGgo="


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


@pytest.fixture
def strict_parse_headers(monkeypatch):
    """A real existing user session while legacy owner fallback remains enabled."""
    monkeypatch.setattr(settings, "auth_allow_guest", True)
    monkeypatch.setattr(settings, "auth_require_token", False)
    monkeypatch.setattr(settings, "auth_auto_register", True)
    init_db()
    db = SessionLocal()
    try:
        db.query(Position).delete()
        db.query(User).delete()
        db.add_all(
            [
                User(user_id="strict-parse-user"),
                User(user_id=settings.guest_owner_id, display_name="访客"),
            ]
        )
        db.commit()
    finally:
        db.close()
    return {"X-Auth-Token": create_session_token("strict-parse-user")}


@pytest.fixture
def position_owner(owner, monkeypatch):
    """Position persistence must remain isolated from a configured embedding service."""
    monkeypatch.setenv("BRAINX_LLM_API_KEY", "example-external-embedding-key")
    monkeypatch.setattr(settings, "llm_api_key", "example-external-embedding-key")
    calls = []

    def fake_embed(text):
        calls.append(text)
        return [0.0]

    monkeypatch.setattr(llm_service, "embed", fake_embed)
    return owner, calls


def database_counts() -> tuple[int, int]:
    db = SessionLocal()
    try:
        return db.query(User).count(), db.query(Position).count()
    finally:
        db.close()


def install_upstream_transport(monkeypatch, handler):
    """Replace only the parser's external HTTP client transport."""
    import reloop.modules.positions.jd_parser as parser_module

    real_client = httpx.Client

    def client_with_fake_transport(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(parser_module.httpx, "Client", client_with_fake_transport)


def test_parse_jd_sends_backend_key_and_validates_json():
    seen_headers = {}
    seen_payload = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen_headers["Authorization"] = request.headers["Authorization"]
        seen_payload.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(VALID_PARSE_RESPONSE)}}]},
        )

    parser = DeepSeekJDParser(
        api_key="test-deepseek-key",
        base_url="https://deepseek.example/v1",
        transport=httpx.MockTransport(handle),
    )

    result = parser.parse("负责平台产品，要求 5 年经验")

    assert result.analysis.title == "平台产品负责人"
    assert result.analysis.required_skills == ["产品规划"]
    assert result.source_text == "负责平台产品，要求 5 年经验"
    assert seen_headers["Authorization"] == "Bearer test-deepseek-key"
    assert seen_payload["response_format"] == {"type": "json_object"}


def test_parser_routes_text_to_flash_and_returns_submitted_source_text():
    seen_payload = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen_payload.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(VALID_PARSE_RESPONSE)}}]},
            request=request,
        )

    parser = DeepSeekJDParser(
        api_key="test-key",
        model="deepseek-v4-flash",
        vision_model="deepseek-v4-flash-vision-exp",
        transport=httpx.MockTransport(handle),
    )
    result = parser.parse("  文本职位描述  ")

    assert seen_payload["model"] == "deepseek-v4-flash"
    assert result.analysis.title == "平台产品负责人"
    assert result.source_text == "文本职位描述"


def test_parser_routes_images_to_vision_with_official_image_url_blocks():
    seen_payload = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen_payload.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(VALID_PARSE_RESPONSE)}}]},
            request=request,
        )

    parser = DeepSeekJDParser(
        api_key="test-key",
        model="deepseek-v4-flash",
        vision_model="deepseek-v4-flash-vision-exp",
        transport=httpx.MockTransport(handle),
    )
    result = parser.parse("", image_data_urls=[IMAGE_DATA_URL])

    content = seen_payload["messages"][1]["content"]
    assert seen_payload["model"] == "deepseek-v4-flash-vision-exp"
    assert content[0]["type"] == "text"
    assert content[1] == {"type": "image_url", "image_url": {"url": IMAGE_DATA_URL}}
    assert result.source_text == "从图片转写出的职位描述"


def test_parse_request_rejects_invalid_image_data_without_writes(strict_parse_headers):
    oversized = "data:image/png;base64," + base64.b64encode(b"x" * (8 * 1024 * 1024 + 1)).decode()
    before = database_counts()
    with TestClient(app) as client:
        malformed = client.post(
            "/positions/parse-jd", headers=strict_parse_headers,
            json={"jd_text": "有效 JD", "images": ["not-a-data-url"]},
        )
        unsupported = client.post(
            "/positions/parse-jd", headers=strict_parse_headers,
            json={"jd_text": "有效 JD", "images": ["data:image/svg+xml;base64,PHN2Zy8+"]},
        )
        too_large = client.post(
            "/positions/parse-jd", headers=strict_parse_headers,
            json={"jd_text": "有效 JD", "images": [oversized]},
        )

    assert malformed.status_code == 422
    assert unsupported.status_code == 422
    assert too_large.status_code == 422
    assert database_counts() == before


def test_parse_request_accepts_image_only_and_limits_four_images():
    image_only = JDParseRequest.model_validate({"jd_text": "   ", "images": [IMAGE_DATA_URL]})

    assert image_only.jd_text == ""
    assert image_only.images == [IMAGE_DATA_URL]
    with pytest.raises(ValidationError):
        JDParseRequest.model_validate({"jd_text": "", "images": [IMAGE_DATA_URL] * 5})


def test_deepseek_defaults_use_official_flash_models():
    configured = Settings()

    assert configured.deepseek_model == "deepseek-v4-flash"
    assert configured.deepseek_vision_model == "deepseek-v4-flash-vision-exp"


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


def test_parse_jd_sanitizes_empty_choices_response():
    parser = DeepSeekJDParser(
        api_key="test-deepseek-key",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"choices": []}, request=request)
        ),
    )

    with pytest.raises(JDParserError) as exc_info:
        parser.parse("职位描述")

    assert "test-deepseek-key" not in str(exc_info.value)


def test_parse_endpoint_does_not_create_position(strict_parse_headers, monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "")
    before = database_counts()

    with TestClient(app) as client:
        response = client.post(
            "/positions/parse-jd", headers=strict_parse_headers, json={"jd_text": "职位描述"}
        )

    assert response.status_code == 503
    assert database_counts() == before


def test_parse_endpoint_uses_transient_header_key_without_persisting_it(strict_parse_headers, monkeypatch):
    transient_key = "transient-test-key"
    seen_headers = {}
    monkeypatch.setattr(settings, "deepseek_api_key", "")

    def handle(request: httpx.Request) -> httpx.Response:
        seen_headers["authorization"] = request.headers["Authorization"]
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(VALID_PARSE_RESPONSE)}}]},
            request=request,
        )

    install_upstream_transport(monkeypatch, handle)
    before = database_counts()
    with TestClient(app) as client:
        response = client.post(
            "/positions/parse-jd",
            headers={**strict_parse_headers, "X-DeepSeek-Api-Key": transient_key},
            json={"jd_text": "职位描述"},
        )

    assert response.status_code == 200, response.text
    assert seen_headers["authorization"] == f"Bearer {transient_key}"
    assert transient_key not in response.text
    assert database_counts() == before


def test_parse_endpoint_rejects_blank_and_over_50000_character_jd(strict_parse_headers):
    before = database_counts()
    with TestClient(app) as client:
        blank = client.post(
            "/positions/parse-jd", headers=strict_parse_headers, json={"jd_text": "   "}
        )
        oversized = client.post(
            "/positions/parse-jd", headers=strict_parse_headers, json={"jd_text": "x" * 50001}
        )

    assert blank.status_code == 422
    assert oversized.status_code == 422
    assert database_counts() == before


def test_parse_endpoint_rejects_unauthenticated_owner_header_without_writes(strict_parse_headers):
    before = database_counts()

    with TestClient(app) as client:
        response = client.post(
            "/positions/parse-jd",
            headers={"X-Owner-User-Id": "must-not-be-honored"},
            json={"jd_text": "职位描述"},
        )

    assert response.status_code == 401
    assert database_counts() == before


def test_parse_endpoint_rejects_invalid_or_guest_sessions_without_writes(strict_parse_headers):
    before = database_counts()
    guest_token = create_session_token(settings.guest_owner_id)

    with TestClient(app) as client:
        invalid = client.post(
            "/positions/parse-jd", headers={"X-Auth-Token": "invalid"}, json={"jd_text": "职位描述"}
        )
        guest = client.post(
            "/positions/parse-jd", headers={"X-Auth-Token": guest_token}, json={"jd_text": "职位描述"}
        )

    assert invalid.status_code == 401
    assert guest.status_code == 401
    assert database_counts() == before


def test_parse_endpoint_sanitizes_upstream_failure_without_writes(strict_parse_headers, monkeypatch):
    transient_key = "test-transient-key"
    monkeypatch.setattr(settings, "deepseek_api_key", "")
    install_upstream_transport(
        monkeypatch,
        lambda request: httpx.Response(500, text="provider failure details", request=request),
    )
    before = database_counts()

    with TestClient(app) as client:
        response = client.post(
            "/positions/parse-jd",
            headers={**strict_parse_headers, "X-DeepSeek-Api-Key": transient_key},
            json={"jd_text": "职位描述"},
        )

    assert response.status_code == 502
    assert "provider failure details" not in response.text
    assert transient_key not in response.text
    assert database_counts() == before


def test_position_saves_raw_and_structured_jd_atomically(position_owner):
    owner, embed_calls = position_owner
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
    assert embed_calls == ["raw jd"]

    db = SessionLocal()
    try:
        saved = db.query(Position).one()
        assert saved.jd_text == "raw jd"
        assert saved.jd_analysis["title"] == "平台产品负责人"
        assert saved.jd_analysis_version == "deepseek-v1"
    finally:
        db.close()


def test_structured_jd_requires_raw_jd(position_owner):
    owner, embed_calls = position_owner
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
        assert embed_calls == []
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


def test_jd_analysis_normalizes_text_and_deduplicates_list_items():
    payload = copy.deepcopy(VALID_ANALYSIS)
    payload["title"] = "  平台产品负责人  "
    payload["responsibilities"] = [" 制定产品策略 ", "制定产品策略", "交付产品"]

    analysis = JDAnalysis.model_validate(payload)

    assert analysis.title == "平台产品负责人"
    assert analysis.responsibilities == ["制定产品策略", "交付产品"]


def test_jd_analysis_rejects_whitespace_scalar_and_list_item():
    blank_scalar = copy.deepcopy(VALID_ANALYSIS)
    blank_scalar["title"] = "   "
    with pytest.raises(ValidationError):
        JDAnalysis.model_validate(blank_scalar)

    blank_list_item = copy.deepcopy(VALID_ANALYSIS)
    blank_list_item["required_skills"] = ["产品规划", "  "]
    with pytest.raises(ValidationError):
        JDAnalysis.model_validate(blank_list_item)
