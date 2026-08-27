"""TTC 一键扫码自动绑定: 会话管理 + 路由契约测试(不触发 Playwright)。"""

import os
import time

os.environ.setdefault("BRAINX_AUTH_REQUIRE_TOKEN", "false")
os.environ.setdefault("BRAINX_AUTH_SESSION_SECRET", "test-auto-login")

from fastapi.testclient import TestClient  # noqa: E402

from reloop.main import app  # noqa: E402
from reloop.modules.auth import auto_login  # noqa: E402

OWNER = "ou_auto_login_test"
H = {"X-Owner-User-Id": OWNER}


def test_session_reuse_pending():
    """同一用户重复发起应复用 pending 会话, 不重开浏览器。"""
    sess1 = auto_login.start_session(OWNER + "_reuse")
    sess2 = auto_login.start_session(OWNER + "_reuse")
    assert sess1.sid == sess2.sid
    assert sess1.status == "pending"


def test_session_expiry():
    """超过 TTL 的会话应标记 expired。"""
    sess = auto_login.start_session(OWNER + "_expiry")
    sess.started_at = time.time() - auto_login._SESSION_TTL - 1
    got = auto_login.get_session(sess.sid)
    assert got.status == "expired"


def test_routes_contract():
    """路由契约: 发起 -> 轮询结构; 他人 sid 404。"""
    from reloop.db.engine import init_db
    init_db()
    c = TestClient(app)
    r = c.post("/auth/ttc/auto-login", headers=H)
    assert r.status_code == 200, r.text
    sid = r.json()["sid"]

    r = c.get(f"/auth/ttc/auto-login/{sid}/status", headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) >= {"status", "qr_png_b64", "error", "bound_name", "space_id"}
    assert body["status"] in ("pending", "failed")  # 无 playwright 环境时 failed

    # 他人不可见该会话
    r = c.get(f"/auth/ttc/auto-login/{sid}/status",
              headers={"X-Owner-User-Id": "ou_someone_else"})
    assert r.status_code == 404

    # 访客不可发起
    r = c.post("/auth/ttc/auto-login")
    assert r.status_code == 401
