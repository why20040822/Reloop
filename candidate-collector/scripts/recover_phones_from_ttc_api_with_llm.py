#!/usr/bin/env python3
"""Recover phone numbers from TTC API raw resume text using LLM.

Reads a scored resume JSON (e.g. full_pipeline_scored.json), finds candidates
with has_phone=false, fetches their profile_summary from TTC API, then asks a
Kimi LLM to extract the mainland Chinese mobile number from raw_resume_text.

Usage:
    cd candidate-collector
    TTC_JWT_TOKEN=eyJ... \
    TTC_LLM_API_KEY=sk-... \
    TTC_LLM_BASE_URL=https://api.kimi.com/coding/v1 \
    TTC_LLM_MODEL=kimi-for-coding \
    python3 scripts/recover_phones_from_ttc_api_with_llm.py \
        --input ../output/pdf/ai_product_manager_top50/full_pipeline_scored.json \
        --output ../data/ttc_phone_recovery.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from utils.llm_client import complete, parse_json_safe

TTC_API_BASE = os.getenv("TTC_API_BASE", "https://api.ttcadvisory.com")
PHONE_RE = re.compile(r"(?<![\d])1[3-9]\d{9}(?![\d])")

_EXTRACTION_PROMPT = """You are extracting a mainland Chinese mobile phone number from a resume.

Resume text:
---
{text}
---

Instructions:
- Find the candidate's own mainland Chinese mobile number (11 digits, starts with 1).
- Do not confuse it with company phone numbers, ID numbers, or other people's numbers.
- If multiple personal mobile numbers appear, return the most prominent one.
- If you are uncertain or no personal mobile number exists, return null for phone.
- Respond with a JSON object exactly like:
  {"phone": "13800138000" | null, "confidence": 0.0-1.0, "reasoning": "short explanation"}
"""


def _ttc_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def fetch_profile_summary(person_leads_id: str, token: str) -> dict[str, Any]:
    url = f"{TTC_API_BASE}/api/talent_store/v1/time_based/profile_summary"
    resp = requests.get(
        url,
        headers=_ttc_headers(token),
        params={"person_leads_id": person_leads_id},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("data", {}) if isinstance(data, dict) else {}


def _extract_phone_regex(text: str) -> Optional[str]:
    if not text:
        return None
    match = PHONE_RE.search(text.replace(" ", "").replace("-", ""))
    return match.group(0) if match else None


def _extract_phone_llm(text: str) -> Optional[dict[str, Any]]:
    if not text or len(text.strip()) < 20:
        return None
    raw = complete(
        _EXTRACTION_PROMPT.format(text=text[:12000]),
        json_mode=True,
        temperature=1.0,
    )
    data = parse_json_safe(raw) or {}
    phone = data.get("phone")
    if phone:
        digits = "".join(ch for ch in str(phone) if ch.isdigit())
        if PHONE_RE.fullmatch(digits):
            return {
                "phone": digits,
                "confidence": float(data.get("confidence") or 0.0),
                "reasoning": data.get("reasoning"),
            }
    return None


def _recover_one(record: dict[str, Any], token: str) -> dict[str, Any]:
    pid = record.get("person_leads_id")
    name = record.get("cn_name") or record.get("name", "")
    result: dict[str, Any] = {
        "person_leads_id": pid,
        "name": name,
        "original_has_phone": record.get("has_phone"),
        "recovered_phone": None,
        "confidence": None,
        "reasoning": None,
        "source": None,
        "error": None,
    }
    if record.get("has_phone"):
        result["source"] = "already_has_phone"
        return result

    try:
        summary = fetch_profile_summary(pid, token)
    except Exception as exc:
        result["error"] = f"api_error: {exc}"
        return result

    raw_text = summary.get("raw_resume_text") or summary.get("resume_text") or ""
    if not raw_text:
        result["error"] = "no_raw_resume_text"
        return result

    # First try cheap regex; fall back to LLM if regex misses.
    regex_phone = _extract_phone_regex(raw_text)
    if regex_phone:
        result["recovered_phone"] = regex_phone
        result["confidence"] = 0.6
        result["reasoning"] = "regex from raw_resume_text"
        result["source"] = "regex"
        return result

    llm_result = _extract_phone_llm(raw_text)
    if llm_result:
        result["recovered_phone"] = llm_result["phone"]
        result["confidence"] = llm_result["confidence"]
        result["reasoning"] = llm_result["reasoning"]
        result["source"] = "llm"
    else:
        result["error"] = "llm_no_phone_found"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Recover phones from TTC API raw resume text via LLM.")
    parser.add_argument("--input", type=Path, required=True, help="Path to scored resume JSON.")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "ttc_phone_recovery.json",
                        help="Path to write recovery report.")
    parser.add_argument("--workers", type=int, default=4, help="Concurrent API calls.")
    args = parser.parse_args()

    token = os.getenv("TTC_JWT_TOKEN", "")
    if not token:
        print("错误：请设置 TTC_JWT_TOKEN 环境变量。")
        return 1

    if not os.getenv("TTC_LLM_API_KEY"):
        print("错误：请设置 TTC_LLM_API_KEY 环境变量（用于 LLM 抽取）。")
        return 1

    with open(args.input, "r", encoding="utf-8") as f:
        scored = json.load(f)

    records = scored.get("data", [])
    targets = [r for r in records if not r.get("has_phone")]
    print(f"共 {len(records)} 人，其中 {len(targets)} 人缺少手机号，开始恢复...")

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        results = list(ex.map(lambda r: _recover_one(r, token), targets))

    # Update original records with recovered phones.
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
                "source": recovered_map[pid]["source"],
            }
            updated_count += 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # Write updated scored JSON next to the original.
    updated_path = args.input.with_suffix(".recovered.json")
    with open(updated_path, "w", encoding="utf-8") as f:
        json.dump(scored, f, ensure_ascii=False, indent=2)

    print(f"\n恢复完成：{len([r for r in results if r.get('recovered_phone')])} / {len(targets)}")
    print(f"已更新原 JSON：{updated_path}")
    print(f"恢复报告：{args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
