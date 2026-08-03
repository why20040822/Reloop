import unittest

from scripts.oneoff.llm_jd_match_report import (
    JD_JINGHUA,
    JD_RUISHENG,
    assess_data_quality,
    hard_filter,
    has_big_tech_history,
    validate_llm_result,
)


def candidate(**overrides):
    value = {
        "person_leads_id": "p-1",
        "source_type": "ttc_api",
        "name": "测试候选人",
        "location": "广东,深圳",
        "age": 30,
        "years_experience": 6,
        "education": "某大学·本科",
        "degree": "本科",
        "current_company": "腾讯",
        "current_role": "AI产品经理",
        "work_information": [{"company": "腾讯", "job_title": "AI产品经理"}],
        "raw_text": "主导企业级AI Agent产品从0到1落地，设计RAG和工具调用。",
        "raw_text_source": "full_resume",
    }
    value.update(overrides)
    return value


class DataQualityTests(unittest.TestCase):
    def test_generated_data_is_quarantined(self):
        result = assess_data_quality(candidate(source="generated"))
        self.assertEqual(result["grade"], "QUARANTINED")

    def test_search_summary_is_review_only(self):
        result = assess_data_quality(candidate(raw_text_source="search_summary"))
        self.assertEqual(result["grade"], "C")
        self.assertIn("project_evidence", result["missing_fields"])

    def test_enriched_profile_is_grade_b(self):
        result = assess_data_quality(candidate(raw_text_source="search_summary", profile_enriched=True))
        self.assertEqual(result["grade"], "B")


class HardFilterTests(unittest.TestCase):
    def test_unknown_location_goes_to_review(self):
        status, _ = hard_filter(candidate(location="未知"), JD_RUISHENG)
        self.assertEqual(status, "review")

    def test_wrong_location_fails(self):
        status, _ = hard_filter(candidate(location="北京"), JD_RUISHENG)
        self.assertEqual(status, "fail")

    def test_jinghua_requires_big_tech_history(self):
        no_big_tech = candidate(
            location="北京",
            current_company="某创业公司",
            work_information=[{"company": "某创业公司"}],
        )
        self.assertFalse(has_big_tech_history(no_big_tech))
        status, reason = hard_filter(no_big_tech, JD_JINGHUA)
        self.assertEqual(status, "fail")
        self.assertIn("大厂", reason)


class SemanticValidationTests(unittest.TestCase):
    def test_unverified_quote_is_removed_and_score_is_recomputed(self):
        c = candidate()
        c["data_quality"] = {"grade": "A"}
        raw = {
            "hard_pass": True,
            "overall": 100,
            "recommendation": "强推",
            "dimensions": {name: 80 for name in JD_RUISHENG.scoring_dimensions},
            "must_have": {item: "met" for item in JD_RUISHENG.must_have},
            "evidence_quotes": ["不存在的经历"],
            "risks": [],
            "evidence": "匹配",
        }
        result = validate_llm_result(raw, JD_RUISHENG, c)
        self.assertEqual(result["overall"], 80)
        self.assertFalse(result["evidence_verified"])
        self.assertNotEqual(result["recommendation"], "强推")

    def test_grade_c_cannot_be_strong_recommendation(self):
        c = candidate()
        c["data_quality"] = {"grade": "C"}
        quote = "主导企业级AI Agent产品从0到1落地"
        raw = {
            "hard_pass": True,
            "dimensions": {name: 100 for name in JD_RUISHENG.scoring_dimensions},
            "must_have": {item: "met" for item in JD_RUISHENG.must_have},
            "evidence_quotes": [quote],
            "risks": [],
            "evidence": "匹配",
        }
        result = validate_llm_result(raw, JD_RUISHENG, c)
        self.assertEqual(result["overall"], 79)
        self.assertEqual(result["recommendation"], "建议沟通")


if __name__ == "__main__":
    unittest.main()
