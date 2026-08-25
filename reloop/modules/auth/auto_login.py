"""TTC 一键扫码自动绑定(Web 版): 零复制粘贴。

流程(前端设置页「一键扫码绑定」):
  1. POST /auth/ttc/auto-login        -> 创建登录会话(进程内管理, 单 worker 部署)
  2. GET  /auth/ttc/auto-login/{sid}/status -> 轮询: 返回二维码 PNG(base64) + 状态
     前端把二维码展示给用户(替代 F12 复制 Token 的手动步骤)
  3. 用户手机飞书扫码 -> 页面自动跳转登录成功 -> 后台线程抓到 TTC Bearer Token
  4. 自动解析 Token(CustomData.user_unique_id -> 空间 ID, nick_name -> 用户名),
     写入 users 表(自动绑定), 并自动触发 sync_jobs 后台同步
  5. 前端轮询到 status=success 后, 继续轮询 /sync/ttc/status 显示"同步中(X/Y人)"

技术要点:
  - Playwright 无头 Chromium 打开 TTC 登录页(BRAINX_AUTH_LOGIN_URL),
    周期性截图当前页面(含飞书二维码)供前端 <img> 展示。
  - 抓 Token: 监听网络请求 Authorization 头 + 轮询 localStorage 兜底。
  - 会话是进程内单例(threading + dict): 必须单 worker 部署(uvicorn --workers 1),
    systemd 已配套。
  - 服务器需 playwright + chromium(ms-playwright 缓存); 无头 + --no-sandbox。
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from reloop.config import settings
from reloop.db.engine import SessionLocal
from reloop.db.models import User
from reloop.modules.auth.feishu import decode_ttc_jwt_unverified

logger = logging.getLogger(__name__)

_SESSION_TTL = 360          # 登录会话最长存活(秒): pending 超时 + success 结果保留
_PENDING_TIMEOUT = 240      # 单个 pending 会话等待扫码的最长时间(秒)
_QR_REFRESH_INTERVAL = 1.0  # 二维码截图刷新间隔(秒)
_TOKEN_LS_KEYS = ("access_token", "token", "Authorization",
                  "authorization", "accessToken", "auth_token")

_session_lock = threading.Lock()
_sessions: dict[str, "AutoLoginSession"] = {}


@dataclass
class AutoLoginSession:
    """一次扫码登录会话(进程内)。"""
    sid: str
    user_id: str                      # Reloop 用户(隔离键)
    status: str = "pending"           # pending / success / failed / timeout / expired
    qr_png: bytes = b""               # 当前页面截图(PNG, 二维码/登录按钮/成功页)
    token: str = ""
    space_id: str = ""
    bound_name: str = ""
    error: str = ""
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def touch(self) -> None:
        self.updated_at = time.time()

    def age(self) -> float:
        return time.time() - self.started_at


def start_session(user_id: str) -> AutoLoginSession:
    """创建(或复用)该用户的 pending 登录会话, 后台线程开始跑 Playwright。"""
    with _session_lock:
        # 复用未结束的同用户会话(前端重复点击/刷新页面不重复开浏览器)
        for s in _sessions.values():
            if s.user_id == user_id and s.status == "pending":
                return s
        # 清理超时会话, 防止内存膨胀
        for k, s in list(_sessions.items()):
            if s.age() > _SESSION_TTL or s.status in ("success", "failed", "timeout"):
                _sessions.pop(k, None)
        sess = AutoLoginSession(sid=uuid.uuid4().hex[:16], user_id=user_id)
        _sessions[sess.sid] = sess

    t = threading.Thread(
        target=_run_login_thread, args=(sess.sid,), daemon=True,
        name=f"ttc-autologin-{sess.sid[:8]}",
    )
    t.start()
    return sess


def get_session(sid: str) -> Optional[AutoLoginSession]:
    with _session_lock:
        s = _sessions.get(sid)
        if s is None:
            return None
        if s.age() > _SESSION_TTL:
            s.status = "expired"
            return s
        return s


# ---------------------------------------------------------------------
# 后台线程: Playwright 驱动
# ---------------------------------------------------------------------
def _apply_stealth(page) -> None:
    try:
        from playwright_stealth import stealth_sync  # type: ignore
        stealth_sync(page)
    except Exception as e:  # noqa: BLE001
        logger.warning("[autologin] stealth 未生效: %s", e)


def _extract_token_from_ls(page) -> str:
    """从 localStorage 常见键里找 Bearer Token(兜底)。"""
    try:
        ls = page.evaluate(
            """(ks) => {
                const out = {};
                for (const k of ks) { const v = localStorage.getItem(k); if (v) out[k] = v; }
                return out;
            }""",
            list(_TOKEN_LS_KEYS),
        )
    except Exception:  # noqa: BLE001
        return ""
    for v in (ls or {}).values():
        s = str(v).strip()
        if s.lower().startswith("bearer "):
            s = s[7:].strip()
        # TTC JWT 一般 3 段且较长
        if len(s) > 60 and s.count(".") >= 2:
            return s
    return ""


def _run_login_thread(sid: str) -> None:
    """Playwright 无头登录: 截图二维码 -> 抓 Token -> 落库绑定 -> 触发同步。"""
    sess = get_session(sid)
    if sess is None:
        return
    token = ""

    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError:
        sess.status = "failed"
        sess.error = "服务器未安装 Playwright"
        sess.touch()
        return

    login_url = settings.auth_login_url
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage",
                      "--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context()
            page = context.new_page()
            _apply_stealth(page)

            # 抓网络请求 Authorization 头(主通道)
            found: dict[str, str] = {}

            def on_request(req):
                auth = req.headers.get("authorization", "")
                if auth.lower().startswith("bearer "):
                    tok = auth[7:].strip()
                    if len(tok) > 60 and tok.count(".") >= 2:
                        found["token"] = tok

            page.on("request", on_request)
            page.goto(login_url, wait_until="domcontentloaded", timeout=60000)
            try:
                page.wait_for_load_state("load", timeout=8000)
            except Exception:  # noqa: BLE001
                pass
            time.sleep(1.5)

            # TTC 登录页通常先显示「飞书登录」按钮, 需点击才会跳到飞书 OAuth 出现二维码。
            # 兜底找第一个可见的 button / a / div[role=button] 点击(页面通常只有一个登录入口)
            try:
                candidates = page.locator(
                    "button:visible, a:visible[href], div[role='button']:visible"
                )
                count = candidates.count()
                for i in range(min(count, 5)):
                    b = candidates.nth(i)
                    try:
                        txt = (b.text_content() or "").strip().lower()
                        cls = (b.get_attribute("class") or "").lower()
                        if any(k in txt for k in ("飞书","feishu","login","登录","sign")) \
                           or any(k in cls for k in ("feishu","login","sign-in","signin")):
                            b.click(timeout=3000)
                            logger.info("[autologin] 已点击登录入口: text=%r", txt[:30])
                            break
                    except Exception:  # noqa: BLE001
                        continue
                else:
                    # 兜底: 直接点第一个可见的 button(TTC 登录页通常就一个)
                    if count > 0:
                        candidates.first.click(timeout=3000)
                        logger.info("[autologin] 兜底点击第一个可见 button")
            except Exception as e:  # noqa: BLE001
                logger.warning("[autologin] 点击登录入口失败(可能已自动跳转): %s", e)

            # 等待跳转(到 open.feishu.cn 飞书 OAuth 扫码页), 最多 15s
            try:
                page.wait_for_url("**/open.feishu.cn/**", timeout=15000)
            except Exception:  # noqa: BLE001
                logger.info("[autologin] 未跳到 open.feishu.cn, 当前 url=%s", page.url[:120])

            deadline = time.time() + _PENDING_TIMEOUT
            while time.time() < deadline:
                # 1) 网络头
                if not found.get("token"):
                    try:
                        page.wait_for_timeout(600)
                    except Exception:  # noqa: BLE001
                        pass
                # 2) localStorage 兜底
                if not found.get("token"):
                    t = _extract_token_from_ls(page)
                    if t:
                        found["token"] = t
                # 3) 刷新截图(二维码/进度)
                try:
                    sess.qr_png = page.screenshot(type="png")
                    sess.touch()
                except Exception:  # noqa: BLE001
                    pass
                if found.get("token"):
                    break
                time.sleep(_QR_REFRESH_INTERVAL)

            token = found.get("token", "")
            browser.close()
    except Exception as e:  # noqa: BLE001
        logger.exception("[autologin] sid=%s playwright error", sid)
        sess.status = "failed"
        sess.error = str(e)[:300]
        sess.touch()
        return

    if not token:
        sess.status = "timeout"
        sess.error = "超时未检测到登录, 请重试"
        sess.touch()
        return

    # ---- 解析并自动绑定 ----
    claims = decode_ttc_jwt_unverified(token)
    custom = (claims.get("CustomData") or {}) if claims else {}
    sess.token = token
    sess.bound_name = str(custom.get("nick_name") or "").strip()
    sess.space_id = str(custom.get("user_unique_id") or "").strip()

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.user_id == sess.user_id).first()
        if user is None:
            sess.status = "failed"
            sess.error = "Reloop 用户不存在, 请先登录"
        else:
            user.ttc_auth_token = token
            if sess.bound_name:
                user.ttc_bound_name = sess.bound_name
            if sess.space_id:
                user.ttc_space_id = sess.space_id
            db.commit()
            sess.status = "success"
            logger.info("[autologin] sid=%s user=%s bound=%s space=%s",
                        sid, sess.user_id, sess.bound_name, sess.space_id)
            # 自动触发同步(后台 sync_jobs)
            from reloop.modules.sync.client import talent_sync_service
            talent_sync_service.start_sync(
                db, sess.user_id, space_id=sess.space_id or None,
                auth_token=token or None,
            )
    except Exception as e:  # noqa: BLE001
        logger.exception("[autologin] bind failed sid=%s", sid)
        sess.status = "failed"
        sess.error = f"自动绑定失败: {e}"
    finally:
        db.close()
    sess.touch()
