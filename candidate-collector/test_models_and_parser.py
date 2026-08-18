import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from models import CandidateRecord
from adapters.feishu_base import FeishuBaseAdapter
from parsers.unified_parser import (
    _extract_education,
    _extract_experiences,
    _extract_name,
    _infer_employment_status,
    parse_resume_file,
    parse_resume_text,
)


RESUME_DIR = Path(__file__).resolve().parent.parent / "简历数据"
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

    def test_phone_too_short_returns_none(self):
        # 少于 7 位的明显非法号码置空，走人工复核
        self.assertIsNone(CandidateRecord(phone="123").phone)
        self.assertIsNone(CandidateRecord(phone="123456").phone)
        self.assertIsNone(CandidateRecord(phone="12-34").phone)

    def test_phone_seven_digits_kept(self):
        self.assertEqual(CandidateRecord(phone="1234567").phone, "1234567")

    def test_fingerprint_empty_identity_not_fixed_string(self):
        # name/company/title 全空时不得塌缩成固定指纹 name_company_title|||
        r = CandidateRecord(raw_text="简历A内容")
        self.assertNotEqual(r.fingerprint_input(), "name_company_title|||")
        self.assertTrue(r.fingerprint_input().startswith("raw_hash|"))

    def test_fingerprint_empty_identity_falls_back_to_unique_info(self):
        # 依次回退到 raw_text / source_url / captured_at，保证可区分
        a = CandidateRecord(raw_text="简历A内容")
        b = CandidateRecord(raw_text="简历B内容")
        self.assertNotEqual(a.fingerprint_input(), b.fingerprint_input())
        c = CandidateRecord(source_url="https://zhipin.com/a")
        d = CandidateRecord(source_url="https://zhipin.com/b")
        self.assertNotEqual(c.fingerprint_input(), d.fingerprint_input())
        # 完全无信息时基于 captured_at 仍保证唯一
        e = CandidateRecord(captured_at="2026-01-01T00:00:00+00:00")
        f = CandidateRecord(captured_at="2026-01-02T00:00:00+00:00")
        self.assertNotEqual(e.fingerprint_input(), f.fingerprint_input())

    def test_to_db_dict_json_fields_are_strings(self):
        # SQLite 写入链路要求 JSON 字符串而非对象
        r = CandidateRecord(skills=["Java"], raw_text="x")
        d = r.to_db_dict()
        for key in ("experiences_json", "education_json", "keywords_json"):
            self.assertIsInstance(d[key], str)
            json.loads(d[key])  # 必须是合法 JSON
        self.assertEqual(json.loads(d["keywords_json"]), ["Java"])


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

    def test_resume_heading_not_a_name(self):
        # “求职简历”等标题行不得被识别为姓名
        text = "\n".join(["求职简历", "张三丰", "13812345678"])
        self.assertEqual(_extract_name(text, ""), "张三丰")

    def test_plain_body_line_requires_digit(self):
        # 无数字/性别信息的普通短行不得被当成姓名（历史 \d{0,2} 误识别）
        text = "\n".join(["负责项目管理工作", "团队协作能力强", "张三丰 男 28岁"])
        self.assertEqual(_extract_name(text, ""), "张三丰")


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

    def test_random_adjacent_lines_not_experience(self):
        # 无任职时间段的相邻短行不得被当成公司+职位
        text = "张三\n13812345678\n今天天气不错\n明天继续加油"
        experiences, _ = _extract_experiences(text)
        self.assertEqual(experiences, [])
        record = parse_resume_text(text)
        self.assertIsNone(record.current_company)
        self.assertIsNone(record.current_title)

    def test_company_role_without_period_rejected(self):
        # 公司+职位相邻但无任何任职时间段，不得产出工作经历
        text = "张三\n13812345678\n字节跳动\n产品经理\n负责产品设计工作"
        experiences, _ = _extract_experiences(text)
        self.assertEqual(experiences, [])

    def test_labeled_current_company_not_overwritten_by_experience(self):
        # 显式标注的现任公司置信度更高，不被第一条工作经历覆盖
        text = "张三\n13812345678\n现任公司：腾讯\n阿里巴巴 高级后端工程师 2020.03 - 至今"
        record = parse_resume_text(text)
        self.assertEqual(record.current_company, "腾讯")
        self.assertEqual(record.current_title, "高级后端工程师")


class EmploymentStatusTests(unittest.TestCase):
    def test_specific_status_wins_over_generic(self):
        self.assertEqual(_infer_employment_status("目前在职-考虑机会，欢迎联系"), "在职-考虑机会")
        self.assertEqual(_infer_employment_status("在职-暂不考虑新机会"), "在职-暂不考虑")
        self.assertEqual(_infer_employment_status("离职-随时到岗"), "离职-随时到岗")

    def test_generic_status_still_matches(self):
        self.assertEqual(_infer_employment_status("目前在职，看看情况"), "在职")


class ExpectedLocationTests(unittest.TestCase):
    def test_expected_location_requires_intent_context(self):
        # 没有“期望/意向”上下文时不得复制 current_location
        record = parse_resume_text("李四\n13812345678\n现居北京\n3年工作经验")
        self.assertEqual(record.current_location, "北京")
        self.assertIsNone(record.expected_location)

    def test_expected_location_from_intent_line(self):
        record = parse_resume_text("李四\n13812345678\n现居北京\n期望城市：上海")
        self.assertEqual(record.current_location, "北京")
        self.assertEqual(record.expected_location, "上海")


class GraduationYearTests(unittest.TestCase):
    def test_grad_year_requires_marker(self):
        # 教育行之外的任意 20xx 年份不得当成本科毕业年份
        edu = _extract_education("北京大学 本科\n公司成立于2020年，员工上千人")
        self.assertEqual(edu.school, "北京大学")
        self.assertIsNone(edu.graduation_year)

    def test_grad_year_with_marker(self):
        edu = _extract_education("北京大学 本科 2016年毕业")
        self.assertEqual(edu.graduation_year, 2016)
        edu = _extract_education("清华大学 硕士 2019届")
        self.assertEqual(edu.graduation_year, 2019)

    def test_grad_year_from_education_period_end(self):
        # 含学历词的行内教育时间段取结束年
        edu = _extract_education("2012-2016 北京大学 本科")
        self.assertEqual(edu.graduation_year, 2016)

    def test_grad_year_marker_beats_bare_years(self):
        edu = _extract_education("2012-2016 北京大学 本科 2016届")
        self.assertEqual(edu.graduation_year, 2016)


class SkillBoundaryTests(unittest.TestCase):
    def test_java_after_chinese_prefix(self):
        record = parse_resume_text("王五\n13812345678\n熟练使用Java和Spring开发")
        self.assertIn("Java", record.skills)

    def test_java_not_matched_inside_javascript(self):
        record = parse_resume_text("王五\n13812345678\n精通JavaScript和Vue")
        self.assertIn("JavaScript", record.skills)
        self.assertNotIn("Java", record.skills)

    def test_java_not_matched_before_digit(self):
        record = parse_resume_text("王五\n13812345678\n熟悉Java8特性")
        self.assertNotIn("Java", record.skills)


class EmptyFileReviewTests(unittest.TestCase):
    def test_scanned_pdf_marked_needs_review(self):
        # 提取不到文字的扫描型 PDF 必须进入人工复核并注明原因
        import fitz

        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "blank.pdf"
            doc = fitz.open()
            doc.new_page()
            doc.save(pdf)
            doc.close()
            with mock.patch("parsers.unified_parser._extract_image_text", return_value=("", 0.0, "none")):
                record = parse_resume_file(pdf)
        self.assertEqual(record.review_status, "needs_review")
        self.assertIn("empty_pdf", record.notes or "")

    def test_image_marked_needs_review_with_mime(self):
        # 图片附件不得以正常已解析状态入库，且需带正确 mime type
        with tempfile.TemporaryDirectory() as tmp:
            img = Path(tmp) / "resume.png"
            img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
            with mock.patch("parsers.unified_parser._extract_image_text", return_value=("", 0.0, "none")), \
                 mock.patch("parsers.mosaic_phone_recovery.recover_phone", return_value=None):
                record = parse_resume_file(img)
        self.assertEqual(record.review_status, "needs_review")
        self.assertEqual(record.attachment_mime_type, "image/png")
        self.assertIn("empty_ocr", record.notes or "")


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
