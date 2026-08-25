"""登录态健康检查: 用现有加密登录态试调一次真实接口, 判定是否仍有效。

用法:
    python -m reloop.modules.auth.check

判定:
  - ok        : 接口 200, 登录态有效
  - expired   : 接口 401/403, 登录态已过期 -> 需重新扫码 (python -m reloop.modules.auth.capture)
  - no_state  : 没有登录态也没有 .env token
  - error     : 网络/其它错误 (无法判定)

可被定时任务调用: 退出码 0=ok, 1=需重扫, 2=其它。
"""

from __future__ import annotations

import logging
import sys

import httpx

from reloop.config import settings
from reloop.modules.auth import provider, vault

logger = logging.getLogger(__name__)


def check_login_state(space_id: str | None = None) -> dict:
    """试调真实接口第 1 页, 返回 {status, source, detail}。"""
    auth = provider.resolve_auth()
    if auth["source"] == "none":
        return {"status": "no_state", "source": "none",
                "detail": "无加密登录态也无 .env token。先跑 capture 扫码或填 BRAINX_TTC_TALENT_AUTH_TOKEN。"}

    space_id = space_id or settings.ttc_talent_space_id
    base_path = settings.ttc_talent_api_path.rstrip("/")
    url = f"{settings.ttc_talent_base_url}{base_path}/{space_id}/talents"
    headers = {"Accept": "application/json"}
    if auth["token"]:
        headers["Authorization"] = f"Bearer {auth['token']}"
    if auth["cookie"]:
        headers["Cookie"] = auth["cookie"]

    try:
        resp = httpx.get(url, params={"page": 1, "page_size": 1}, headers=headers, timeout=15)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "source": auth["source"], "detail": f"请求异常: {e}"}

    if resp.status_code == 200:
        total = ((resp.json() or {}).get("data") or {}).get("total")
        return {"status": "ok", "source": auth["source"],
                "detail": f"登录态有效 (接口 200, total={total})"}
    if resp.status_code in (401, 403):
        return {"status": "expired", "source": auth["source"],
                "detail": f"登录态已过期 (HTTP {resp.status_code})。请重新扫码: "
                          f"python -m reloop.modules.auth.capture"}
    return {"status": "error", "source": auth["source"],
            "detail": f"接口返回 HTTP {resp.status_code}, 无法判定 (可能接口路径需按真实 XHR 调整)"}


_EXIT = {"ok": 0, "expired": 1, "no_state": 1, "error": 2}
_ICON = {"ok": "✅", "expired": "⏰", "no_state": "⚪", "error": "⚠️"}


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    r = check_login_state()
    print(f"{_ICON.get(r['status'], '?')} [{r['status']}] 鉴权来源={r['source']}")
    print(f"   {r['detail']}")
    if r["status"] == "expired":
        print("   👉 登录态过期不影响服务启动: sync 会自动降级为'跳过接口拉取', 可继续用 ingest 导入。")
    return _EXIT.get(r["status"], 2)


if __name__ == "__main__":
    sys.exit(main())
