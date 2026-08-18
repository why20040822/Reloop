"""Unit tests for mosaic phone number recovery."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from models import CandidateRecord
from parsers.mosaic_phone_recovery import RecoveryResult, recover_phone
from parsers.unified_parser import _build_confidences, _post_process_record


class TestMosaicPhoneRecovery(unittest.TestCase):
    def test_recovery_skipped_when_disabled(self):
        """When the feature switch is off, recover_phone returns None."""
        with patch.dict(os.environ, {"ENABLE_MOSAIC_PHONE_RECOVERY": "false"}, clear=True):
            result = recover_phone(Path("/fake/resume.pdf"), "paddleocr")
        self.assertIsNone(result)

    @patch("parsers.mosaic_phone_recovery.complete_with_image")
    def test_recovery_returns_valid_phone(self, mock_complete):
        mock_complete.return_value = json.dumps({
            "phone": "13800138000",
            "confidence": 0.85,
            "reasoning": "digits visible through light mosaic",
        })
        with patch.dict(os.environ, {"ENABLE_MOSAIC_PHONE_RECOVERY": "true"}, clear=True):
            result = recover_phone(Path("/fake/resume.png"), "paddleocr")

        self.assertIsNotNone(result)
        self.assertEqual(result.phone, "13800138000")
        self.assertEqual(result.source, "vision_full_page")
        # System confidence must be capped below human-review threshold.
        self.assertLessEqual(result.confidence, 0.4)
        self.assertGreater(result.confidence, 0.0)

    @patch("parsers.mosaic_phone_recovery.complete_with_image")
    def test_recovery_rejects_invalid_phone(self, mock_complete):
        mock_complete.return_value = json.dumps({
            "phone": "123456789",
            "confidence": 0.9,
            "reasoning": "looks like a phone",
        })
        with patch.dict(os.environ, {"ENABLE_MOSAIC_PHONE_RECOVERY": "true"}, clear=True):
            result = recover_phone(Path("/fake/resume.png"), "paddleocr")
        self.assertIsNone(result)

    @patch("parsers.mosaic_phone_recovery.complete_with_image")
    def test_recovery_rejects_uncertain_llm(self, mock_complete):
        mock_complete.return_value = json.dumps({
            "phone": None,
            "confidence": 0.1,
            "reasoning": "too blurred",
        })
        with patch.dict(os.environ, {"ENABLE_MOSAIC_PHONE_RECOVERY": "true"}, clear=True):
            result = recover_phone(Path("/fake/resume.png"), "paddleocr")
        self.assertIsNone(result)

    @patch("parsers.mosaic_phone_recovery.complete_with_image")
    def test_recovery_discounts_low_ocr_confidence(self, mock_complete):
        mock_complete.return_value = json.dumps({
            "phone": "13800138000",
            "confidence": 0.9,
            "reasoning": "digits visible",
        })
        with patch.dict(os.environ, {"ENABLE_MOSAIC_PHONE_RECOVERY": "true"}, clear=True):
            result = recover_phone(Path("/fake/resume.png"), "paddleocr", ocr_confidence=0.5)
        self.assertIsNotNone(result)
        # 0.4 cap * 0.5 OCR discount.
        self.assertLessEqual(result.confidence, 0.2)


class TestUnifiedParserConfidenceIntegration(unittest.TestCase):
    def test_build_confidences_uses_recovery_for_phone(self):
        record = CandidateRecord(
            name="张三",
            phone="13800138000",
            email="zs@example.com",
        )
        recovery = RecoveryResult(
            phone="13800138000",
            confidence=0.35,
            reasoning="light mosaic",
            source="vision_full_page",
        )
        confidences = _build_confidences(record, 1.0, 1.0, 0.8, recovery)
        phone_conf = next(fc for fc in confidences if fc.field == "phone")
        self.assertEqual(phone_conf.confidence, 0.35)
        self.assertIn("mosaic_recovery", phone_conf.note or "")

    def test_post_process_record_keeps_recovered_phone_for_review(self):
        record = CandidateRecord(
            name="张三",
            phone="13800138000",
            review_status="needs_review",
        )
        recovery = RecoveryResult(
            phone="13800138000",
            confidence=0.35,
            reasoning="light mosaic",
            source="vision_full_page",
        )
        processed = _post_process_record(record, 1.0, 1.0, 0.8, recovery)
        self.assertEqual(processed.phone, "13800138000")
        phone_conf = next(fc for fc in processed.field_confidences if fc.field == "phone")
        self.assertEqual(phone_conf.confidence, 0.35)


if __name__ == "__main__":
    unittest.main()
