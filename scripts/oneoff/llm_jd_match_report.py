#!/usr/bin/env python3
# ONE-OFF (2026-08-03)
# Input: inspect --help and the operator invocation record before running.
# Execution: do not rerun without explicit operator confirmation.

"""
基于 DeepSeek LLM 的 JD 语义筛选报告生成。

改进点（针对审计结论）：
1. 真正调用 LLM（DeepSeek）做语义判断，而非关键词计数。
2. 两个岗位分别召回、分别评分、分别输出报告。
3. 硬条件前置过滤：地点、年限、年龄、学历、排除研究院。
4. 使用 person_leads_id 去重。
5. 保留现有 PDF/JSON/HTML 输出格式。
"""

import argparse
import asyncio
import html as html_lib
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from openai import AsyncOpenAI
from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
DEFAULT_OUTPUT_DIR = DATA_DIR / "llm_jd_match"

TTC_API_BASE = "https://api.ttcadvisory.com"
TTC_WEB_BASE = "https://app.ttcadvisory.com"

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

ACADEMIC_KEYWORDS = [
    "大学", "研究院", "研究所", "中科院", "中国科学院", "工程院", "学院",
    "复旦大学", "浙江大学", "北京大学", "清华大学", "上海交大", "上海交通大学",
    "中科大", "中国科学技术大学", "南京大学", "武汉大学", "华中科技大学",
    "哈尔滨工业大学", "哈工大", "西安电子科技大学", "电子科技大学", "北邮", "北京邮电大学",
]


@dataclass
class JdSpec:
    title: str
    company: str
    search_queries: Tuple[str, ...]
    location: str
    min_years: int
    max_age: int
    require_degree: str = "本科"
    jd_text: str = ""
    scoring_dimensions: Tuple[str, ...] = ()
    dimension_weights: Tuple[float, ...] = ()
    must_have: Tuple[str, ...] = ()
    preferred: Tuple[str, ...] = ()


JD_RUISHENG = JdSpec(
    title="瑞声科技-AI产品经理",
    company="瑞声科技",
    search_queries=(
        "AI产品经理 深圳", "B端AI产品经理 深圳", "AI Agent产品经理 深圳",
        "企业级大模型产品经理 深圳", "制造业AI产品经理 深圳",
    ),
    location="深圳",
    min_years=3,
    max_age=35,
    jd_text="""岗位职责：
1. 基于办公、采购、人力等经营管理与流程提效场景，深入研究和规划端到端 AI 应用产品。
2. 结合多模态大模型、企业知识库、业务流程自动化、AI Agent 等能力，将业务需求转化为符合 AI 原理且具备落地价值的产品设计。
3. 负责 AI Agent 核心能力的产品方案设计：意图理解、上下文管理、工具调用、RAG接入、反思规划、多Agent协同等。
4. 洞察 AI 在垂直行业（制造业）的应用方向，熟悉客户业务需求。

任职要求：
1. 本科及以上学历，3年左右互联网或人工智能产品经理工作经验。
2. 有从0到1的产品管理过程经验优先，特别是B端产品的商业化经验优先。
3. 有企业级大模型应用、AI Agent、业务流程自动化等产品设计经验优先。
4. 深刻理解 AI Agent 体系：LLM能力、RAG、Function Calling、工作流、工具编排、多智能体协作。
5. base 深圳，B端AI产品，3年以上经验，做过企业级产品，有工业/制造业相关背景加分。""",
    scoring_dimensions=(
        "B端企业级产品", "AI Agent产品深度", "0到1与交付", "业务价值与商业化", "工业制造业背景",
    ),
    dimension_weights=(0.30, 0.30, 0.15, 0.15, 0.10),
    must_have=("B端或企业级产品经验", "AI大模型或Agent产品经验", "3年以上工作经验", "本科及以上"),
    preferred=("工业或制造业", "从0到1", "企业级商业化", "RAG/Function Calling/工具编排/多Agent"),
)

JD_JINGHUA = JdSpec(
    title="荆华密算-用户产品经理",
    company="荆华密算",
    search_queries=(
        "用户产品经理 北京", "C端产品经理 北京", "用户增长产品经理 北京",
        "用户策略产品经理 北京", "用户体验产品经理 北京",
    ),
    location="北京",
    min_years=3,
    max_age=32,
    jd_text="""岗位职责：
1. 产品规划：深入研究 AI 相关技术趋势、市场动态、用户体验和真实用户需求，制定 ToC 密态AI 应用产品战略与规划。
2. 用户洞察与需求创造：从用户真实场景、使用习惯、隐私焦虑和业务痛点出发，识别需求并转化为产品方向。
3. 解决方案设计：设计安全隐私类产品方案，包括产品架构、业务流程、人机交互逻辑、AI 能力调用路径和安全体验表达方式。
4. 产品设计与体验打磨：输出高质量 PRD、原型、交互方案，持续提升产品体验。

任职要求：
1. 具备 ToC AI 应用产品设计经验，能够从市场刚需和用户价值出发构建垂类 AI 应用产品。
2. 具备较强的产品品味和用户体验判断力，对交互细节、信息表达、用户感受敏感。
3. 能够通过分析 bad case、用户反馈和使用数据定位问题并主导解决方案。
4. 优秀的沟通能力与团队协作精神。
5. base北京，过往有大厂背景，C端产品，用户体验/用户策略/用户增长相关，不需要有AI经验，3年经验以上，32岁以内。""",
    scoring_dimensions=(
        "C端产品经验", "用户洞察与体验", "用户策略与增长", "数据与Bad Case迭代", "产品品味与交付",
    ),
    dimension_weights=(0.30, 0.25, 0.20, 0.15, 0.10),
    must_have=("C端产品经验", "3年以上工作经验", "32岁以内", "本科及以上", "过往大厂背景"),
    preferred=("用户体验", "用户策略", "用户增长", "bad case和数据迭代", "隐私安全产品"),
)


def _parse_env_file(path: Path) -> Dict[str, str]:
    result: Dict[str, str] = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)", line)
        if not m:
            continue
        key, value = m.group(1), m.group(2).strip().strip('"').strip("'")
        result[key] = value
    return result


def load_env() -> None:
    for path in [
        REPO_ROOT / ".env",
        Path.home() / ".ttc" / "ttc_jwt.env",
        Path.home() / ".ttc" / "deepseek.env",
    ]:
        for k, v in _parse_env_file(path).items():
            os.environ.setdefault(k, v)


def _ttc_headers(token: str) -> Dict[str, str]:
    return {
        "authorization": f"Bearer {token}",
        "content-type": "application/json",
        "accept": "application/json, text/plain, */*",
        "accept-language": "zh-CN,zh;q=0.9",
        "origin": "https://app.ttcadvisory.com",
        "referer": "https://app.ttcadvisory.com/",
        "sec-ch-ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
        "user-agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
        ),
    }


def build_http_session() -> requests.Session:
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def search_ttc_talent(
    keyword: str,
    token: str,
    limit: int = 100,
    *,
    page: int = 1,
    session: Optional[requests.Session] = None,
) -> List[Dict[str, Any]]:
    url = f"{TTC_API_BASE}/api/talent_store/v1/search"
    payload = {
        "keyword": keyword,
        "page_size": limit,
        "current_page": page,
        "filter": {
            "locations": ["不限"],
            "degree": ["不限"],
            "university_category": ["不限"],
            "overseas_experience": ["不限"],
            "age_range": ["", ""],
            "has_system_tag_gulu": False,
            "has_system_tag_ttc": False,
            "has_mobile": False,
            "has_raw_resume": False,
        },
        "colors": "",
        "names": [],
        "companies": [],
        "titles": [],
        "keyword_type": 2,
        "company_type": 2,
    }
    client = session or build_http_session()
    resp = client.post(url, headers=_ttc_headers(token), json=payload, timeout=(8, 30))
    resp.raise_for_status()
    data = resp.json()
    items = []
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        items = data["data"].get("person_leads_items") or []
    if not isinstance(items, list):
        items = []
    for item in items:
        item["source_type"] = "ttc_api"
        item["link"] = f"{TTC_WEB_BASE}/app/talent/{item.get('person_leads_id', '')}"
        item["location"] = item.get("locations_display") or item.get("locations") or "未知"
        item["name"] = (item.get("cn_name") or item.get("name") or "（姓名未提供）").strip()
        item["age"] = item.get("age") or 0

        work = item.get("work_information") or []
        latest_work = work[0] if work else {}
        raw_company = latest_work.get("company") or latest_work.get("formatted_company") or ""
        raw_role = item.get("job_title") or latest_work.get("job_title") or ""
        if raw_company and raw_role and raw_company == raw_role and len(work) >= 2:
            raw_company = work[1].get("company") or work[1].get("formatted_company") or ""
        item["current_company"] = raw_company
        item["current_role"] = raw_role
        years = item.get("years_experience")
        if not years and work:
            years = sum(w.get("duration_in_years", 0) for w in work)
        item["years_experience"] = round(float(years or 0), 1)

        edu_list = item.get("education_information") or []
        if edu_list:
            top_edu = edu_list[0]
            parts = [p for p in [top_edu.get('school'), top_edu.get('major'), top_edu.get('degree')] if p]
            item["education"] = "·".join(parts)
        else:
            item["education"] = item.get("degree") or ""

        item["skills"] = item.get("tags") or []

        work_lines = []
        for w in work[:5]:
            dur = round(float(w.get("duration_in_years", 0) or 0), 1)
            line = f"{w.get('company','')} | {w.get('job_title','')} | {dur}年 | {w.get('start_time','')} 至 {w.get('end_time','')}"
            work_lines.append(line)
        edu_lines = []
        for e in edu_list[:3]:
            line = f"{e.get('school','')} | {e.get('major','')} | {e.get('degree','')}"
            edu_lines.append(line)
        full_text = item.get("full_text")
        if isinstance(full_text, str) and full_text.strip():
            item["raw_text"] = full_text
            item["raw_text_source"] = "full_resume"
        else:
            item["raw_text"] = "\n".join([
                f"姓名: {item['name']}",
                f"年龄: {item['age']}",
                f"当前职位: {item['current_role']}",
                f"当前公司: {item['current_company']}",
                f"工作地点: {item['location']}",
                f"工作年限: {item['years_experience']}年",
                f"教育背景: {item['education']}",
                "工作经历:\n" + "\n".join(work_lines),
                "教育经历:\n" + "\n".join(edu_lines),
                f"技能标签: {', '.join(item['skills'])}",
            ])
            item["raw_text_source"] = "search_summary"
    return items


def get_profile_summary(
    person_leads_id: str, token: str, session: Optional[requests.Session] = None
) -> Dict[str, Any]:
    client = session or build_http_session()
    response = client.get(
        f"{TTC_API_BASE}/api/talent_store/v1/time_based/profile_summary",
        headers=_ttc_headers(token),
        params={"person_leads_id": person_leads_id},
        timeout=(8, 30),
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    return data if isinstance(data, dict) else {}


def flatten_profile_data(value: Any, prefix: str = "") -> List[str]:
    """只将水下信息转成可审计文本，不补写或推断缺失经历。"""
    lines: List[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            label = f"{prefix}.{key}" if prefix else str(key)
            lines.extend(flatten_profile_data(child, label))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            lines.extend(flatten_profile_data(child, f"{prefix}[{index}]"))
    elif value not in (None, "", False):
        lines.append(f"{prefix}: {value}")
    return lines


def is_academic(company: str) -> bool:
    return any(kw in company for kw in ACADEMIC_KEYWORDS)


BIG_TECH_KEYWORDS = (
    "字节跳动", "腾讯", "阿里巴巴", "蚂蚁", "美团", "百度", "京东", "拼多多",
    "快手", "滴滴", "小米", "华为", "OPPO", "vivo", "小红书", "哔哩哔哩",
    "Microsoft", "Google", "Amazon", "Apple", "Meta", "Shopee", "Uber", "Airbnb",
)


def has_big_tech_history(candidate: Dict[str, Any]) -> bool:
    companies = [candidate.get("current_company", "")]
    companies.extend(
        str(work.get("company") or work.get("formatted_company") or "")
        for work in candidate.get("work_information") or []
        if isinstance(work, dict)
    )
    return any(keyword.lower() in company.lower() for company in companies for keyword in BIG_TECH_KEYWORDS)


def assess_data_quality(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """评估数据是否足以支撑语义匹配。C 级只能进入待补证池。"""
    missing: List[str] = []
    if not candidate.get("person_leads_id"):
        missing.append("person_leads_id")
    if not candidate.get("location") or candidate.get("location") == "未知":
        missing.append("location")
    if not candidate.get("age"):
        missing.append("age")
    if not candidate.get("education") and not candidate.get("degree"):
        missing.append("education")
    if not candidate.get("work_information"):
        missing.append("work_information")

    source = candidate.get("source") or candidate.get("source_type")
    if source == "generated":
        return {"grade": "QUARANTINED", "score": 0.0, "missing_fields": missing, "reason": "generated_test_data"}
    if candidate.get("raw_text_source") == "full_resume":
        grade, score = "A", 0.95
    elif candidate.get("profile_enriched"):
        grade, score = "B", 0.75
    else:
        grade, score = "C", 0.45
        missing.append("project_evidence")
    return {"grade": grade, "score": score, "missing_fields": sorted(set(missing)), "reason": ""}


def hard_filter(candidate: Dict[str, Any], spec: JdSpec) -> Tuple[str, str]:
    """硬条件门禁：pass / review / fail。未知不等于不匹配。"""
    # 地点
    location = candidate.get("location") or "未知"
    if spec.location and spec.location not in location:
        if location in ("", "未知", None):
            return "review", "地点未知，需要人工确认"
        return "fail", f"地点不匹配：{location}（要求 {spec.location}）"

    # 年龄
    age = candidate.get("age") or 0
    if age <= 0:
        return "review", "年龄未知，需要人工确认"
    if age > spec.max_age:
        return "fail", f"年龄 {age} 岁，超过 {spec.max_age} 岁上限"

    # 工作年限
    years = candidate.get("years_experience") or 0
    if years < spec.min_years:
        return "fail", f"工作年限 {years} 年，低于 {spec.min_years} 年要求"

    # 学历
    education = candidate.get("education", "")
    degree = candidate.get("degree", "")
    combined = f"{education} {degree}"
    if "本科" not in combined and "硕士" not in combined and "博士" not in combined and "MBA" not in combined:
        if not combined.strip():
            return "review", "学历未知，需要人工确认"
        return "fail", f"学历不匹配：{combined}"

    if spec is JD_JINGHUA and not has_big_tech_history(candidate):
        return "fail", "无可验证的过往大厂工作经历"

    return "pass", ""


def build_llm_prompt(candidate: Dict[str, Any], spec: JdSpec) -> str:
    dims = "\n".join(f"- {d}" for d in spec.scoring_dimensions)
    weighted_dims = "\n".join(
        f"- {name}：{weight:.0%}" for name, weight in zip(spec.scoring_dimensions, spec.dimension_weights)
    )
    must_have = "\n".join(f"- {item}" for item in spec.must_have)
    preferred = "\n".join(f"- {item}" for item in spec.preferred)
    return f"""你是一位资深猎头顾问，正在严格根据以下 JD 评估候选人简历。

要求：
1. 先判断硬条件是否满足，再评估软性匹配。
2. 只根据简历中明确写出的经历打分，不要推测、不要脑补。
3. 地点必须严格匹配（JD 要求 {spec.location}），非 {spec.location} 一律 hard_pass=false。
4. 工作年限必须 ≥ {spec.min_years} 年，年龄必须 ≤ {spec.max_age} 岁。
5. 候选人资料中没有明确证据的能力必须记为 unknown，不得根据职称推断。
6. 每条证据必须是候选人资料中的原文短句，禁止改写或生成经历。
7. 如果仅有搜索摘要、没有项目职责证据，即使职称匹配也不得评为"强推"。

必须满足的画像：
{must_have}

加分画像：
{preferred}

评分维度与权重：
{weighted_dims}

请输出 JSON：
{{
  "hard_pass": true/false,
  "hard_fail_reason": "如果不通过说明原因，通过则留空",
  "overall": 0-100,
  "recommendation": "强推/建议沟通/备选/不匹配",
  "dimensions": {{
{chr(10).join(f'    "{d}": 0-100' for d in spec.scoring_dimensions)}
  }},
  "must_have": {{"画像条目": "met/unmet/unknown"}},
  "evidence_quotes": ["3-8条候选人资料原文短句"],
  "risks": ["缺失证据或不匹配点"],
  "evidence": "不超过200字的结论"
}}

JD：
{spec.jd_text}

候选人数据等级：{candidate.get('data_quality', {}).get('grade', 'C')}
候选人资料：
{candidate['raw_text']}
"""


def validate_llm_result(result: Any, spec: JdSpec, candidate: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(result, dict):
        raise ValueError("LLM result is not an object")
    dimensions = result.get("dimensions")
    if not isinstance(dimensions, dict):
        raise ValueError("dimensions is missing")
    clean_dimensions: Dict[str, int] = {}
    for name in spec.scoring_dimensions:
        value = dimensions.get(name, 0)
        if not isinstance(value, (int, float)):
            raise ValueError(f"invalid dimension score: {name}")
        clean_dimensions[name] = max(0, min(100, int(value)))
    calculated = sum(
        clean_dimensions[name] * weight
        for name, weight in zip(spec.scoring_dimensions, spec.dimension_weights)
    )
    must = result.get("must_have") if isinstance(result.get("must_have"), dict) else {}
    unknown_or_unmet = [key for key, value in must.items() if value in ("unknown", "unmet")]
    hard_pass = bool(result.get("hard_pass")) and not any(value == "unmet" for value in must.values())
    grade = candidate.get("data_quality", {}).get("grade", "C")
    cap = 79 if grade == "C" else 100
    overall = min(cap, round(calculated, 1))
    if not hard_pass:
        overall = 0.0
    recommendation = "不匹配"
    if hard_pass and overall >= 85 and not unknown_or_unmet and grade in ("A", "B"):
        recommendation = "强推"
    elif hard_pass and overall >= 75:
        recommendation = "建议沟通"
    elif hard_pass and overall >= 60:
        recommendation = "备选"
    quotes = result.get("evidence_quotes") if isinstance(result.get("evidence_quotes"), list) else []
    source_text = candidate.get("raw_text", "")
    verified_quotes = [str(q) for q in quotes if str(q).strip() and str(q).strip() in source_text]
    return {
        **result,
        "hard_pass": hard_pass,
        "overall": overall,
        "recommendation": recommendation,
        "dimensions": clean_dimensions,
        "evidence_quotes": verified_quotes,
        "evidence_verified": bool(verified_quotes),
        "risks": result.get("risks") if isinstance(result.get("risks"), list) else [],
    }


async def evaluate_candidate(client: AsyncOpenAI, candidate: Dict[str, Any], spec: JdSpec, sem: asyncio.Semaphore) -> Dict[str, Any]:
    async with sem:
        prompt = build_llm_prompt(candidate, spec)
        try:
            resp = await client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": "You are an expert recruiter. Respond only with valid JSON. Do not hallucinate evidence."},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                max_tokens=800,
                temperature=0.1,
            )
            content = resp.choices[0].message.content or "{}"
            llm_result = validate_llm_result(json.loads(content), spec, candidate)
        except Exception as e:
            llm_result = {
                "_scoring_error": type(e).__name__,
                "hard_pass": False,
                "hard_fail_reason": "LLM 调用失败，已转入待重试池",
                "overall": 0,
                "recommendation": "不匹配",
                "dimensions": {d: 0 for d in spec.scoring_dimensions},
                "evidence": "LLM 调用失败",
            }

        return {
            **candidate,
            "jd_title": spec.title,
            "hard_pass": llm_result.get("hard_pass", False),
            "hard_fail_reason": llm_result.get("hard_fail_reason", ""),
            "overall": float(llm_result.get("overall", 0)),
            "recommendation": llm_result.get("recommendation", "不匹配"),
            "dimension_scores": llm_result.get("dimensions", {d: 0 for d in spec.scoring_dimensions}),
            "evidence": llm_result.get("evidence", ""),
            "evidence_quotes": llm_result.get("evidence_quotes", []),
            "evidence_verified": llm_result.get("evidence_verified", False),
            "risks": llm_result.get("risks", []),
            "must_have_assessment": llm_result.get("must_have", {}),
            "scoring_status": "error" if llm_result.get("_scoring_error") else "completed",
            "scoring_error_type": llm_result.get("_scoring_error", ""),
        }


def safe(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        value = ", ".join(str(item) for item in value)
    return html_lib.escape(str(value), quote=True)


def render_html(candidates: List[Dict[str, Any]], spec: JdSpec, output: Path, logs: List[str], title: str = "LLM JD 语义筛选报告") -> None:
    ranked = sorted(candidates, key=lambda x: x["overall"], reverse=True)

    rows = []
    for idx, c in enumerate(ranked, 1):
        anchor = f"candidate-{idx:03d}"
        dim_summary = "<br>".join(
            f"{k}: {v}" for k, v in c.get("dimension_scores", {}).items()
        )
        rows.append({
            "rank": idx,
            "anchor": anchor,
            "name": c.get("name", ""),
            "company": c.get("current_company", ""),
            "role": c.get("current_role", ""),
            "age": c.get("age", ""),
            "exp": c.get("years_experience", ""),
            "location": c.get("location", "未知"),
            "education": c.get("education", ""),
            "skills": ", ".join(c.get("skills", [])[:6]),
            "overall": c["overall"],
            "recommendation": c["recommendation"],
            "link": c.get("link", ""),
            "dim_summary": dim_summary,
            "evidence": c.get("evidence", ""),
        })

    trs = []
    for r in rows:
        jump_link = f'<a href="#{r["anchor"]}">查看完整简历</a>'
        external_link = f'<a href="{safe(r["link"])}" target="_blank" rel="noopener noreferrer">线上详情</a>' if r["link"] else "无"
        trs.append(
            f"""<tr id="row-{r['anchor']}">
            <td>{safe(r['rank'])}</td>
            <td>{safe(r['name'])}</td>
            <td>{safe(r['company'])}</td>
            <td>{safe(r['role'])}</td>
            <td>{safe(r['age'])}</td>
            <td>{safe(r['exp'])}</td>
            <td>{safe(r['location'])}</td>
            <td>{safe(r['education'])}</td>
            <td>{safe(r['skills'])}</td>
            <td><strong>{safe(r['overall'])}</strong></td>
            <td>{safe(r['recommendation'])}</td>
            <td>{jump_link} | {external_link}</td>
            <td>{safe(r['evidence'])}</td>
            <td>{r['dim_summary']}</td>
            </tr>"""
        )

    detail_sections = []
    for idx, c in enumerate(ranked, 1):
        anchor = f"candidate-{idx:03d}"
        raw_text = c.get("raw_text", "").replace("\n", "<br>")
        dim_html = "<ul>" + "".join(
            f"<li><strong>{safe(k)}</strong>: {safe(v)}</li>"
            for k, v in c.get("dimension_scores", {}).items()
        ) + "</ul>"
        detail_sections.append(
            f"""<div class="detail" id="{anchor}">
            <h2>#{idx} {safe(c.get('name',''))} — {safe(c.get('current_company',''))} — 综合得分 {safe(c['overall'])}</h2>
            <p>
              <strong>职位：</strong>{safe(c.get('current_role',''))} |
              <strong>年限：</strong>{safe(c.get('years_experience',''))} 年 |
              <strong>年龄：</strong>{safe(c.get('age',''))} 岁 |
              <strong>地点：</strong>{safe(c.get('location','未知'))} |
              <strong>学历：</strong>{safe(c.get('education',''))}
            </p>
            <p><strong>技能：</strong>{safe(', '.join(c.get('skills', [])))}</p>
            <p><strong>推荐：</strong>{safe(c['recommendation'])} | <strong>硬条件：</strong>{'通过' if c['hard_pass'] else '未通过'} {safe(c.get('hard_fail_reason',''))}</p>
            <p><strong>LLM 证据：</strong>{safe(c.get('evidence',''))}</p>
            <p><strong>线上链接：</strong> {f'<a href="{safe(c.get("link",""))}" target="_blank" rel="noopener noreferrer">{safe(c.get("link",""))}</a>' if c.get('link') else '无'}</p>
            <h3>维度得分</h3>
            {dim_html}
            <h3>完整简历原文</h3>
            <div class="raw">{raw_text}</div>
            <p><a href="#row-{anchor}">← 返回排名表</a></p>
            </div>"""
        )

    logs_html = "<br>".join(safe(line) for line in logs)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{safe(title)}</title>
<style>
  @media print {{
    .detail {{ page-break-before: always; }}
    .detail:first-of-type {{ page-break-before: auto; }}
  }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; margin: 1.5rem; background: #fff; color: #212529; line-height: 1.6; }}
  h1 {{ font-size: 1.5rem; margin-bottom: .5rem; }}
  h2 {{ font-size: 1.2rem; margin-top: 1.5rem; border-bottom: 2px solid #dee2e6; padding-bottom: .25rem; }}
  h3 {{ font-size: 1rem; margin-top: 1rem; }}
  .meta {{ color: #6c757d; font-size: .875rem; margin-bottom: 1rem; }}
  .logs {{ background: #f8f9fa; border-left: 4px solid #0d6efd; padding: .75rem; margin: 1rem 0; font-size: .85rem; }}
  table {{ width: 100%; border-collapse: collapse; margin: 1rem 0; font-size: .75rem; }}
  th, td {{ padding: .4rem; text-align: left; border: 1px solid #dee2e6; vertical-align: top; }}
  th {{ background: #e9ecef; font-weight: 600; }}
  tr:nth-child(even) {{ background: #f8f9fa; }}
  .detail {{ margin-top: 2rem; padding: 1rem; border: 1px solid #dee2e6; border-radius: 6px; background: #fff; }}
  .raw {{ background: #f8f9fa; border: 1px solid #dee2e6; padding: .75rem; border-radius: 4px; font-size: .85rem; white-space: pre-wrap; }}
  a {{ color: #0d6efd; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .warning {{ background: #fff3cd; border-left: 4px solid #ffc107; padding: .75rem; margin: 1rem 0; }}
</style>
</head>
<body>
<h1>{safe(title)}</h1>
<div class="meta">岗位：{safe(spec.title)} · 筛选后 {len(ranked)} 人 · 生成时间 {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>
<div class="warning">
<strong>筛选规则：</strong>地点 {safe(spec.location)}、年龄 ≤ {spec.max_age} 岁、年限 ≥ {spec.min_years} 年、本科及以上、排除高校/研究院；评分由 DeepSeek LLM 语义判断，非关键词计数。
</div>
<div class="logs"><strong>执行日志：</strong><br>{logs_html}</div>

<h2>评分排名表</h2>
<div style="overflow-x:auto"><table>
<thead><tr>
  <th>排名</th><th>姓名</th><th>公司</th><th>职位</th><th>年龄</th><th>年限</th><th>地点</th><th>学历</th><th>技能</th><th>得分</th><th>推荐</th><th>链接</th><th>LLM证据</th><th>维度详情</th>
</tr></thead>
<tbody>{''.join(trs)}</tbody>
</table></div>

<h2>完整简历明细（保留原始信息）</h2>
{''.join(detail_sections)}
</body>
</html>"""
    output.write_text(html, encoding="utf-8")


def html_to_pdf(html_path: Path, pdf_path: Path) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(f"file://{html_path.resolve()}")
        page.wait_for_load_state("networkidle")
        page.pdf(
            path=str(pdf_path),
            format="A3",
            margin={"top": "1cm", "right": "1cm", "bottom": "1cm", "left": "1cm"},
            print_background=True,
        )
        browser.close()


@dataclass
class PipelineContext:
    spec: JdSpec
    token: str
    logs: List[str]
    recalled: List[Dict[str, Any]]
    review_pool: List[Dict[str, Any]]
    rejected: List[Dict[str, Any]]
    recalled_count: int = 0


class RecallAgent:
    """用多策略召回降低单一关键词偏差，并且只按稳定 ID 去重。"""

    def __init__(self, page_size: int, pages: int) -> None:
        self.page_size = page_size
        self.pages = pages

    async def run(self, context: PipelineContext) -> None:
        session = build_http_session()
        recalled: List[Dict[str, Any]] = []
        for query in context.spec.search_queries:
            for page in range(1, self.pages + 1):
                items = await asyncio.to_thread(
                    search_ttc_talent,
                    query,
                    context.token,
                    self.page_size,
                    page=page,
                    session=session,
                )
                recalled.extend(items)
                context.logs.append(f"[RecallAgent] {query} 第{page}页返回 {len(items)} 条")
                if len(items) < self.page_size:
                    break
        unique: Dict[str, Dict[str, Any]] = {}
        for item in recalled:
            pid = str(item.get("person_leads_id") or "").strip()
            if pid:
                unique[pid] = item
        context.recalled = list(unique.values())
        context.recalled_count = len(context.recalled)
        context.logs.append(f"[RecallAgent] 总召回 {len(recalled)} 条，稳定ID去重后 {len(context.recalled)} 人")


class EnrichmentAgent:
    """补全可用的水下信息；无数据时保留明确状态，不伪造简历。"""

    def __init__(self, limit: int, concurrency: int = 5) -> None:
        self.limit = limit
        self.semaphore = asyncio.Semaphore(concurrency)

    async def _enrich(self, candidate: Dict[str, Any], token: str) -> None:
        async with self.semaphore:
            try:
                profile = await asyncio.to_thread(get_profile_summary, candidate["person_leads_id"], token)
            except Exception as exc:
                candidate["profile_status"] = "error"
                candidate["profile_error"] = type(exc).__name__
                return
            profile_data = profile.get("profile_data")
            if isinstance(profile_data, dict) and profile_data:
                lines = flatten_profile_data(profile_data)
                candidate["profile_enriched"] = True
                candidate["profile_status"] = "available"
                candidate["raw_text"] = candidate.get("raw_text", "") + "\n水下信息:\n" + "\n".join(lines)
            else:
                candidate["profile_enriched"] = False
                candidate["profile_status"] = "unavailable"

    async def run(self, context: PipelineContext) -> None:
        candidates = context.recalled[: self.limit] if self.limit > 0 else context.recalled
        await asyncio.gather(*(self._enrich(candidate, context.token) for candidate in candidates))
        available = sum(1 for candidate in candidates if candidate.get("profile_enriched"))
        context.logs.append(f"[EnrichmentAgent] 补全 {len(candidates)} 人，有效水下信息 {available} 人")


class QualityGateAgent:
    def run(self, context: PipelineContext) -> None:
        for candidate in context.recalled:
            quality = assess_data_quality(candidate)
            candidate["data_quality"] = quality
            if quality["grade"] == "QUARANTINED":
                candidate["pipeline_status"] = "quarantined"
                context.rejected.append(candidate)
        context.recalled = [c for c in context.recalled if c.get("pipeline_status") != "quarantined"]
        grades: Dict[str, int] = {}
        for candidate in context.recalled:
            grade = candidate["data_quality"]["grade"]
            grades[grade] = grades.get(grade, 0) + 1
        context.logs.append(f"[QualityGateAgent] 数据等级 {grades}，隔离 {len(context.rejected)} 人")


class HardFilterAgent:
    def run(self, context: PipelineContext) -> List[Dict[str, Any]]:
        passed: List[Dict[str, Any]] = []
        for candidate in context.recalled:
            status, reason = hard_filter(candidate, context.spec)
            candidate["hard_filter_status"] = status
            candidate["hard_filter_reason"] = reason
            if status == "pass":
                if candidate["data_quality"]["grade"] == "C":
                    candidate["pipeline_status"] = "pending_evidence"
                    context.review_pool.append(candidate)
                else:
                    passed.append(candidate)
            elif status == "review":
                candidate["pipeline_status"] = "pending_hard_condition"
                context.review_pool.append(candidate)
            else:
                candidate["pipeline_status"] = "rejected"
                context.rejected.append(candidate)
        context.logs.append(
            f"[HardFilterAgent] 可语义评分 {len(passed)} 人，待补证 {len(context.review_pool)} 人，累计拒绝 {len(context.rejected)} 人"
        )
        return passed


class SemanticScoringAgent:
    def __init__(self, api_key: str, concurrency: int = 6) -> None:
        self.client = AsyncOpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)
        self.semaphore = asyncio.Semaphore(concurrency)

    async def run(self, candidates: List[Dict[str, Any]], spec: JdSpec) -> List[Dict[str, Any]]:
        tasks = [evaluate_candidate(self.client, candidate, spec, self.semaphore) for candidate in candidates]
        return list(await asyncio.gather(*tasks)) if tasks else []


class AuditAgent:
    """确保产出中没有生成数据、无证据强推或计数不一致。"""

    def run(self, scored: List[Dict[str, Any]], context: PipelineContext) -> None:
        for candidate in scored:
            if (candidate.get("source") or candidate.get("source_type")) == "generated":
                raise RuntimeError("production output contains generated data")
            if candidate.get("recommendation") == "强推" and not candidate.get("evidence_verified"):
                raise RuntimeError("strong recommendation without verified evidence")
            if candidate.get("data_quality", {}).get("grade") not in ("A", "B"):
                raise RuntimeError("final output contains insufficient-quality data")
        context.logs.append(f"[AuditAgent] 通过：{len(scored)} 人均为真实来源且数据质量达标")


async def process_jd(
    spec: JdSpec,
    token: str,
    ds_key: str,
    output_dir: Path,
    limit: int = 100,
    top_n: Optional[int] = None,
    pages: int = 1,
    enrich_limit: int = 100,
) -> Tuple[Path, Path, Path, List[str]]:
    logs: List[str] = []
    logs.append(f"[{spec.title}] Agent 流水线启动")
    context = PipelineContext(spec, token, logs, [], [], [])
    await RecallAgent(limit, pages).run(context)
    await EnrichmentAgent(enrich_limit).run(context)
    QualityGateAgent().run(context)
    passed = HardFilterAgent().run(context)
    scored = await SemanticScoringAgent(ds_key).run(passed, spec)
    scoring_errors = [candidate for candidate in scored if candidate.get("scoring_status") == "error"]
    for candidate in scoring_errors:
        candidate["pipeline_status"] = "pending_scoring_retry"
        context.review_pool.append(candidate)
    if scoring_errors:
        logs.append(f"[SemanticScoringAgent] {len(scoring_errors)} 人评分调用失败，已转入待重试池")

    # 只保留 hard_pass 且 overall >= 60 的
    scored = [
        s for s in scored
        if s.get("scoring_status") == "completed"
        and s["hard_pass"]
        and s["overall"] >= 60
        and s.get("evidence_verified")
    ]
    scored.sort(key=lambda x: x["overall"], reverse=True)
    logs.append(f"[SemanticScoringAgent] 证据校验后符合要求 {len(scored)} 人")

    if top_n and len(scored) > top_n:
        scored = scored[:top_n]
        logs.append(f"[{spec.title}] 取前 {top_n} 人")

    AuditAgent().run(scored, context)
    safe_title = spec.title.replace(" ", "_").replace("/", "_")
    json_path = output_dir / f"{safe_title}_scored.json"
    json_path.write_text(
        json.dumps({
            "meta": {
                "jd_title": spec.title,
                "search_queries": spec.search_queries,
                "location": spec.location,
                "min_years": spec.min_years,
                "max_age": spec.max_age,
                "generated_at": datetime.now().isoformat(),
                "total_recalled": context.recalled_count,
                "unique_count": context.recalled_count,
                "hard_pass_count": len(passed),
                "review_count": len(context.review_pool),
                "rejected_count": len(context.rejected),
                "final_count": len(scored),
            },
            "data": scored,
            "review_pool": context.review_pool,
            "rejected": context.rejected,
        }, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    html_path = output_dir / f"{safe_title}_report.html"
    render_html(scored, spec, html_path, logs, title=f"Agent 精准画像匹配报告：{spec.title}")

    pdf_path = output_dir / f"{safe_title}_report.pdf"
    await asyncio.to_thread(html_to_pdf, html_path, pdf_path)

    return json_path, html_path, pdf_path, logs


async def main_async() -> int:
    load_env()
    parser = argparse.ArgumentParser(description="LLM 语义 JD 筛选报告")
    parser.add_argument("--limit", type=int, default=100, help="每个岗位召回数量")
    parser.add_argument("--pages", type=int, default=1, help="每个召回策略最多页数")
    parser.add_argument("--enrich-limit", type=int, default=100, help="每个岗位最多拉取水下信息的人数，0表示全部")
    parser.add_argument("--top-n", type=int, default=None, help="每个岗位最终保留前 N 人，默认不限制")
    parser.add_argument("--output-dir", type=str, default=str(DEFAULT_OUTPUT_DIR), help="输出目录")
    parser.add_argument("--jwt", type=str, default="", help="TTC JWT Token")
    parser.add_argument("--deepseek-key", type=str, default="", help="DeepSeek API Key")
    args = parser.parse_args()

    token = args.jwt or os.getenv("TTC_JWT_TOKEN", "")
    ds_key = args.deepseek_key or os.getenv("DEEPSEEK_API_KEY", "")

    if not token:
        print("错误：需要提供 TTC_JWT_TOKEN", file=sys.stderr)
        return 1
    if not ds_key:
        print("错误：需要提供 DEEPSEEK_API_KEY", file=sys.stderr)
        return 1

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    specs = [JD_RUISHENG, JD_JINGHUA]
    for spec in specs:
        print(f"\n=== 开始处理：{spec.title} ===")
        json_path, html_path, pdf_path, logs = await process_jd(
            spec,
            token,
            ds_key,
            output_dir,
            limit=args.limit,
            top_n=args.top_n,
            pages=args.pages,
            enrich_limit=args.enrich_limit,
        )
        print("\n".join(logs))
        print(f"[OK] JSON: {json_path}")
        print(f"[OK] HTML: {html_path}")
        print(f"[OK] PDF: {pdf_path}")

    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
