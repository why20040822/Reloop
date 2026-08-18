"""Recover mosaic/pixelated phone numbers from resume images using a vision LLM.

This module is intentionally conservative: it only runs when regular OCR and regex
fail to extract a phone number, and any recovered value is flagged for human review.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from image_processing.ocr import pdf_page_images
from utils.llm_client import complete_with_image, parse_json_safe

# Loose phone regex used only to validate a recovered candidate.
PHONE_RE = re.compile(r"(?<![\d])1[3-9]\d{9}(?![\d])")

_SYSTEM_PROMPT = (
    "You are a resume data recovery assistant. Your only task is to recover a "
    "mainland Chinese mobile phone number that may be partially obscured by a "
    "mosaic or pixelation effect in the provided resume image."
)

_USER_PROMPT = (
    "Look at this resume image carefully. If you can infer the candidate's "
    "mainland Chinese mobile phone number (11 digits, starts with 1) even though "
    "it may be mosaic-blurred, return it. If you are not confident or cannot "
    "determine the number, return null for phone. Do not guess or make up a number.\n\n"
    "Respond with a JSON object exactly in this format:\n"
    '{\n  "phone": "13800138000" | null,\n  "confidence": 0.0-1.0,\n  "reasoning": "short explanation"\n}'
)

MAX_SYSTEM_CONFIDENCE = 0.4


@dataclass
class RecoveryResult:
    """Result of a mosaic phone recovery attempt."""

    phone: Optional[str]
    confidence: float
    reasoning: Optional[str]
    source: str


def _enabled() -> bool:
    return os.getenv("ENABLE_MOSAIC_PHONE_RECOVERY", "").lower() in ("1", "true", "yes")


def _validate_phone(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    digits = "".join(ch for ch in value if ch.isdigit())
    if PHONE_RE.fullmatch(digits):
        return digits
    return None


def _first_page_image(path: Path, parser_name: str) -> Optional[Path]:
    """Return a representative image path for the given file."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            pages = pdf_page_images(path, filetype="pdf", dpi=200)
        except Exception:
            return None
        if pages:
            # Contact info is almost always on the first page of a resume.
            return pages[0][1]
        return None
    if suffix in (".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"):
        return path
    return None


def recover_phone(
    path: Path,
    parser_name: str,
    ocr_confidence: float = 1.0,
) -> Optional[RecoveryResult]:
    """Attempt to recover a phone number from a mosaic-obscured resume image.

    Returns ``None`` when recovery is disabled, the file cannot be rendered to an
    image, or no confident phone number can be recovered.
    """
    if not _enabled():
        return None

    image_path = _first_page_image(path, parser_name)
    if not image_path:
        return None

    model = os.getenv("TTC_LLM_VISION_MODEL") or os.getenv("TTC_LLM_MODEL")
    try:
        raw = complete_with_image(
            prompt=_USER_PROMPT,
            image_path=image_path,
            model=model,
            json_mode=True,
            temperature=1.0,
        )
    except Exception:
        return None

    data = parse_json_safe(raw) or {}
    candidate = data.get("phone")
    validated = _validate_phone(candidate)
    if not validated:
        return None

    llm_confidence = float(data.get("confidence") or 0.0)
    # Cap system confidence so the record always enters human review.
    system_confidence = min(MAX_SYSTEM_CONFIDENCE, llm_confidence)
    # If OCR confidence was already degraded, further discount the visual recovery.
    if ocr_confidence < 1.0:
        system_confidence = round(system_confidence * ocr_confidence, 2)

    return RecoveryResult(
        phone=validated,
        confidence=system_confidence,
        reasoning=data.get("reasoning"),
        source="vision_full_page",
    )
