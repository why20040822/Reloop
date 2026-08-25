"""登录态采集: 打开飞书扫码页, 人工登录一次, 存加密 storageState。

用法(在有桌面/可扫码的环境手动跑一次):
    python -m reloop.modules.auth.capture

流程:
  1. Playwright 启动有头浏览器(headless=False), 应用 stealth 反检测;
  2. 打开 BRAINX_AUTH_LOGIN_URL, 你用飞书扫码登录;
  3. 检测到登录完成(URL 不再含 login marker)后, 抓 storageState;
  4. 通过 vault 加密落盘 -> .auth/ttc_state.enc。

之后 provider.py 会从该加密文件自动解出 token, sync/client 无需再手填。
Playwright 是懒加载导入: 只有真正跑采集时才需要它, 不影响 API/降级路径。
"""

from __future__ import annotations

import logging
import sys

from reloop.config import settings
from reloop.modules.auth import vault

logger = logging.getLogger(__name__)


def _apply_stealth(page) -> None:
    """应用 playwright-stealth 反检测(飞书扫码页较敏感)。"""
    try:
        from playwright_stealth import stealth_sync  # type: ignore
        stealth_sync(page)
        logger.info("[capture] 已应用 stealth 反检测")
    except Exception as e:  # noqa: BLE001
        logger.warning("[capture] stealth 未生效(不影响登录, 仅反检测减弱): %s", e)


def capture_login_state(timeout_sec: int = 300) -> bool:
    """打开登录页, 等待人工扫码, 成功后加密保存 storageState。

    返回 True=已保存; False=超时/失败。
    需先配置 BRAINX_AUTH_VAULT_KEY, 否则拒绝明文保存。
    """
    if not vault.has_vault_key():
        print("❌ 未配置 BRAINX_AUTH_VAULT_KEY。先生成密钥:")
        print('   python -c "from cryptography.fernet import Fernet; '
              'print(Fernet.generate_key().decode())"')
        print("   把输出填进 .env 的 BRAINX_AUTH_VAULT_KEY 再重试。")
        return False

    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError:
        print("❌ 未安装 Playwright。请执行:")
        print("   pip install playwright playwright-stealth && playwright install chromium")
        return False

    login_url = settings.auth_login_url
    marker = (settings.auth_login_done_marker or "login").lower()
    print(f"🌐 打开登录页: {login_url}")
    print("   请在弹出的浏览器里用飞书扫码登录, 登录完成后本脚本会自动保存登录态…")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        _apply_stealth(page)
        page.goto(login_url, wait_until="domcontentloaded")

        # 轮询等待登录完成: URL 不再含 marker 即视为已登录
        import time
        deadline = time.time() + timeout_sec
        logged_in = False
        while time.time() < deadline:
            cur = (page.url or "").lower()
            if marker not in cur:
                logged_in = True
                break
            time.sleep(1.5)

        if not logged_in:
            print(f"⏰ {timeout_sec}s 内未检测到登录完成, 取消保存。")
            browser.close()
            return False

        # 抓 cookie + localStorage 一把存
        state = context.storage_state()
        browser.close()

    path = vault.save_state(state)
    print(f"✅ 登录态已加密保存: {path}")
    print("   现在 sync/client 会自动读取, 无需再手填 BRAINX_TTC_TALENT_AUTH_TOKEN。")
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ok = capture_login_state()
    sys.exit(0 if ok else 1)
