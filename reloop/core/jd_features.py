"""JD 特征规范化层(纯算法, 零 IO)。

框架改造①(2026-08-28): positions.jd_analysis(AI 解析产物)此前落库后
全链路零消费, 匹配引擎从原文重抽特征(中文整句当关键词/正则扫年限学历)。
本模块把解析字段规范化为匹配特征; 无解析产物时原文正则仅作兜底。

公开: JDFeatures / build_jd_features
"""

import re
from dataclasses import dataclass, field
from typing import Optional, Sequence

from reloop.core.matching import (
    extract_edu_requirement,
    extract_years_requirement,
    normalize_skills,
)

_UNSET = "未提供"


@dataclass
class JDFeatures:
    """规范化后的 JD 匹配特征(供召回层/评分层/LLM 精算层统一消费)。"""
    skill_list: list[str] = field(default_factory=list)       # 规范化必备+优选技能
    industry_keywords: list[str] = field(default_factory=list)
    years_min: Optional[float] = None                          # 经验下限(年)
    edu_min: Optional[str] = None                              # 学历下限(大专/本科/硕士/博士)
    recall_keywords: list[str] = field(default_factory=list)   # 召回词(技能+行业词+岗位名)
    source: str = "raw"                                        # analysis | raw


def _clean_list(items: Optional[Sequence[str]]) -> list[str]:
    out: list[str] = []
    for it in items or []:
        s = str(it).strip()
        if s and s != _UNSET:
            out.append(s)
    return out


def _years_from_text(text: Optional[str]) -> Optional[float]:
    """'3-5年'/'3年以上'/'5年' -> 下限; '不限/应届/未提供' -> None。"""
    if not text:
        return None
    t = str(text).strip()
    if _UNSET in t or "不限" in t or "应届" in t:
        return None
    m = re.search(r"(\d+)\s*[-~至到]\s*(\d+)\s*年", t)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+)\s*年", t)
    if m:
        return float(m.group(1))
    return None


def _edu_from_text(text: Optional[str]) -> Optional[str]:
    """学历要求文本 -> 最低学历档(从高到低命中即取)。"""
    if not text:
        return None
    t = str(text)
    if _UNSET in t or "不限" in t:
        return None
    for lvl in ("博士", "硕士", "本科", "大专"):
        if lvl in t:
            return lvl
    return None


def build_jd_features(position_name: Optional[str],
                      jd_text: Optional[str],
                      jd_analysis: Optional[dict]) -> JDFeatures:
    """从 jd_analysis 构建匹配特征; 无解析产物时走原文兜底。"""
    a = jd_analysis if isinstance(jd_analysis, dict) else {}
    skills = normalize_skills(
        _clean_list(a.get("required_skills")) + _clean_list(a.get("preferred_skills")))
    industry = [k for k in _clean_list(a.get("industry_keywords")) if len(k) >= 2]

    years = _years_from_text(a.get("experience"))
    if years is None:
        years = extract_years_requirement(jd_text)

    edu = _edu_from_text(a.get("education"))
    if edu is None:
        edu = extract_edu_requirement(jd_text)

    feats = JDFeatures(
        skill_list=skills,
        industry_keywords=industry,
        years_min=years,
        edu_min=edu,
        source="analysis" if a else "raw",
    )

    recall = []
    if position_name and position_name.strip():
        recall.append(position_name.strip())
    recall.extend(skills)
    recall.extend(industry)
    if not recall:
        parts = re.split(r"[\s,，、/;；|]+", f"{position_name or ''} {jd_text or ''}")
        recall = [p.strip() for p in parts if len(p.strip()) >= 2]
    seen: set[str] = set()
    out: list[str] = []
    for k in recall:
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    feats.recall_keywords = out[:30]
    return feats
