import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import MagicMock, patch

import fitz

from reloop.api import legacy as app

# Starlette <0.40 emits a false-positive warning when used with httpx>=0.28.
warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated",
    category=UserWarning,
)

SAMPLE = """
张某 31岁 北京 8年工作经验
复旦大学 本科
罗兰贝格 咨询顾问，负责消费行业品牌定位项目，向客户CEO汇报。
百事 战略经理，主导新品上市、产品创新、GTM和渠道策略。
"""


class ParserTests(unittest.TestCase):
    def test_qiming_profile(self):
        result = app.parse_candidate(app.CapturePayload(title="张某-在线简历", heading="张某", text=SAMPLE, url="https://www.zhipin.com/candidate/1"))
        self.assertEqual(result["name"], "张某")
        self.assertEqual(result["platform"], "BOSS直聘")
        self.assertEqual(result["undergraduate_tier"], "985")
        self.assertGreaterEqual(result["score"], 85)
        self.assertTrue(result["consulting_evidence"])
        self.assertTrue(result["inhouse_evidence"])

    def test_clean_text_deduplicates_lines(self):
        self.assertEqual(app.clean_text(" A  \nA\n\n B "), "A\nB")

    def test_name_from_prefixed_filename(self):
        text = "\n能力简介\n工作经历\nWenda Yin 殷闻达\n北京\n"
        self.assertEqual(app.infer_name("【消费品牌策略顾问】_北京 25K-殷闻达 5年.pdf", "", text), "殷闻达")

    def test_chinese_name_precedes_english_filename(self):
        self.assertEqual(app.infer_name("Guofu(Rachel) RAO_CV.pdf", "", "饶帼馥\n联系电话\n"), "饶帼馥")

    def test_job_prefixed_filename_beats_page_button(self):
        title = "【新消费品牌策略_北京 50-55K】李潭清 8年.pdf"
        text = "后一个月\n设置\n工作经历\n"
        self.assertEqual(app.infer_name(title, "", text), "李潭清")

    def test_boss_native_profile(self):
        text = """詹先生
31岁
本科
9年
在职-考虑机会
北京
战略咨询
30-50K
工作经历
美团
业务策略
2025.11 - 至今
负责业务战略规划、产品创新和渠道策略，向管理层汇报。
帕特侬战略咨询
高级战略顾问
2021.11 - 2022.05
参与消费行业战略咨询项目。
教育经历
中南财经政法大学
会计学
本科
2013 - 2017
211院校"""
        result = app.parse_candidate(app.CapturePayload(
            title="BOSS直聘", heading="詹先生", text=text,
            url="https://www.zhipin.com/web/geek/detail/example"
        ))
        self.assertEqual(result["name"], "詹先生")
        self.assertEqual(result["explicit_age"], 31)
        self.assertEqual(result["experience_years"], 9)
        self.assertEqual(result["current_company"], "美团")
        self.assertEqual(result["current_role"], "业务策略")
        self.assertEqual(result["expected_salary"], "30-50K")
        self.assertEqual(result["undergraduate_tier"], "211")
        self.assertEqual(len(result["experiences"]), 2)
        self.assertGreaterEqual(result["score"], 85)

    def test_age_over_33_is_zero(self):
        text = SAMPLE.replace("31岁", "34岁")
        result = app.parse_candidate(app.CapturePayload(
            title="候选人", heading="张某", text=text
        ))
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["hard_filter_reason"], "年龄超过33岁")
        self.assertEqual(result["recommendation"], "不符合年龄硬性要求")

    def test_phone_and_email_extracted(self):
        text = "王小明 13812345678 邮箱 wangxm@example.com 8年经验"
        result = app.parse_candidate(app.CapturePayload(title="简历", heading="王小明", text=text, url=""))
        self.assertEqual(result["phone"], "13812345678")
        self.assertEqual(result["email"], "wangxm@example.com")

    def test_manual_text_extracts_work_experiences(self):
        text = """王小明
13812345678
wangxm@example.com

工作经历
字节跳动 产品经理 2020.03 - 至今
负责抖音电商产品规划

阿里巴巴 产品专员 2018.07 - 2020.02
负责淘宝活动运营

教育经历
北京大学 本科 2016.09 - 2020.07
"""
        result = app.parse_candidate(app.CapturePayload(title="测试简历", heading="王小明", text=text, url=""))
        self.assertEqual(result["name"], "王小明")
        self.assertEqual(result["phone"], "13812345678")
        self.assertEqual(result["current_company"], "字节跳动")
        self.assertEqual(result["current_role"], "产品经理")
        self.assertEqual(len(result["experiences"]), 2)
        self.assertEqual(result["experiences"][0]["company"], "字节跳动")
        self.assertEqual(result["experiences"][1]["company"], "阿里巴巴")

    def test_pdf_no_ocr_when_text_sufficient(self):
        page = MagicMock()
        page.get_text.return_value = "王小明 13812345678\n字节跳动 产品经理 2020.03 - 至今\n"
        doc = MagicMock()
        doc.__iter__.return_value = [page]

        with patch("reloop.api.legacy.fitz.open", return_value=doc):
            with patch("reloop.api.legacy.ocr_pdf") as mock_ocr:
                text = app._extract_upload_text(b"fake pdf", ".pdf", Path("/tmp/test.pdf"))

        self.assertIn("王小明", text)
        mock_ocr.assert_not_called()

    def test_pdf_ocr_fallback_when_text_too_short(self):
        page = MagicMock()
        page.get_text.return_value = "   "
        doc = MagicMock()
        doc.__iter__.return_value = [page]

        ocr_result = MagicMock()
        ocr_result.text = "王小明 13812345678 字节跳动 产品经理"

        with patch("reloop.api.legacy.fitz.open", return_value=doc):
            with patch("reloop.api.legacy.ocr_pdf", return_value=ocr_result) as mock_ocr:
                text = app._extract_upload_text(b"fake pdf", ".pdf", Path("/tmp/test.pdf"))

        self.assertEqual(text, "王小明 13812345678 字节跳动 产品经理")
        mock_ocr.assert_called_once()

    def test_docx_text_extraction(self):
        with patch("reloop.api.legacy.gmail_sync.extract_word_text", return_value="王小明 13812345678") as mock_extract:
            text = app._extract_upload_text(b"fake docx", ".docx", Path("/tmp/test.docx"))
        self.assertEqual(text, "王小明 13812345678")
        mock_extract.assert_called_once_with(Path("/tmp/test.docx"))

    def test_quality_stats_structure(self):
        stats = app.quality_stats()
        self.assertTrue(stats["ok"])
        self.assertIn("field_completeness", stats)
        self.assertIn("low_confidence_ratio", stats)
        self.assertIn("pending_review_count", stats)
        self.assertIn("ingestion_success_rate", stats)

    def test_manual_text_extracts_education(self):
        text = """王小明
13812345678

教育经历
北京大学 本科 2016年毕业

工作经历
字节跳动 产品经理 2020.03 - 至今
"""
        result = app.parse_candidate(app.CapturePayload(title="测试简历", heading="王小明", text=text, url=""))
        self.assertEqual(result["undergraduate_school"], "北京大学")
        self.assertEqual(result["undergraduate_tier"], "985")
        self.assertEqual(result["education"]["school"], "北京大学")
        self.assertEqual(result["education"]["degree"], "本科")

    def test_manual_text_extracts_non_tier_school(self):
        text = """王小明
13812345678

教育经历
宁波大学 本科 2016年毕业
"""
        result = app.parse_candidate(app.CapturePayload(title="测试简历", heading="王小明", text=text, url=""))
        self.assertEqual(result["education"]["school"], "宁波大学")
        self.assertEqual(result["education"]["degree"], "本科")

    def test_extract_upload_text_with_real_pdf(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = Path(f.name)
        doc = fitz.open()
        page = doc.new_page()
        # Use ASCII text to avoid font/encoding issues in the test PDF.
        page.insert_text((100, 100), "Wang Xiaoming 13812345678\nByteDance Product Manager")
        doc.save(str(pdf_path))
        doc.close()
        try:
            text = app._extract_upload_text(pdf_path.read_bytes(), ".pdf", pdf_path)
            self.assertIn("Wang Xiaoming", text)
            self.assertIn("ByteDance", text)
        finally:
            pdf_path.unlink()


if __name__ == "__main__":
    unittest.main()
