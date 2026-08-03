import unittest

from scripts.ops.full_pipeline_report import (
    evaluate,
    infer_age,
    is_academic,
    recent_company_score,
)


def candidate(**overrides):
    value = {
        "person_leads_id": "p1",
        "source_type": "ttc_api",
        "source": "ttc_api",
        "name": "测试候选人",
        "age": 30,
        "years_experience": 6,
        "education": "某大学·本科",
        "degree": "本科",
        "location": "广东,深圳",
        "current_company": "某创业科技公司",
        "current_role": "AI产品经理",
        "skills": ["LLM", "RAG"],
        "raw_text": "B端AI产品经理，负责企业级AI Agent与RAG产品。",
        "work_information": [
            {"company": "某创业科技公司", "job_title": "AI产品经理"},
            {"company": "腾讯", "job_title": "产品经理"},
        ],
    }
    value.update(overrides)
    return value


class FullPipelineRuleTests(unittest.TestCase):
    def test_cloud_actual_age_takes_priority(self):
        value = candidate(age=29, years_experience=12)
        self.assertEqual(infer_age(value), 29)
        self.assertIn("实际字段", value["age_source"])

    def test_current_academic_employer_is_detected(self):
        self.assertTrue(is_academic("某大学人工智能研究院"))
        self.assertFalse(is_academic("腾讯科技"))

    def test_recent_big_tech_history_gets_weighted(self):
        score, evidence = recent_company_score(candidate())
        self.assertEqual(score, 100)
        self.assertIn("腾讯", evidence)

    def test_generated_fixture_never_scores(self):
        self.assertIsNone(evaluate(candidate(source="generated")))

    def test_candidate_gets_two_job_rule_scores(self):
        result = evaluate(candidate())
        self.assertIsNotNone(result)
        self.assertIn("ruisheng_rule_score", result)
        self.assertIn("jinghua_rule_score", result)


if __name__ == "__main__":
    unittest.main()
