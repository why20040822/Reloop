#!/usr/bin/env python3
# ONE-OFF (2026-08-03)
# Input: inspect --help and the operator invocation record before running.
# Execution: do not rerun without explicit operator confirmation.

"""
使用 Playwright 在已登录 TTC（Feishu SSO）的浏览器中批量下载简历 PDF。

核心思路：
1. 复用用户真实 Chrome 登录态（persistent context）。
2. 监听 `/api/crm/resumeFile/**` 请求，直接保存返回的 PDF 字节。
3. 若页面未自动加载简历，尝试点击「简历 / 附件 / 下载」相关元素触发。
4. 断点续传：已下载的 person_leads_id 会写入 progress.json，跳过重跑。

前置条件：
- macOS + Chrome（默认读取 ~/Library/Application Support/Google/Chrome）。
- 请先在普通 Chrome 里登录 TTC（飞书扫码/SSO），保持登录态。
- 运行前建议关闭 Chrome，避免 profile 被占用。

用法示例：
    # 先关闭 Chrome，然后用已登录的默认 profile 下载
    reloop/.venv/bin/python scripts/download_ttc_resume_pdfs.py \
        --input data/fa_shilai_match_combined/fa_shilai_all_scored.json \
        --output-dir data/ttc_resume_pdfs \
        --limit 50

    # 若 Chrome 已开，可连接 CDP（需手动启动 Chrome --remote-debugging-port=9222）
    reloop/.venv/bin/python scripts/download_ttc_resume_pdfs.py \
        --input data/fa_shilai_match_combined/fa_shilai_all_scored.json \
        --output-dir data/ttc_resume_pdfs \
        --connect-cdp http://localhost:9222 \
        --limit 10
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from playwright.sync_api import (
    BrowserContext,
    Page,
    Playwright,
    Route,
    Response,
    sync_playwright,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "ttc_resume_pdfs"
DEFAULT_USER_DATA_DIR = Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
DEFAULT_PROFILE = "Default"


def load_candidates(input_path: Path, only_cloud: bool = True) -> List[Dict[str, Any]]:
    data = json.loads(input_path.read_text(encoding="utf-8"))
    items = data.get("data", []) if isinstance(data, dict) else data
    candidates: List[Dict[str, Any]] = []
    for item in items:
        pid = item.get("person_leads_id")
        if not pid:
            continue
        if only_cloud and item.get("source") == "local_pdf":
            continue
        candidates.append({
            "person_leads_id": pid,
            "name": item.get("name", ""),
            "company": item.get("current_company", ""),
            "title": item.get("current_title", ""),
            "link": f"https://app.ttcadvisory.com/app/talent/{pid}",
        })
    return candidates


def safe_filename(name: str) -> str:
    """去除不能用在文件名中的字符。"""
    return re.sub(r'[\\/:*?"<>>|]', "_", name).strip() or "unknown"


class PdfCapture:
    """拦截并保存 /api/crm/resumeFile/** 返回的 PDF。"""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.saved: Set[str] = set()

    def _save_response(self, url: str, body: bytes, candidate: Dict[str, Any]) -> Optional[Path]:
        if len(body) < 1024 or body[:4] != b"%PDF":
            return None
        # URL 形如 https://xxx/api/crm/resumeFile/{resumeFileId}
        m = re.search(r"/api/crm/resumeFile/([^/?#]+)", url)
        file_id = m.group(1) if m else "unknown"
        name = safe_filename(candidate.get("name") or "unknown")
        company = safe_filename(candidate.get("company") or "unknown")
        pid = candidate.get("person_leads_id", "unknown")
        filename = f"{pid}_{file_id}_{name}_{company}.pdf"
        path = self.output_dir / filename
        path.write_bytes(body)
        self.saved.add(pid)
        return path

    def route_handler(self, candidate: Dict[str, Any]):
        def _handler(route: Route):
            try:
                response = route.fetch()
                body = response.body()
                saved = self._save_response(route.request.url, body, candidate)
                if saved:
                    print(f"  [PDF saved] {saved.name} ({len(body)} bytes)")
                route.fulfill(response=response)
            except Exception as exc:
                print(f"  [route error] {exc}")
                route.abort()
        return _handler

    def response_handler(self, candidate: Dict[str, Any]):
        def _handler(response: Response):
            if "/api/crm/resumeFile/" not in response.url:
                return
            if response.status != 200:
                return
            try:
                body = response.body()
                saved = self._save_response(response.url, body, candidate)
                if saved:
                    print(f"  [PDF saved via response] {saved.name} ({len(body)} bytes)")
            except Exception:
                pass
        return _handler


class Downloader:
    def __init__(
        self,
        output_dir: Path,
        user_data_dir: Path,
        profile_directory: str,
        connect_cdp: Optional[str],
        headless: bool,
        delay: float,
        timeout: int,
    ):
        self.output_dir = output_dir
        self.user_data_dir = user_data_dir
        self.profile_directory = profile_directory
        self.connect_cdp = connect_cdp
        self.headless = headless
        self.delay = delay
        self.timeout = timeout
        self.progress_file = output_dir / "download_progress.json"
        self.progress: Dict[str, Any] = self._load_progress()

    def _load_progress(self) -> Dict[str, Any]:
        if self.progress_file.exists():
            try:
                return json.loads(self.progress_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"completed": [], "failed": [], "skipped_no_resume": []}

    def _save_progress(self) -> None:
        self.progress_file.write_text(json.dumps(self.progress, ensure_ascii=False, indent=2), encoding="utf-8")

    def _create_context(self, playwright: Playwright) -> BrowserContext:
        if self.connect_cdp:
            print(f"[Browser] 通过 CDP 连接 {self.connect_cdp}")
            browser = playwright.chromium.connect_over_cdp(self.connect_cdp)
            contexts = browser.contexts
            if contexts:
                return contexts[0]
            return browser.new_context(viewport={"width": 1400, "height": 900})

        print(f"[Browser] 使用 Chrome profile: {self.user_data_dir}/{self.profile_directory}")
        print("[Browser] 如果提示 profile 被占用，请先完全关闭 Chrome 再运行。")
        return playwright.chromium.launch_persistent_context(
            str(self.user_data_dir),
            headless=self.headless,
            viewport={"width": 1400, "height": 900},
            args=[
                f"--profile-directory={self.profile_directory}",
                "--disable-blink-features=AutomationControlled",
            ],
        )

    def _try_click_resume_trigger(self, page: Page) -> bool:
        """尝试点击可能触发简历预览/下载的元素。"""
        selectors = [
            'button:has-text("简历")',
            'div:has-text("简历"):not(:has(*))',
            'button:has-text("附件")',
            'div:has-text("附件"):not(:has(*))',
            'button:has-text("下载")',
            'a:has-text("下载")',
            'button:has-text("导出")',
            '[data-testid*="resume"]',
            '[data-testid*="attachment"]',
            '[class*="resume"]',
            '[class*="attachment"]',
        ]
        for sel in selectors:
            try:
                els = page.locator(sel).all()
                for el in els:
                    if el.is_visible():
                        el.click(timeout=3000)
                        return True
            except Exception:
                continue
        return False

    def download_one(self, page: Page, candidate: Dict[str, Any], capture: PdfCapture) -> str:
        pid = candidate["person_leads_id"]
        if pid in self.progress["completed"]:
            return "already_done"

        url = candidate["link"]
        print(f"\n[{pid}] {candidate.get('name')} @ {candidate.get('company')}")
        print(f"  打开 {url}")

        # 设置本次候选人的路由拦截
        page.route("**/api/crm/resumeFile/**", capture.route_handler(candidate))

        try:
            page.goto(url, wait_until="load", timeout=self.timeout * 1000)
        except Exception as exc:
            print(f"  [goto error] {exc}")
            self.progress["failed"].append({"pid": pid, "reason": "goto_error", "error": str(exc)})
            return "failed"

        # 等待页面稳定并尝试自动触发简历
        time.sleep(2.5)
        clicked = self._try_click_resume_trigger(page)
        if clicked:
            print("  已尝试点击简历/附件元素")
            time.sleep(2.5)

        # 再等待一下网络请求完成
        time.sleep(1.5)

        # 移除本次路由，避免影响下一个
        page.unroute("**/api/crm/resumeFile/**")

        if pid in capture.saved:
            self.progress["completed"].append(pid)
            return "success"

        # 未捕获到 PDF，截图留档帮助调试
        screenshot_path = self.output_dir / "debug" / f"{pid}.png"
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            page.screenshot(path=str(screenshot_path), full_page=False)
            print(f"  [调试截图] {screenshot_path}")
        except Exception:
            pass

        self.progress["skipped_no_resume"].append(pid)
        return "no_resume"

    def run(self, candidates: List[Dict[str, Any]], limit: int = 0) -> None:
        with sync_playwright() as playwright:
            context = self._create_context(playwright)
            page = context.new_page()

            # 监听所有 /api/crm/resumeFile 响应（兜底）
            capture = PdfCapture(self.output_dir)
            page.on("response", capture.response_handler({"person_leads_id": "unknown", "name": "", "company": ""}))

            targets = candidates[:limit] if limit > 0 else candidates
            total = len(targets)
            for idx, candidate in enumerate(targets, 1):
                print(f"\n=== {idx}/{total} ===")
                status = self.download_one(page, candidate, capture)
                self._save_progress()
                if status == "success":
                    print(f"  成功 ({len(self.progress['completed'])}/{total})")
                elif status == "already_done":
                    print(f"  已跳过（之前已下载）")
                elif status == "no_resume":
                    print(f"  未找到简历文件")
                else:
                    print(f"  失败")

                if self.delay > 0:
                    time.sleep(self.delay)

            print("\n下载完成。")
            print(f"  成功：{len(self.progress['completed'])}")
            print(f"  无简历：{len(self.progress['skipped_no_resume'])}")
            print(f"  失败：{len(self.progress['failed'])}")
            print(f"  PDF 保存目录：{self.output_dir}")

            if not self.connect_cdp:
                context.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="TTC 简历 PDF 浏览器自动化下载")
    parser.add_argument("--input", type=Path, default=REPO_ROOT / "data" / "fa_shilai_match_combined" / "fa_shilai_all_scored.json",
                        help="候选人 JSON，需包含 person_leads_id")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
                        help="PDF 保存目录")
    parser.add_argument("--user-data-dir", type=Path, default=DEFAULT_USER_DATA_DIR,
                        help="Chrome user data 目录")
    parser.add_argument("--profile-directory", type=str, default=DEFAULT_PROFILE,
                        help="Chrome profile 名称")
    parser.add_argument("--connect-cdp", type=str, default=None,
                        help="已开启远程调试的 Chrome CDP 地址，如 http://localhost:9222")
    parser.add_argument("--headless", action="store_true",
                        help="无头模式（可能无法通过飞书登录态，默认关闭）")
    parser.add_argument("--limit", type=int, default=0,
                        help="最多下载数量（0=全部）")
    parser.add_argument("--delay", type=float, default=2.0,
                        help="每页下载间隔秒数")
    parser.add_argument("--timeout", type=int, default=60,
                        help="页面加载超时秒数")
    parser.add_argument("--include-local", action="store_true",
                        help="同时下载本地 PDF 对应的 TTC 页面（默认只下载云端）")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"错误：输入文件不存在 {args.input}", file=sys.stderr)
        return 1

    candidates = load_candidates(args.input, only_cloud=not args.include_local)
    print(f"[INFO] 共 {len(candidates)} 位云端候选人待下载")

    downloader = Downloader(
        output_dir=args.output_dir,
        user_data_dir=args.user_data_dir,
        profile_directory=args.profile_directory,
        connect_cdp=args.connect_cdp,
        headless=args.headless,
        delay=args.delay,
        timeout=args.timeout,
    )
    downloader.run(candidates, limit=args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
