"""Cloud read path and JD-match placeholder math (pure functions, no RDS/LLM)."""

from __future__ import annotations

import unittest

from reloop.domain.jd_match import (
    FACTOR_WEIGHTS,
    NEUTRAL_FACTOR,
    _keyword_match,
    _keyword_prefilter,
    placeholder_factors,
    score_candidate,
    weighted_product,
)
from reloop.sinks.rds.client import public_candidate_row


class PublicCandidateRowTest(unittest.TestCase):
    def test_shapes_cloud_row_for_frontend(self):
        row = {
            "id": 42,
            "fingerprint": "fp",
            "name": "张三",
            "phone": "13812345678",
            "email": "",
            "current_company": "某公司",
            "current_role": "HRBP",
            "location": "上海",
            "undergraduate_school": "复旦",
            "expected_salary": "30k",
            "opportunity_intent": "看机会",
            "platform": "boss",
            "source_url": "https://example.com",
            "review_status": "pending",
            "quality_score": 0.75,
            "missing_fields": '["salary_level"]',
            "experiences_json": '[{"company": "A", "role": "B", "period": "2020-2023", "highlights": ["x"]}]',
            "keywords_json": '["招聘", "OD"]',
            "raw_text": "完整简历正文",
            "collected_at": None,
            "updated_at": None,
        }
        item = public_candidate_row(row)
        self.assertEqual(item["id"], 42)
        self.assertEqual(item["quality_score"], 0.75)
        self.assertEqual(item["missing_fields"], ["salary_level"])
        self.assertEqual(item["experiences"], [{"company": "A", "role": "B", "period": "2020-2023", "highlights": ["x"]}])
        self.assertEqual(item["keywords"], ["招聘", "OD"])
        self.assertIsNone(item["score"])
        self.assertIsNone(item["jd_score"])

    def test_tolerates_null_and_malformed_json(self):
        item = public_candidate_row({"id": 1, "name": "x", "experiences_json": "{bad json", "quality_score": None})
        self.assertEqual(item["experiences"], [])
        self.assertEqual(item["keywords"], [])
        self.assertIsNone(item["quality_score"])
        self.assertEqual(item["raw_text"], "")


class WeightedProductTest(unittest.TestCase):
    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(FACTOR_WEIGHTS.values()), 1.0)

    def test_all_placeholders_yield_neutral_score(self):
        self.assertAlmostEqual(weighted_product(placeholder_factors()), NEUTRAL_FACTOR)

    def test_match_only_uses_placeholder_for_rest(self):
        factors = placeholder_factors()
        factors["match"] = 1.0
        expected = (1.0 ** 0.4) * (NEUTRAL_FACTOR ** 0.6)
        self.assertAlmostEqual(weighted_product(factors), expected)

    def test_zero_match_kills_score(self):
        factors = placeholder_factors()
        factors["match"] = 0.0
        self.assertEqual(weighted_product(factors), 0.0)


class KeywordPrefilterTest(unittest.TestCase):
    def test_prefers_keyword_overlap(self):
        candidates = [
            {"id": 1, "raw_text": "完全无关的厨师简历"},
            {"id": 2, "raw_text": "资深 HRBP 人力资源业务伙伴 招聘 组织发展"},
            {"id": 3, "raw_text": "销售总监"},
        ]
        pool = _keyword_prefilter("HRBP 人力资源 招聘", candidates, keep=2)
        self.assertEqual(pool[0]["id"], 2)
        self.assertEqual(len(pool), 2)


class KeywordFallbackTest(unittest.TestCase):
    def test_keyword_match_scores_overlap(self):
        result = _keyword_match("HRBP 人力资源 招聘", {"raw_text": "资深 HRBP，负责人力资源与招聘工作"})
        self.assertIsNotNone(result)
        match, reason = result
        self.assertGreater(match, 0)
        self.assertIn("命中关键词", reason)

    def test_keyword_match_none_without_overlap(self):
        self.assertIsNone(_keyword_match("HRBP 人力资源", {"raw_text": "厨师，擅长川菜"}))

    def test_score_candidate_falls_back_without_llm(self):
        # 测试环境无 TTC_LLM_API_KEY → 必须走 keyword_fallback 且如实标记
        result = score_candidate("HRBP 人力资源 招聘", {"id": 7, "name": "测试", "raw_text": "HRBP 人力资源 招聘 10 年"})
        self.assertIsNotNone(result)
        self.assertEqual(result.mode, "keyword_fallback")
        self.assertGreater(result.score, 0)


if __name__ == "__main__":
    unittest.main()
