"""质量闸门（R6）：有效简历 4 要素打分，纯函数可单测。

4 要素（黑客松 KR「有效简历率 ≥60%」的判定口径）：
    1. complete_resume — 完整简历：raw_text 达到最小长度
    2. phone           — 手机号：CandidateRecord 已做格式归一（非法→None）
    3. intent          — 求职意向：expected_title / opportunity_intent 一级列优先，
                         否则 raw_text 关键词兜底（parser 修复前的过渡方案）
    4. salary_level    — 薪资职级：expected_salary 一级列优先，否则 raw_text 兜底

输出 quality_score = 通过项数 / 4，missing_fields = 未通过项的键名数组。
入库时随行写入 cloud_candidates.quality_score / missing_fields。
"""
from __future__ import annotations

import re
from typing import Any

#: 完整简历的 raw_text 最小字符数（低于此值视为骨架/摘要，不算完整简历）
RAW_TEXT_MIN_CHARS = 200

_INTENT_RE = re.compile(r"求职意向|期望职位|意向岗位|目标岗位|期望工作|求职目标|职业目标")
_SALARY_RE = re.compile(
    r"期望薪资|期望月薪|期望年薪|薪资要求|月薪|年薪|\d{2,3}\s*[kK]|\d+\s*万\s*[/／]?\s*年|职级"
)

ELEMENTS = ("complete_resume", "phone", "intent", "salary_level")


def _get(source: Any, key: str) -> Any:
    if hasattr(source, "model_dump"):
        return getattr(source, key, None)
    if isinstance(source, dict):
        return source.get(key)
    return getattr(source, key, None)


def evaluate_quality(record: Any) -> tuple[float, list[str]]:
    """Score one CandidateRecord（或 dict）against the 4 elements.

    Returns:
        (quality_score 0-1, missing_fields 键名数组)
    """
    raw_text = (_get(record, "raw_text") or "").strip()
    phone = (_get(record, "phone") or "").strip()
    expected_title = (_get(record, "expected_title") or "").strip()
    opportunity_intent = (_get(record, "opportunity_intent") or "").strip()
    expected_salary = (_get(record, "expected_salary") or "").strip()

    checks = {
        "complete_resume": len(raw_text) >= RAW_TEXT_MIN_CHARS,
        "phone": bool(phone),
        "intent": bool(expected_title or opportunity_intent) or bool(_INTENT_RE.search(raw_text)),
        "salary_level": bool(expected_salary) or bool(_SALARY_RE.search(raw_text)),
    }
    missing = [key for key, ok in checks.items() if not ok]
    score = (len(ELEMENTS) - len(missing)) / len(ELEMENTS)
    return score, missing
