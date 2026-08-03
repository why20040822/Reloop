import unittest

from reloop.config import REPOSITORY_ROOT
from reloop.domain.models import CandidateRecord
from reloop.parsing.unified_parser import (
    _extract_experiences,
    _extract_name,
    parse_resume_file,
    parse_resume_text,
)
from reloop.sinks.feishu.feishu_base import FeishuBaseAdapter

RESUME_DIR = REPOSITORY_ROOT / "简历数据"
SAMPLE_PDF = RESUME_DIR / "004359d2c2b4_【新消费品牌策略_北京_50-55K】陈女士_7年.pdf"


class CandidateRecordTests(unittest.TestCase):
    def test_phone_normalization(self):
        r = CandidateRecord(phone="138-1234-5678")
        self.assertEqual(r.phone, "13812345678")

    def test_fingerprint_prefers_sha256(self):
        r = CandidateRecord(attachment_sha256="abc", phone="13812345678")
        self.assertTrue(r.fingerprint_input().startswith("sha256|"))

    def test_fingerprint_fallback_to_phone(self):
        r = CandidateRecord(phone="13812345678")
        self.assertEqual(r.fingerprint_input(), "phone|13812345678")


class NameExtractionTests(unittest.TestCase):
    def test_name_from_prefixed_filename(self):
        self.assertEqual(
            _extract_name("", "【新消费品牌策略_北京_50-55K】李潭清_8年.pdf"),
            "李潭清",
        )

    def test_name_from_top_lines(self):
        text = "\n".join(["在线简历", "张三丰", "北京", "8年"])
        self.assertEqual(_extract_name(text, ""), "张三丰")

    def test_name_before_resume_keyword_in_filename(self):
        self.assertEqual(_extract_name("", "张佩柔_个人简历.pdf"), "张佩柔")
        self.assertEqual(_extract_name("", "李潭清-简历.docx"), "李潭清")

    def test_name_as_last_segment_in_filename(self):
        self.assertEqual(_extract_name("", "any_张佩柔.pdf"), "张佩柔")
        self.assertEqual(_extract_name("", "资深后端-刘金杰.pdf"), "刘金杰")

    def test_name_last_segment_skips_stop_words(self):
        self.assertIsNone(_extract_name("", "岗位_北京.pdf"))


class JobTypeInferenceTests(unittest.TestCase):
    def test_infer_algorithm(self):
        r = CandidateRecord(tech_stack=["Python", "PyTorch"], current_title="算法工程师")
        self.assertEqual(FeishuBaseAdapter._infer_job_type(r, {"options": ["算法", "后端", "产品"], "fallback": "无匹配标签"}), "算法")

    def test_infer_product(self):
        r = CandidateRecord(tech_stack=[], current_title="AI产品经理")
        self.assertEqual(FeishuBaseAdapter._infer_job_type(r, {"options": ["产品", "后端"], "fallback": "无匹配标签"}), "产品")


class TextParserTests(unittest.TestCase):
    def test_parse_text_extracts_basic_fields(self):
        text = """
王小明
13812345678
xiaoming@example.com
北京大学 本科 2016年毕业
阿里巴巴 高级后端工程师 2020.03 - 至今
负责微服务架构设计，使用Java、Spring、MySQL、Redis。
期望薪资：40-60K
"""
        record = parse_resume_text(text, title="王小明.pdf", source_url="https://zhipin.com/1")
        self.assertEqual(record.name, "王小明")
        self.assertEqual(record.phone, "13812345678")
        self.assertEqual(record.email, "xiaoming@example.com")
        self.assertEqual(record.school, "北京大学")
        self.assertEqual(record.current_company, "阿里巴巴")
        self.assertEqual(record.current_title, "高级后端工程师")
        self.assertEqual(record.expected_salary, "40-60K")
        self.assertIn("Java", record.tech_stack)


class ExperienceExtractionTests(unittest.TestCase):
    def test_company_period_role_order(self):
        text = """工作经历
惠达卫浴股份有限公司
2025年10月 - 2026年04月
战略管理高级专员
新奥阳光易采科技有限公司
2024年10月 - 2025年04月
战略分析师
"""
        experiences, _ = _extract_experiences(text)
        self.assertEqual(len(experiences), 2)
        self.assertEqual(experiences[0].company, "惠达卫浴股份有限公司")
        self.assertEqual(experiences[0].role, "战略管理高级专员")
        self.assertEqual(experiences[0].period, "2025年10月 - 2026年04月")
        self.assertEqual(experiences[1].company, "新奥阳光易采科技有限公司")
        self.assertEqual(experiences[1].role, "战略分析师")

    def test_company_role_period_order(self):
        text = """工作经历
阿里巴巴
产品经理
2020.03 - 至今
腾讯
高级产品经理
2018.05 - 2020.02
"""
        experiences, _ = _extract_experiences(text)
        self.assertEqual(len(experiences), 2)
        self.assertEqual(experiences[0].company, "阿里巴巴")
        self.assertEqual(experiences[0].role, "产品经理")
        self.assertEqual(experiences[1].company, "腾讯")
        self.assertEqual(experiences[1].role, "高级产品经理")

    def test_cross_line_company_name(self):
        text = """工作经历
北京字节跳动
科技有限公司
2023年01月 - 至今
产品经理
"""
        experiences, _ = _extract_experiences(text)
        self.assertEqual(len(experiences), 1)
        self.assertEqual(experiences[0].company, "北京字节跳动科技有限公司")
        self.assertEqual(experiences[0].role, "产品经理")

    def test_pipes_separator_single_line(self):
        text = """工作经历
字节跳动 | 后端开发工程师 | 2020-至今
"""
        experiences, _ = _extract_experiences(text)
        self.assertEqual(len(experiences), 1)
        self.assertEqual(experiences[0].company, "字节跳动")
        self.assertEqual(experiences[0].role, "后端开发工程师")


class RealPdfRegressionTests(unittest.TestCase):
    def test_real_pdf_current_company_and_title(self):
        if not SAMPLE_PDF.is_file():
            self.skipTest(f"Sample PDF not found: {SAMPLE_PDF}")
        record = parse_resume_file(SAMPLE_PDF)
        self.assertEqual(record.name, "陈女士")
        self.assertEqual(record.current_company, "惠达卫浴股份有限公司")
        self.assertEqual(record.current_title, "战略管理高级专员")
        self.assertGreaterEqual(len(record.work_experiences), 3)
        self.assertEqual(record.phone, "13473532431")
        self.assertGreaterEqual(record.parse_confidence or 0, 0.5)


if __name__ == "__main__":
    unittest.main()
