# ONE-OFF (2026-08-03)
# Input: inspect --help and the operator invocation record before running.
# Execution: do not rerun without explicit operator confirmation.

"""Use Playwright to discover the TTC PDF download endpoint.

This is a one-off probe: log in via JWT, open a candidate page, click the
"download PDF" button, and print the intercepted request/response.
"""

import asyncio
import os
from playwright.async_api import async_playwright

# Playwright/httpx may fail with a SOCKS proxy; clear it for this probe.
for _proxy_var in ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
    os.environ.pop(_proxy_var, None)

TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3ODgxMDI4OTMsImlhdCI6MTc4MjkxODg5MywiQ3VzdG9tRGF0YSI6eyJuaWNrX25hbWUiOiJNaWEg6ZKf56yR5ZKqIiwidXNlcl91bmlxdWVfaWQiOiJVMjA3MTU4NTk4NzQ0MDM5ODMzNiIsInJvbGVfdW5pcXVlX2lkIjoiIiwiYmVsb25nX3RvX3R0YyI6dHJ1ZSwib3Blbl9pZCI6Im91X2QyZTM3MWYwMTQyYWQ2MDAyZDhiZDNjZGJlY2NhM2NkIiwidW5pb25faWQiOiJvbl9kYmM5MWRiOGFlNmQ3MWEwN2Y0NzkyYjhkM2JhODkxNSIsInRhbGVudF9pZCI6IjEyODM1YjgwN2UwZjU3NDAiLCJ0aGlyZF9iaW5kX3BsYXRmb3JtIjoiRkVJU0hVIiwiZXh0ZXJuYWwiOmZhbHNlfX0.Jm1wP676-XMUHDoHA38gYoLtX3Jllkvo4nAnUz4xFM0"
PID = "PL2026640500396716032"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        # Intercept all network requests/responses.
        captured_requests = []
        captured_responses = []

        def on_request(req):
            url = req.url
            if "ttcadvisory" in url or "download" in url or "pdf" in url or "attachment" in url:
                captured_requests.append({"url": url, "method": req.method, "headers": dict(req.headers)})

        def on_response(res):
            url = res.url
            if "ttcadvisory" in url or "download" in url or "pdf" in url or "attachment" in url:
                captured_responses.append({"url": url, "status": res.status, "headers": dict(res.headers)})

        page.on("request", on_request)
        page.on("response", on_response)

        # Navigate once to establish origin, then set auth and reload.
        await page.goto("https://app.ttcadvisory.com/", wait_until="domcontentloaded", timeout=60000)

        # Try multiple common storage keys.
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

        await context.add_cookies([{
            "name": "token",
            "value": TOKEN,
            "domain": ".ttcadvisory.com",
            "path": "/",
        }, {
            "name": "jwt",
            "value": TOKEN,
            "domain": ".ttcadvisory.com",
            "path": "/",
        }])

        await page.goto(f"https://app.ttcadvisory.com/app/talent/{PID}", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(5)

        # Try to find and click a "下载 PDF" button.
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
        for sel in selectors:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=2000):
                    print(f"Found button: {sel}")
                    await btn.click()
                    clicked = True
                    await asyncio.sleep(3)
                    break
            except Exception:
                continue

        if not clicked:
            print("No download button found. Page buttons:")
            buttons = await page.locator("button, a").all_inner_texts()
            for b in buttons[:50]:
                if "下载" in b or "PDF" in b or "简历" in b:
                    print(f"  - {b.strip()}")

        print("\n--- Captured requests ---")
        for r in captured_requests:
            print(r["method"], r["url"][:300])
            auth = r["headers"].get("authorization") or r["headers"].get("Authorization")
            if auth:
                print("  Authorization:", auth[:60])

        print("\n--- Captured responses ---")
        for r in captured_responses:
            print(r["status"], r["url"][:300])
            print("  content-type:", r["headers"].get("content-type"))

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
