"""
JD 对齐评分：针对「新消费品牌策略顾问（投后-明星消费基金）」岗位。
与 candidate-collector 共用，支持纯文本输入。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


DIMS = [
    "消费品牌/战略咨询经验",
    "结构化思维与研究能力",
    "创业团队沟通协作",
    "独立思考与学习敏锐度",
    "教育背景",
    "职业背景适配",
]
WEIGHTS = [0.30, 0.20, 0.20, 0.15, 0.10, 0.05]

KEYWORDS: dict[str, list[str]] = {
    "消费品牌/战略咨询经验": [
        "消费品牌", "品牌战略", "品牌策略", "品牌定位", "产品定义", "增长模式", "战略咨询",
        "咨询顾问", "罗兰贝格", "贝恩", "麦肯锡", "BCG", "思略特", "久谦", "沙利文",
        "消费品", "食品饮料", "新消费", "零食", "美妆", "母婴", "个护", "奈雪", "喜茶",
        "王小卤", "百事", "宝洁", "联合利华", "欧莱雅", "可口可乐", "农夫山泉",
    ],
    "结构化思维与研究能力": [
        "市场研究", "行业研究", "竞争格局", "消费者洞察", "用户研究", "趋势分析",
        "对标分析", "benchmark", "数据分析", "商业分析", "战略分析", "经营分析",
        "案头研究", "定性访谈", "定量研究", "问卷", "焦点小组", "专家访谈",
        "战略框架", "问题拆解", "假设驱动", "逻辑树", "MECE",
    ],
    "创业团队沟通协作": [
        "创始团队", "创始人", "跨部门协作", "协同", "推动共识", "项目管理", "PMO",
        "利益相关方", "stakeholder", "沟通", "汇报", "工作坊", "研讨会", "共创",
        "从0到1", "0-1", "新业务", "新业务孵化", "业务协同", "资源整合",
    ],
    "独立思考与学习敏锐度": [
        "好奇心", "持续学习", "新兴品牌", "消费趋势", "行业动态", "独立思考",
        "创新", "探索", "快速学习", "自驱", "主动", "CFA", "CPA", "GMAT", "雅思",
        "多语言", "英语", "法语", "粤语", "海外", "交换", "留学",
    ],
    "教育背景": [
        "硕士", "MBA", "复旦", "北大", "清华", "浙大", "人大", "港大", "香港大学",
        "LSE", "伦敦政治经济学院", "博科尼", "WUSTL", "中央财经大学", "武汉大学",
        "985", "211", "双一流", "Top", "一等荣誉", "GPA", "奖学金",
    ],
    "职业背景适配": [
        "3年", "4年", "5年", "3-5年", "战略", "品牌", "咨询", "消费", "消费品",
        "品牌策略", "战略规划", "战略运营", "投后", "投资", "战投",
    ],
}

# 注意：启承隐藏偏好是“讨厌大厂背景”，但外企巨头惩罚较轻。
BIG_TECH = [
    "阿里巴巴", "阿里", "腾讯", "字节跳动", "字节", "美团", "拼多多", "百度", "京东",
    "快手", "滴滴", "荣耀", "华为", "小米", "沃尔玛",
]
BIG_TECH_LIGHT = ["宝洁", "百事", "联合利华", "欧莱雅", "可口可乐"]


@dataclass(frozen=True)
class JdScoreResult:
    overall: float
    scores: dict[str, int]
    big_tech_penalty: int
    evidence: dict[str, list[str]]
    recommendation: str


def _keyword_score(text: str, keywords: list[str]) -> int:
    text = text.lower()
    hits = sum(1 for kw in keywords if kw.lower() in text)
    return min(100, int(30 + 10 * hits**0.8))


def _evidence_lines(text: str, keywords: list[str], limit: int = 3) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if len(line.strip()) >= 8]
    matches: list[str] = []
    for line in lines:
        if any(kw.lower() in line.lower() for kw in keywords):
            matches.append(line)
            if len(matches) >= limit:
                break
    return matches


def _detect_big_tech(text: str) -> int:
    for name in BIG_TECH:
        if name in text:
            return -10
    for name in BIG_TECH_LIGHT:
        if name in text:
            return -5
    return 0


def _infer_recommendation(overall: float) -> str:
    if overall >= 80:
        return "强推"
    if overall >= 65:
        return "建议沟通"
    if overall >= 50:
        return "备选/需补证"
    return "信息不足"


def evaluate(text: str) -> JdScoreResult:
    """对一段简历文本做 JD 对齐评分。"""
    scores = {dim: _keyword_score(text, KEYWORDS[dim]) for dim in DIMS}
    penalty = _detect_big_tech(text)
    weighted = sum(scores[d] * w for d, w in zip(DIMS, WEIGHTS))
    overall = max(0.0, min(100.0, weighted + penalty))

    # 启承隐藏偏好：如果大厂背景但创业团队沟通/职业适配被高估，额外压低。
    if penalty and scores["创业团队沟通协作"] > 75:
        overall = max(0.0, overall - 8)
    if penalty and scores["职业背景适配"] > 80:
        overall = max(0.0, overall - 7)

    evidence = {dim: _evidence_lines(text, KEYWORDS[dim]) for dim in DIMS}
    return JdScoreResult(
        overall=round(overall, 1),
        scores=scores,
        big_tech_penalty=penalty,
        evidence=evidence,
        recommendation=_infer_recommendation(overall),
    )


def evaluate_to_dict(text: str) -> dict[str, Any]:
    r = evaluate(text)
    return {
        "overall": r.overall,
        "recommendation": r.recommendation,
        "scores": r.scores,
        "big_tech_penalty": r.big_tech_penalty,
        "evidence": r.evidence,
    }
