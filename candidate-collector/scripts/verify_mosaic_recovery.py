#!/usr/bin/env python3
"""Manual verification for mosaic phone recovery using the de-sensitized fixture.

Usage:
    cd candidate-collector
    ENABLE_MOSAIC_PHONE_RECOVERY=true \
    TTC_LLM_API_KEY=sk-... \
    TTC_LLM_BASE_URL=https://api.moonshot.ai/v1 \
    TTC_LLM_VISION_MODEL=kimi-k2.6 \
    python3 scripts/verify_mosaic_recovery.py

If the fixture does not exist, the script exits with code 1.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from parsers.mosaic_phone_recovery import recover_phone

FIXTURE = Path(__file__).resolve().parent.parent.parent / "简历数据" / "简历_脱敏.pdf"


def main() -> int:
    if os.getenv("ENABLE_MOSAIC_PHONE_RECOVERY", "").lower() not in ("1", "true", "yes"):
        print("Set ENABLE_MOSAIC_PHONE_RECOVERY=true and configure TTC_LLM_API_KEY.")
        return 1
    if not FIXTURE.is_file():
        print(f"Fixture not found: {FIXTURE}")
        return 1

    result = recover_phone(FIXTURE, parser_name="paddleocr")
    if not result:
        print("No phone could be recovered (recovery disabled, no API key, or too blurred).")
        return 1

    print(json.dumps({
        "phone": result.phone,
        "confidence": result.confidence,
        "reasoning": result.reasoning,
        "source": result.source,
    }, ensure_ascii=False, indent=2))
    return 0 if result.phone else 1


if __name__ == "__main__":
    raise SystemExit(main())
