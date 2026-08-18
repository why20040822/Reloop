"""Use Playwright to discover the TTC PDF download endpoint.

This is a one-off probe: authenticate with ``TTC_JWT``, open a candidate
page, click the download button, and print sanitized request metadata.
"""

import asyncio
import os

from playwright.async_api import async_playwright


# Playwright/httpx may fail with a SOCKS proxy; clear it for this probe.
for _proxy_var in (
    "ALL_PROXY",
    "all_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "HTTPS_PROXY",
    "https_proxy",
):
    os.environ.pop(_proxy_var, None)

# TOKEN 走环境变量,禁止硬编码进仓库(此前硬编码的 JWT 已泄露,务必轮换)。
TOKEN = os.environ.get("TTC_JWT_TOKEN", "")
PID = os.environ.get("TTC_PROBE_PID", "PL2026640500396716032")


async def main() -> None:
    if not TOKEN:
        raise SystemExit("请先通过环境变量 TTC_JWT 提供登录令牌")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        captured_requests: list[dict[str, object]] = []
        captured_responses: list[dict[str, object]] = []

        def on_request(req) -> None:
            url = req.url
            if any(marker in url for marker in ("ttcadvisory", "download", "pdf", "attachment")):
                captured_requests.append(
                    {"url": url, "method": req.method, "has_auth": "authorization" in req.headers}
                )

        def on_response(res) -> None:
            url = res.url
            if any(marker in url for marker in ("ttcadvisory", "download", "pdf", "attachment")):
                captured_responses.append(
                    {
                        "url": url,
                        "status": res.status,
                        "content_type": res.headers.get("content-type"),
                    }
                )

        page.on("request", on_request)
        page.on("response", on_response)

        await page.goto(
            "https://app.ttcadvisory.com/",
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        await page.evaluate(
            """(token) => {
                localStorage.setItem('token', token);
                localStorage.setItem('jwt', token);
                localStorage.setItem('accessToken', token);
                localStorage.setItem('auth_token', token);
                sessionStorage.setItem('token', token);
            }""",
            TOKEN,
        )
        await context.add_cookies(
            [
                {
                    "name": name,
                    "value": TOKEN,
                    "domain": ".ttcadvisory.com",
                    "path": "/",
                }
                for name in ("token", "jwt")
            ]
        )

        await page.goto(
            f"https://app.ttcadvisory.com/app/talent/{PID}",
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        await asyncio.sleep(5)

        selectors = [
            "button:has-text('下载 PDF')",
            "button:has-text('下载简历')",
            "button:has-text('下载附件')",
            "a:has-text('下载 PDF')",
            "a:has-text('下载简历')",
            "[title*='下载']",
            "[title*='PDF']",
        ]
        clicked = False
        for selector in selectors:
            try:
                button = page.locator(selector).first
                if await button.is_visible(timeout=2_000):
                    print(f"Found button: {selector}")
                    await button.click()
                    clicked = True
                    await asyncio.sleep(3)
                    break
            except Exception:
                continue

        if not clicked:
            print("No download button found. Page buttons:")
            buttons = await page.locator("button, a").all_inner_texts()
            for label in buttons[:50]:
                if any(marker in label for marker in ("下载", "PDF", "简历")):
                    print(f"  - {label.strip()}")

        print("\n--- Captured requests ---")
        for request in captured_requests:
            print(request["method"], str(request["url"])[:300])
            if request["has_auth"]:
                print("  Authorization: <redacted>")

        print("\n--- Captured responses ---")
        for response in captured_responses:
            print(response["status"], str(response["url"])[:300])
            print("  content-type:", response["content_type"])

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
