"""Collected HTTP regression for asynchronous authenticated TTC ingestion."""

import time

from fastapi.testclient import TestClient

from reloop.config import settings
from reloop.db.engine import SessionLocal, init_db
from reloop.db.models import TalentProfile, User
from reloop.main import app
from reloop.modules.auth.feishu import create_session_token


OWNER = "sync-pipeline-owner"
OTHER = "sync-pipeline-other"
TALENTS = [
    {
        "id": "SYNC-S1",
        "姓名": "张韵",
        "公司": "字节跳动",
        "职位": "商业分析师",
        "经验": "6年",
        "学历": "硕士",
        "技能": "SQL, Python, 大模型",
        "最近活跃": "1天前",
    },
    {
        "id": "SYNC-S2",
        "姓名": "李哲",
        "公司": "腾讯",
        "职位": "数据产品经理",
        "经验": "8年",
        "学历": "本科",
        "技能": "数据分析, SQL",
        "最近活跃": "3天前",
    },
    {
        "id": "SYNC-S3",
        "姓名": "王楠",
        "公司": "初创公司",
        "职位": "HR专员",
        "经验": "2年",
        "学历": "大专",
        "技能": "行政",
        "最近活跃": "20天前",
    },
]


def test_authenticated_async_ingest_persists_and_hides_progress_from_other_owner(monkeypatch):
    monkeypatch.setattr(settings, "auth_require_token", True)
    monkeypatch.setattr(settings, "auth_allow_guest", False)
    monkeypatch.setattr(settings, "llm_api_key", "")
    init_db()
    db = SessionLocal()
    try:
        db.query(TalentProfile).filter(TalentProfile.owner_user_id.in_([OWNER, OTHER])).delete(
            synchronize_session=False
        )
        db.query(User).filter(User.user_id.in_([OWNER, OTHER])).delete(
            synchronize_session=False
        )
        db.add_all(
            [
                User(user_id=OWNER, display_name="Sync Owner"),
                User(user_id=OTHER, display_name="Other Owner"),
            ]
        )
        db.commit()
    finally:
        db.close()

    owner_headers = {"X-Auth-Token": create_session_token(OWNER)}
    other_headers = {"X-Auth-Token": create_session_token(OTHER)}
    with TestClient(app) as client:
        started = client.post(
            "/sync/ttc/ingest",
            headers=owner_headers,
            json={"talents": TALENTS},
        )
        assert started.status_code == 200, started.text
        sync_id = started.json()["sync_id"]

        denied = client.get(
            "/sync/ttc/status",
            headers=other_headers,
            params={"sync_id": sync_id},
        )
        assert denied.status_code == 200
        assert denied.json() == {"status": "not_found"}

        deadline = time.monotonic() + 10
        status = {"status": "running"}
        while time.monotonic() < deadline:
            response = client.get(
                "/sync/ttc/status",
                headers=owner_headers,
                params={"sync_id": sync_id},
            )
            assert response.status_code == 200, response.text
            status = response.json()
            if status["status"] != "running":
                break
            time.sleep(0.02)

    assert status["status"] == "done", status
    assert status["synced"] == 3
    db = SessionLocal()
    try:
        rows = (
            db.query(TalentProfile)
            .filter(TalentProfile.owner_user_id == OWNER)
            .order_by(TalentProfile.source_id)
            .all()
        )
        assert [row.source_id for row in rows] == ["SYNC-S1", "SYNC-S2", "SYNC-S3"]
        assert all(row.resume_embedding for row in rows)
        assert db.query(TalentProfile).filter(TalentProfile.owner_user_id == OTHER).count() == 0
    finally:
        db.close()
