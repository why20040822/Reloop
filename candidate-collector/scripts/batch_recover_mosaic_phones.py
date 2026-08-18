#!/usr/bin/env python3
"""Batch recover mosaic-obscured phone numbers from local resume PDFs.

Only files whose regular OCR/regex extraction fails to find a phone number are
sent to the vision LLM, keeping API cost minimal. Results are written to a JSON
report for human review before any database update.

Usage:
    cd candidate-collector
    ENABLE_MOSAIC_PHONE_RECOVERY=true \
    TTC_LLM_API_KEY=sk-... \
    TTC_LLM_BASE_URL=https://api.moonshot.ai/v1 \
    TTC_LLM_VISION_MODEL=kimi-k2.6 \
    python3 scripts/batch_recover_mosaic_phones.py \
        --input ../简历数据 \
        --output ../data/mosaic_recovery_report.json \
        --limit 20

The report format is:
    [
      {
        "file": ".../简历_脱敏.pdf",
        "parser": "paddleocr",
        "original_phone": null,
        "recovered_phone": "13800138000",
        "confidence": 0.35,
        "reasoning": "digits visible through light mosaic",
        "review_status": "needs_review"
      },
      ...
    ]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from parsers.mosaic_phone_recovery import recover_phone
from parsers.unified_parser import parse_resume_file


def _find_pdfs(input_dir: Path) -> list[Path]:
    return sorted(input_dir.glob("*.pdf"))


def _recover_one(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "file": str(path),
        "parser": None,
        "original_phone": None,
        "recovered_phone": None,
        "confidence": None,
        "reasoning": None,
        "review_status": None,
        "error": None,
    }
    try:
        record = parse_resume_file(path)
    except Exception as exc:
        result["error"] = f"parse_failed: {exc}"
        return result

    result["parser"] = record.parser_name
    result["original_phone"] = record.phone
    result["review_status"] = record.review_status

    # If regex/OCR already found a phone, nothing to do.
    if record.phone:
        result["reasoning"] = "phone_already_visible"
        return result

    # Attempt vision recovery for any PDF/image with a missing phone.
    # This also catches text-based PDFs where only the phone region is mosaic-blurred.
    recovered = recover_phone(path, parser_name=record.parser_name or "paddleocr")
    if recovered and recovered.phone:
        result["recovered_phone"] = recovered.phone
        result["confidence"] = recovered.confidence
        result["reasoning"] = recovered.reasoning
        result["review_status"] = "needs_review"
    else:
        result["reasoning"] = "recovery_failed_or_uncertain"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Batch recover mosaic phone numbers from local resumes.")
    parser.add_argument("--input", type=Path, default=Path(__file__).resolve().parent.parent.parent / "简历数据",
                        help="Directory containing resume PDFs.")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "mosaic_recovery_report.json",
                        help="Path to write the JSON report.")
    parser.add_argument("--limit", type=int, default=0,
                        help="Maximum number of PDFs to process (0 = unlimited).")
    parser.add_argument("--yes", action="store_true",
                        help="Skip the cost confirmation prompt.")
    args = parser.parse_args(argv)

    if os.getenv("ENABLE_MOSAIC_PHONE_RECOVERY", "").lower() not in ("1", "true", "yes"):
        print("ENABLE_MOSAIC_PHONE_RECOVERY is not enabled. Set it to 'true' to run recovery.")
        return 1
    if not os.getenv("TTC_LLM_API_KEY"):
        print("TTC_LLM_API_KEY is not set. Please configure it before running recovery.")
        return 1

    if not args.input.is_dir():
        print(f"Input directory not found: {args.input}")
        return 1

    pdfs = _find_pdfs(args.input)
    if args.limit > 0:
        pdfs = pdfs[:args.limit]

    estimated_visual_calls = sum(1 for p in pdfs)  # upper bound; actual calls only on missing phones
    print(f"Found {len(pdfs)} PDFs to scan (up to {estimated_visual_calls} may call vision API).")
    if not args.yes:
        answer = input("Continue? [y/N] ")
        if answer.lower() not in ("y", "yes"):
            print("Aborted.")
            return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    report: list[dict[str, Any]] = []
    stats = {"total": 0, "already_visible": 0, "recovered": 0, "failed": 0, "errors": 0}

    for i, pdf in enumerate(pdfs, 1):
        print(f"[{i}/{len(pdfs)}] {pdf.name} ...", end=" ", flush=True)
        entry = _recover_one(pdf)
        report.append(entry)
        stats["total"] += 1

        if entry.get("error"):
            stats["errors"] += 1
            print(f"ERROR {entry['error']}")
        elif entry.get("reasoning") == "phone_already_visible":
            stats["already_visible"] += 1
            print(f"already has phone {entry['original_phone']}")
        elif entry.get("recovered_phone"):
            stats["recovered"] += 1
            print(f"recovered {entry['recovered_phone']} (conf={entry['confidence']})")
        else:
            stats["failed"] += 1
            print(f"{entry.get('reasoning')}")

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("\n--- Summary ---")
    print(json.dumps(stats, indent=2))
    print(f"Report written to: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
