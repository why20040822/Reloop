"""resume_scorer 单测：覆盖 ≥8.5 / 6-6.9 / <6 分档 + 封顶规则。"""

from __future__ import annotations

import unittest

import resume_scorer
from resume_scorer import build_dimensions, score_resume


JD_FINANCE = """财务负责人（智能硬件出海方向）
岗位职责：
1. 负责公司供应链业财一体化建设，打通采购、库存、成本核算与财务核算；
2. 主导全面预算与经营分析体系，输出滚动预测与损益分析；
3. 支持海外业务财务，处理跨境结算、外汇与 IFRS 报表；
4. 作为财务一号位，搭建并管理财务团队，直接向 CEO 汇报。
任职要求：
1. 8 年以上财务经验，3 年以上硬件/消费电子行业经验；
2. 熟悉供应链业财、预算管理、海外财务；
3. CPA 优先。
"""

# 强简历：五个维度全部命中 → 期望 ≥8.5 重点推荐
RESUME_STRONG = """李四 13800001111
10年工作经验
某智能硬件公司 财务负责人
负责供应链业财一体化建设，打通采购、库存、成本核算与财务核算，实现业财融合
主导全面预算管理与经营分析，建立滚动预测机制，输出损益分析与 FP&A 报告
负责海外财务与跨境结算，处理外汇风险，按 IFRS 出具合并报表，英语可作为工作语言
搭建财务团队并管理 12 人，作为财务一号位直接向 CEO 汇报
任职于消费电子制造业，熟悉智能硬件工厂成本结构，推动库存周转提升 30%
持有 CPA 证书
教育经历
复旦大学 本科 会计学
"""

# 临界简历：部分维度有证据、海外/一号位弱 → 期望 6.0-6.9 临界
RESUME_BORDERLINE = """王五 13900002222
6年工作经验
某电子制造业公司 财务经理
负责供应链与采购成本核算，协助业财数据对账
参与年度预算编制、经营分析与财务分析，输出月度报表
带领 3 人小组，负责团队管理，参与搭建团队
教育经历
某财经院校 本科 财务管理
"""

# 弱简历：行政前台背景 → 期望 <6 不推荐
RESUME_WEAK = """赵六 13700003333
3年工作经验
某贸易公司 行政前台
负责前台接待、会议室预订与快递收发
负责办公用品采购与费用报销单据整理
协助人事部门安排面试
教育经历
某职业技术学院 大专 文秘
"""

# 光环简历：名校+名企光环，但完全缺核心维度（供应链业财）证据 → 触发封顶 ≤6.0
RESUME_HALO_NO_CORE = """孙七 13600004444
9年工作经验
麦肯锡 高级顾问 → 某消费电子制造业集团 财务总监
主导全面预算管理与经营分析体系建设，输出滚动预测与损益分析，FP&A 经验丰富
负责海外财务与跨境业务支持，处理外汇与 IFRS 报表，英语流利
搭建财务团队，团队管理 15 人
教育经历
清华大学 本科 经济学
"""


class TestDimensionInference(unittest.TestCase):
    def test_finance_template_used(self):
        dims, source = build_dimensions(JD_FINANCE)
        self.assertIn("财务负责人", source)
        names = [d.name for d in dims]
        self.assertEqual(names[0], "供应链业财")
        self.assertAlmostEqual(sum(d.weight for d in dims), 100.0, places=1)
        self.assertTrue(dims[0].core)

    def test_explicit_weight_lines(self):
        jd = "岗位说明\n供应链业财 40\n硬件行业 20\n预算经营 15\n海外财务 15\n一号位能力 10\n负责公司财务工作"
        dims, source = build_dimensions(jd)
        self.assertIn("显式权重", source)
        self.assertAlmostEqual(sum(d.weight for d in dims), 100.0, places=1)

    def test_explicit_weight_lines_inherit_theme_keywords(self):
        """JD 显式权重行的维度若命中主题库，应带上主题关键词（同义词可命中）。"""
        jd = "供应链业财 40\n硬件行业 20\n预算经营 15\n海外财务 15\n一号位能力 10"
        dims, _ = build_dimensions(jd)
        supply = next(d for d in dims if d.name == "供应链业财")
        self.assertIn("供应链", supply.keywords)
        resume = "8年供应链财务经验，管理40亿采购预算，推动成本下降12%。主导预算与经营分析体系搭建，覆盖海外子公司财务合规。"
        r = score_resume(resume, jd)
        supply_result = next(d for d in r["dimensions"] if d["name"] == "供应链业财")
        self.assertGreater(supply_result["score"], 0, r["report"])

    def test_user_weights_config(self):
        cfg = [
            {"name": "核心技能", "weight": 60, "core": True, "keywords": ["Python"]},
            {"name": "沟通", "weight": 40, "keywords": ["沟通"]},
        ]
        dims, source = build_dimensions("任何 JD", weights_config=cfg)
        self.assertIn("用户", source)
        self.assertTrue(dims[0].core)


class TestTiers(unittest.TestCase):
    def test_strong_resume_key_recommendation(self):
        r = score_resume(RESUME_STRONG, JD_FINANCE, candidate_name="李四")
        self.assertGreaterEqual(r["overall"], 8.5, r["report"])
        self.assertEqual(r["tier"], "key")
        self.assertFalse(r["cap_applied"])
        self.assertTrue(r["recommendation"], "≥8.5 必须产出推荐语")
        self.assertLessEqual(len(r["recommendation"]), 320)
        self.assertTrue(r["strengths"])
        self.assertTrue(r["dimensions"][0]["evidence"])

    def test_borderline_resume(self):
        r = score_resume(RESUME_BORDERLINE, JD_FINANCE, candidate_name="王五")
        self.assertGreaterEqual(r["overall"], 6.0, r["report"])
        self.assertLess(r["overall"], 7.0, r["report"])
        self.assertEqual(r["tier"], "borderline")
        self.assertFalse(r["recommendation"], "临界档不产出推荐语")
        self.assertTrue(r["gaps"], "临界档必须列缺口")

    def test_weak_resume_reject(self):
        r = score_resume(RESUME_WEAK, JD_FINANCE, candidate_name="赵六")
        self.assertLess(r["overall"], 6.0, r["report"])
        self.assertEqual(r["tier"], "reject")
        self.assertFalse(r["recommendation"])
        self.assertTrue(r["mismatch_reason"], "<6 只给分数+不匹配原因")

    def test_cap_rule_halo_cannot_replace_core(self):
        r = score_resume(RESUME_HALO_NO_CORE, JD_FINANCE, candidate_name="孙七")
        self.assertTrue(r["cap_applied"], r["report"])
        self.assertLessEqual(r["overall"], 6.0, "缺核心证据时总分必须封顶 ≤6.0")
        self.assertTrue(r["halo_bonus"] > 0, "光环背景应产生加分")
        self.assertTrue(any("光环" in s or "清华" in s or "麦肯锡" in s for s in r["priority_backgrounds"]))
        self.assertFalse(r["recommendation"], "触发封顶不得产出推荐语")
        self.assertTrue(any("封顶" in g for g in r["gaps"]))

    def test_llm_hook_optional(self):
        def enhancer(result, resume_text, jd_text):
            result["overall"] = 9.9
            return result
        r = score_resume(RESUME_STRONG, JD_FINANCE, llm_enhancer=enhancer)
        self.assertEqual(r["overall"], 9.9)
        r2 = score_resume(RESUME_STRONG, JD_FINANCE)  # 默认关闭
        self.assertNotEqual(r2["overall"], 9.9)

    def test_relative_position(self):
        r = score_resume(RESUME_STRONG, JD_FINANCE, history=[5.0, 6.5, 7.2])
        self.assertIn("排第 1", r["relative_position"])

    def test_report_format_sections(self):
        r = score_resume(RESUME_STRONG, JD_FINANCE)
        for marker in ["综合匹配度", "各维度得分及简历证据", "核心优势", "关键缺口", "待验证问题", "相对位置"]:
            self.assertIn(marker, r["report"])

    def test_too_short_resume_rejected(self):
        with self.assertRaises(ValueError):
            score_resume("太短", JD_FINANCE)


if __name__ == "__main__":
    unittest.main()
