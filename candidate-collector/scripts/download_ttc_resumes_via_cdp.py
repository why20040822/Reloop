#!/usr/bin/env python3
"""Download resume PDFs from the user's already-running Chrome via CDP.

The user must have started Chrome with --remote-debugging-port=9222 and logged
into the TTC web app. This script connects to that browser, navigates to each
candidate page, clicks "下载 PDF", and saves the downloads.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright, Download

ROOT = Path(__file__).resolve().parent.parent


def _sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip() or "resume"


async def _download_one(page, candidate: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    pid = candidate.get("person_leads_id", "")
    name = candidate.get("cn_name") or candidate.get("name", "unknown")
    result = {"person_leads_id": pid, "name": name, "file": None, "error": None}

    url = f"https://app.ttcadvisory.com/app/talent/{pid}"
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(4)  # Let SPA render
    except Exception as exc:
        result["error"] = f"navigation_failed: {exc}"
        return result

    selectors = [
        "button:has-text('下载 PDF')",
        "button:has-text('下载简历')",
        "button:has-text('下载附件')",
        "a:has-text('下载 PDF')",
        "a:has-text('下载简历')",
        "[title*='下载 PDF']",
        "[title*='下载简历']",
        "[aria-label*='下载']",
    ]

    download_event: Download | None = None
    clicked = False
    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=3000):
                download_promise = page.wait_for_event("download", timeout=30000)
                await btn.click()
                try:
                    download_event = await asyncio.wait_for(download_promise, timeout=30)
                    clicked = True
                    break
                except asyncio.TimeoutError:
                    continue
        except Exception:
            continue

    if not clicked:
        try:
            buttons = await page.locator("button, a").all_inner_texts()
            relevant = [b.strip() for b in buttons if "下载" in b or "PDF" in b or "简历" in b]
            result["error"] = f"no_download_button; visible: {relevant[:10]}"
        except Exception:
            result["error"] = "no_download_button"
        return result

    if download_event:
        safe_name = _sanitize_filename(f"{name}_{pid}")
        dest = output_dir / f"{safe_name}.pdf"
        counter = 1
        while dest.exists():
            dest = output_dir / f"{safe_name}_{counter}.pdf"
            counter += 1
        try:
            await download_event.save_as(str(dest))
            result["file"] = str(dest)
        except Exception as exc:
            result["error"] = f"download_save_failed: {exc}"
    else:
        result["error"] = "download_event_missing"

    return result


async def main() -> int:
    parser = argparse.ArgumentParser(description="Download TTC PDFs via CDP-connected Chrome.")
    parser.add_argument("--input", type=Path, required=True, help="Scored resume JSON.")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "ttc_top38_pdfs",
                        help="Directory to save PDFs.")
    parser.add_argument("--cdp-url", type=str, default="http://127.0.0.1:9222",
                        help="Chrome DevTools Protocol URL.")
    parser.add_argument("--limit", type=int, default=0, help="Max candidates (0=all).")
    args = parser.parse_args()

    if not args.input.is_file():
        print(f"Input not found: {args.input}")
        return 1

    args.output.mkdir(parents=True, exist_ok=True)

    with open(args.input, "r", encoding="utf-8") as f:
        scored = json.load(f)

    records = scored.get("data", [])
    targets = [r for r in records if not r.get("has_phone")]
    if args.limit > 0:
        targets = targets[:args.limit]

    print(f"Will download PDFs for {len(targets)} candidates to {args.output}")
    print(f"Connecting to Chrome at {args.cdp_url} ...")

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(args.cdp_url)
        if browser.contexts:
            context = browser.contexts[0]
        else:
            context = await browser.new_context()
        page = context.pages[0] if context.pages else await context.new_page()

        results: list[dict[str, Any]] = []
        for i, candidate in enumerate(targets, 1):
            print(f"[{i}/{len(targets)}] {candidate.get('cn_name', 'unknown')} ({candidate.get('person_leads_id', '')})")
            result = await _download_one(page, candidate, args.output)
            results.append(result)
            if result.get("file"):
                print(f"  -> saved: {result['file']}")
            else:
                print(f"  -> error: {result['error']}")

        await browser.close()

    report_path = args.output / "download_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    success = sum(1 for r in results if r.get("file"))
    print(f"\nDone: {success}/{len(targets)} PDFs downloaded.")
    print(f"Report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
