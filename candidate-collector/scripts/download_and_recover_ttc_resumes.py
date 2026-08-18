#!/usr/bin/env python3
"""Download TTC resume PDFs via API and recover mosaic phone numbers with vision LLM.

Steps for each candidate with has_phone=false:
  1. Call /api/talent_store/v1/person_leads/resume/attachment/list
  2. Download the first PDF attachment from the signed OSS link
  3. Run mosaic_phone_recovery.recover_phone() on the PDF
  4. Save recovered phone back to the scored JSON

Usage:
    cd candidate-collector
    TTC_JWT_TOKEN=eyJ... \
    ENABLE_MOSAIC_PHONE_RECOVERY=true \
    TTC_LLM_API_KEY=sk-... \
    TTC_LLM_BASE_URL=https://api.kimi.com/coding/v1 \
    TTC_LLM_VISION_MODEL=kimi-for-coding \
    python3 scripts/download_and_recover_ttc_resumes.py \
        --input ../output/pdf/ai_product_manager_top50/full_pipeline_scored.json \
        --output ../data/ttc_top38_recovery.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional

import requests

# Playwright/httpx may fail with a SOCKS proxy; clear it for this probe.
for _proxy_var in ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
    os.environ.pop(_proxy_var, None)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from parsers.mosaic_phone_recovery import recover_phone

TTC_API_BASE = os.getenv("TTC_API_BASE", "https://api.ttcadvisory.com")
ATTACHMENT_LIST_URL = f"{TTC_API_BASE}/api/talent_store/v1/person_leads/resume/attachment/list"


def _ttc_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip() or "resume"


def _fetch_attachment_list(person_leads_id: str, token: str) -> list[dict[str, Any]]:
    resp = requests.post(
        ATTACHMENT_LIST_URL,
        headers=_ttc_headers(token),
        json={"person_leads_id": person_leads_id},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return (data.get("data") or {}).get("attachment_items", [])


def _download_pdf(url: str, dest: Path) -> None:
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as f:
        f.write(resp.content)


def _recover_one(candidate: dict[str, Any], token: str, pdf_dir: Path) -> dict[str, Any]:
    pid = candidate.get("person_leads_id", "")
    name = candidate.get("cn_name") or candidate.get("name", "unknown")
    result = {
        "person_leads_id": pid,
        "name": name,
        "original_has_phone": candidate.get("has_phone"),
        "downloaded_pdf": None,
        "recovered_phone": None,
        "confidence": None,
        "reasoning": None,
        "error": None,
    }

    try:
        attachments = _fetch_attachment_list(pid, token)
    except Exception as exc:
        result["error"] = f"attachment_list_failed: {exc}"
        return result

    if not attachments:
        result["error"] = "no_attachments"
        return result

    # Use the first attachment.
    att = attachments[0]
    link = att.get("link") or att.get("preview_url")
    if not link:
        result["error"] = "no_download_link"
        return result

    safe_name = _sanitize_filename(f"{name}_{pid}")
    pdf_path = pdf_dir / f"{safe_name}.pdf"
    counter = 1
    while pdf_path.exists():
        pdf_path = pdf_dir / f"{safe_name}_{counter}.pdf"
        counter += 1

    try:
        _download_pdf(link, pdf_path)
        result["downloaded_pdf"] = str(pdf_path)
    except Exception as exc:
        result["error"] = f"download_failed: {exc}"
        return result

    recovered = recover_phone(pdf_path, parser_name="paddleocr")
    if recovered and recovered.phone:
        result["recovered_phone"] = recovered.phone
        result["confidence"] = recovered.confidence
        result["reasoning"] = recovered.reasoning
    else:
        result["error"] = "vision_recovery_failed"

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Download TTC PDFs via API and recover phones.")
    parser.add_argument("--input", type=Path, required=True, help="Scored resume JSON.")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "ttc_top38_recovery.json",
                        help="Path to write recovery report.")
    parser.add_argument("--pdf-dir", type=Path, default=ROOT / "data" / "ttc_top38_pdfs",
                        help="Directory to save downloaded PDFs.")
    parser.add_argument("--workers", type=int, default=2,
                        help="Concurrent downloads (keep low to avoid rate limits).")
    args = parser.parse_args()

    token = os.getenv("TTC_JWT_TOKEN", "")
    if not token:
        print("错误：请设置 TTC_JWT_TOKEN 环境变量。")
        return 1
    if os.getenv("ENABLE_MOSAIC_PHONE_RECOVERY", "").lower() not in ("1", "true", "yes"):
        print("错误：请设置 ENABLE_MOSAIC_PHONE_RECOVERY=true。")
        return 1
    if not os.getenv("TTC_LLM_API_KEY"):
        print("错误：请设置 TTC_LLM_API_KEY 环境变量。")
        return 1

    with open(args.input, "r", encoding="utf-8") as f:
        scored = json.load(f)

    records = scored.get("data", [])
    targets = [r for r in records if not r.get("has_phone")]
    print(f"共 {len(records)} 人，其中 {len(targets)} 人缺少手机号，开始下载并恢复...")

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        results = list(ex.map(lambda c: _recover_one(c, token, args.pdf_dir), targets))

    # Update original records.
    recovered_map = {r["person_leads_id"]: r for r in results if r.get("recovered_phone")}
    updated_count = 0
    for record in records:
        pid = record.get("person_leads_id")
        if pid in recovered_map:
            record["has_phone"] = True
            record["phone"] = recovered_map[pid]["recovered_phone"]
            record["phone_recovery"] = {
                "confidence": recovered_map[pid]["confidence"],
                "reasoning": recovered_map[pid]["reasoning"],
                "pdf": recovered_map[pid]["downloaded_pdf"],
            }
            updated_count += 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    updated_path = args.input.with_suffix(".recovered.json")
    with open(updated_path, "w", encoding="utf-8") as f:
        json.dump(scored, f, ensure_ascii=False, indent=2)

    print(f"\n恢复完成：{len([r for r in results if r.get('recovered_phone')])} / {len(targets)}")
    print(f"已更新原 JSON：{updated_path}")
    print(f"恢复报告：{args.output}")
    print(f"PDF 下载目录：{args.pdf_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
