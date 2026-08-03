#!/usr/bin/env python3
"""
全链路人才筛选评分报告生成。

流程：
1. 同时从本地 Source MySQL 和 TTC TalentStore API（云数据库）拉取候选人。
2. 筛选：年龄 < 35，排除大学/研究院/高校背景。
3. 评分：大厂/知名互联网公司背景权重加分，AI 产品经验、年限、技能匹配。
4. 生成 PDF：保留完整简历原文，附带 PDF 内部锚点链接，可点击跳转。
"""

import argparse
import asyncio
import html as html_lib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from openai import AsyncOpenAI
from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
DEFAULT_OUTPUT_DIR = DATA_DIR / "full_pipeline"

SCORE_THRESHOLD = 60.0
TARGET_COUNT = 50

TTC_API_BASE = "https://api.ttcadvisory.com"
TTC_WEB_BASE = "https://app.ttcadvisory.com"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

# 大厂/知名互联网公司/投资机构
INTERNET_BIG_NAMES = [
    "蚂蚁集团", "阿里巴巴", "阿里", "腾讯", "字节跳动", "字节", "美团", "拼多多",
    "京东", "百度", "快手", "滴滴", "小米", "OPPO", "vivo", "华为", "荣耀",
    "B站", "哔哩哔哩", "小红书", "知乎", "虎扑", "贝壳找房", "Boss直聘", "智联招聘",
    "Amazon", "Google", "微软", "Apple", "Meta", "Facebook", "Netflix", "Uber",
    "Airbnb", "Shopee", "Grab", "PayPal", "Stripe", "LinkedIn", "Twitter", "Snap",
    "旷视", "商汤", "科大讯飞", "大疆", "蔚来", "小鹏", "理想", "比亚迪",
    "红杉", "IDG", "启明创投", "高瓴", "中金公司", "摩根士丹利", "高盛",
]

KNOWN_COMPANY_NAMES = [
    "宁德时代", "海尔", "美的", "格力", "联想", "中兴", "比亚迪", "大疆", "富士康",
    "中国平安", "招商银行", "工商银行", "建设银行", "中国移动", "中国电信",
    "携程", "去哪儿", "得物", "唯品会", "爱奇艺", "网易", "新浪", "58同城", "同程",
    "IBM", "Oracle", "SAP", "Cisco", "Intel", "NVIDIA", "Adobe", "Salesforce",
]

SEARCH_QUERIES = [
    "AI产品经理", "B端AI产品经理", "AI Agent产品经理", "企业级大模型产品经理",
    "制造业AI产品经理", "用户产品经理", "C端产品经理", "用户增长产品经理",
    "用户策略产品经理", "用户体验产品经理",
]

RUISHENG_DIMENSIONS = {
    "AI/Agent产品能力": (0.25, ["ai", "人工智能", "大模型", "llm", "agent", "rag", "function calling", "工具调用", "知识库", "多模态"]),
    "B端/企业级经验": (0.20, ["b端", "tob", "to b", "企业级", "saas", "erp", "crm", "oa", "采购", "人力", "流程自动化"]),
    "产品交付与0到1": (0.15, ["prd", "原型", "产品规划", "产品定义", "从0到1", "0到1", "流程设计", "验收标准"]),
    "工业/制造业背景": (0.10, ["工业", "制造", "工厂", "生产", "供应链", "智能硬件", "iot", "物联网"]),
}

JINGHUA_DIMENSIONS = {
    "C端产品经验": (0.20, ["c端", "toc", "to c", "用户产品", "app", "小程序", "消费者", "社区", "内容产品"]),
    "用户体验/策略/增长": (0.25, ["用户体验", "用户策略", "用户增长", "用户洞察", "交互", "留存", "转化", "漏斗", "a/b", "ab测试"]),
    "数据与Bad Case迭代": (0.10, ["数据分析", "bad case", "用户反馈", "实验", "sql", "指标", "迭代"]),
    "隐私/安全场景": (0.05, ["隐私", "安全", "数据安全", "密态", "密码学", "可信计算"]),
}

# 大学/研究院/高校关键字，命中则直接过滤
ACADEMIC_KEYWORDS = [
    "大学", "研究院", "研究所", "中科院", "中国科学院", "工程院", "学院",
    "复旦", "浙大", "北京大学", "清华大学", "上海交大", "上海交通大学",
    "中科大", "中国科学技术大学", "南京大学", "武汉大学", "华中科技大学",
    "哈尔滨工业大学", "哈工大", "西安电子科技大学", "电子科技大学", "北邮", "北京邮电大学",
]


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
        Path.home() / ".ttc" / "mysql.env",
        Path.home() / ".ttc" / "ttc_jwt.env",
        Path.home() / ".ttc" / "deepseek.env",
    ]:
        for k, v in _parse_env_file(path).items():
            os.environ.setdefault(k, v)


def get_mysql_connection():
    import pymysql

    host = os.getenv("TTC_MYSQL_HOST") or os.getenv("TTC_SOURCE_TALENT_MYSQL_HOST")
    port = int(os.getenv("TTC_MYSQL_PORT") or os.getenv("TTC_SOURCE_TALENT_MYSQL_PORT", "3306"))
    user = os.getenv("TTC_MYSQL_USER") or os.getenv("TTC_SOURCE_TALENT_MYSQL_USER")
    password = os.getenv("TTC_MYSQL_PASSWORD") or os.getenv("TTC_SOURCE_TALENT_MYSQL_PASSWORD")
    database = os.getenv("TTC_MYSQL_DATABASE") or os.getenv("TTC_SOURCE_TALENT_MYSQL_DATABASE")
    if not all([host, user, password, database]):
        raise RuntimeError("MySQL 配置不完整，请检查 ~/.ttc/mysql.env 或环境变量 TTC_MYSQL_*")
    return pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=8,
        read_timeout=20,
    )


def query_source_db(keyword: str, limit: int = 100) -> List[Dict[str, Any]]:
    terms = [term for term in re.split(r"\s+", keyword.strip()) if term]
    if not terms:
        raise ValueError("搜索关键词不能为空")
    term_clause = """
        (name LIKE %s OR raw_text LIKE %s OR current_role LIKE %s
         OR current_company LIKE %s OR JSON_SEARCH(skills, 'one', %s) IS NOT NULL)
    """
    sql = f"""
        SELECT id, name, raw_text, skills, years_experience, education,
               current_role, current_company, source, updated_at
        FROM candidates
        WHERE {' AND '.join(term_clause for _ in terms)}
        ORDER BY updated_at DESC
        LIMIT %s
    """
    params: List[Any] = []
    for term in terms:
        like = f"%{term}%"
        params.extend([like, like, like, like, like])
    params.append(limit)
    conn = get_mysql_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    finally:
        conn.close()

    for row in rows:
        skills = row.get("skills") or []
        if isinstance(skills, str):
            try:
                skills = json.loads(skills)
            except Exception:
                skills = [s.strip() for s in skills.replace(",", "，").split("，") if s.strip()]
        row["skills"] = skills if isinstance(skills, list) else []
        row["source_type"] = "source_mysql"
        source_value = str(row.get("source") or "")
        row["link"] = source_value if source_value.startswith(("http://", "https://")) else ""
        row["location"] = "未知（本地库无 base 地字段）"
        row["source_payload"] = dict(row)
    return rows


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


def search_ttc_talent(keyword: str, token: str, limit: int = 100) -> List[Dict[str, Any]]:
    url = f"{TTC_API_BASE}/api/talent_store/v1/search"
    payload = {
        "keyword": keyword,
        "page_size": limit,
        "current_page": 1,
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
    resp = requests.post(url, headers=_ttc_headers(token), json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    items = (data.get("data", {}).get("person_leads_items") or []) if isinstance(data, dict) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        item["source_payload"] = dict(item)
        item["source_type"] = "ttc_api"
        item["link"] = f"{TTC_WEB_BASE}/app/talent/{item.get('person_leads_id', '')}"
        item["location"] = item.get("locations_display") or item.get("locations") or "未知"
        item["name"] = (item.get("cn_name") or item.get("name") or "（姓名未提供）").strip()
        item["age"] = item.get("age") or 0

        # 从工作经历中提取当前职位和公司
        work = item.get("work_information") or []
        latest_work = work[0] if work else {}
        # 如果 company 和 job_title 内容完全相同（数据录入问题），尝试用 job_title 作为职位，公司留空
        raw_company = latest_work.get("company") or latest_work.get("formatted_company") or ""
        raw_role = item.get("job_title") or latest_work.get("job_title") or ""
        if raw_company and raw_role and raw_company == raw_role and len(work) >= 2:
            # 用第二段工作经历作为公司参考
            raw_company = work[1].get("company") or work[1].get("formatted_company") or ""
        item["current_company"] = raw_company
        item["current_role"] = raw_role
        # 工作年限：优先用 API 返回的累计年限，否则按工作经历求和
        years = item.get("years_experience")
        if not years and work:
            years = sum(w.get("duration_in_years", 0) for w in work)
        item["years_experience"] = round(float(years or 0), 1)

        # 教育背景
        edu_list = item.get("education_information") or []
        if edu_list:
            top_edu = edu_list[0]
            parts = [p for p in [top_edu.get('school'), top_edu.get('major'), top_edu.get('degree')] if p]
            item["education"] = "·".join(parts)
        else:
            item["education"] = item.get("degree") or ""

        item["skills"] = item.get("tags") or []

        # 构造完整简历原文
        work_lines = []
        for w in work:
            dur = round(float(w.get("duration_in_years", 0) or 0), 1)
            line = f"{w.get('company','')} | {w.get('job_title','')} | {dur}年 | {w.get('start_time','')} 至 {w.get('end_time','')}"
            work_lines.append(line)
        edu_lines = []
        for e in edu_list:
            line = f"{e.get('school','')} | {e.get('major','')} | {e.get('degree','')}"
            edu_lines.append(line)
        full_text = item.get("full_text")
        if isinstance(full_text, str) and full_text.strip():
            item["raw_text"] = full_text
        else:
            item["raw_text"] = "\n".join([
                f"姓名: {item['name']}",
                f"年龄: {item['age']}",
                f"当前职位: {item['current_role']}",
                f"当前公司: {item['current_company']}",
                f"工作地点: {item['location']}",
                f"工作年限: {item['years_experience']}年",
                "工作经历:\n" + "\n".join(work_lines),
                "教育背景:\n" + "\n".join(edu_lines),
                f"技能标签: {', '.join(item['skills'])}",
            ])
    return items


def fetch_candidates(keywords: List[str], limit: int, token: Optional[str], api_only: bool = False) -> Tuple[List[Dict[str, Any]], List[str]]:
    all_candidates: List[Dict[str, Any]] = []
    logs: List[str] = []

    # 1. 本地 Source MySQL
    if not api_only:
        for keyword in keywords:
            try:
                rows = query_source_db(keyword, limit)
                logs.append(f"[本地 Source MySQL] {keyword} 返回 {len(rows)} 条")
                all_candidates.extend(rows)
            except Exception as e:
                logs.append(f"[本地 Source MySQL] {keyword} 失败：{e}")
    else:
        logs.append("[本地 Source MySQL] 跳过（--api-only 模式，仅使用真实 TTC API 数据）")

    # 2. 云数据库 TTC API
    if token:
        for keyword in keywords:
            try:
                items = search_ttc_talent(keyword, token, limit)
                logs.append(f"[云数据库 TTC API] {keyword} 返回 {len(items)} 条")
                all_candidates.extend(items)
            except Exception as e:
                logs.append(f"[云数据库 TTC API] {keyword} 失败：{e}")
    else:
        logs.append("[云数据库 TTC API] 未配置 TTC_JWT_TOKEN，跳过")

    if api_only and not token:
        logs.append("[错误] --api-only 模式必须提供 TTC_JWT_TOKEN")
        return [], logs

    # 去重：云端优先使用稳定 person_leads_id，本地库使用本地 ID。
    seen = {}
    for c in all_candidates:
        if c.get("person_leads_id"):
            key = f"ttc:{c['person_leads_id']}"
        elif c.get("id"):
            key = f"local:{c['id']}"
        else:
            key = f"fallback:{c.get('name','')}|{c.get('current_company','')}|{c.get('current_role','')}"
        existing = seen.get(key)
        if existing is None or c.get("source_type") == "ttc_api":
            seen[key] = c
    unique = list(seen.values())

    return unique, logs


def infer_age(candidate: Dict[str, Any]) -> int:
    actual_age = candidate.get("age")
    if isinstance(actual_age, (int, float)) and 0 < actual_age < 100:
        candidate["age_source"] = "TTC云端实际字段"
        return int(actual_age)
    education = candidate.get("education", "")
    years = candidate.get("years_experience") or 0
    base = 22
    if "硕士" in education or "研究生" in education or "MBA" in education:
        base = 25
    elif "博士" in education:
        base = 28
    candidate["age_source"] = "根据学历与工作年限推断"
    return base + int(years)


def is_academic(company: str) -> bool:
    return any(kw in company for kw in ACADEMIC_KEYWORDS)


def bachelor_or_above(candidate: Dict[str, Any]) -> bool:
    text = f"{candidate.get('education', '')} {candidate.get('degree', '')}".lower()
    return any(degree in text for degree in ("本科", "学士", "硕士", "研究生", "博士", "mba"))


def has_product_experience(candidate: Dict[str, Any]) -> bool:
    text = f"{candidate.get('current_role', '')}\n{candidate.get('raw_text', '')}".lower()
    return "产品" in text or "product" in text


def company_tier(company: str) -> Tuple[int, str]:
    company_lower = str(company or "").lower()
    if any(name.lower() in company_lower for name in INTERNET_BIG_NAMES):
        return 100, "大厂/头部互联网"
    if any(name.lower() in company_lower for name in KNOWN_COMPANY_NAMES):
        return 82, "知名公司"
    if any(word in company_lower for word in ("互联网", "科技", "网络", "数字", "信息技术", "software", "technology")):
        return 68, "互联网/科技公司"
    return 50, "其他公司"


def recent_company_score(candidate: Dict[str, Any]) -> Tuple[int, str]:
    works = candidate.get("work_information") or []
    companies: List[str] = []
    for work in works[:3]:
        if isinstance(work, dict):
            company = str(work.get("company") or work.get("formatted_company") or "").strip()
            if company:
                companies.append(company)
    if not companies and candidate.get("current_company"):
        companies.append(str(candidate["current_company"]))
    scored = [(company_tier(company)[0], company_tier(company)[1], company) for company in companies]
    if not scored:
        return 40, "最近公司信息缺失"
    score, tier, company = max(scored, key=lambda item: item[0])
    return score, f"{company}（{tier}）"


def keyword_dimension(text: str, keywords: List[str]) -> int:
    hits = sum(1 for keyword in keywords if keyword.lower() in text)
    return min(100, 30 + hits * 14) if hits else 20


def location_score(location: str, target: str) -> int:
    if not location or "未知" in location:
        return 45
    return 100 if target in location else 35


def job_rule_score(candidate: Dict[str, Any], dimensions: Dict[str, Tuple[float, List[str]]], target_location: str) -> Tuple[float, Dict[str, int], Dict[str, float]]:
    text = "\n".join([
        str(candidate.get("raw_text") or ""),
        str(candidate.get("current_role") or ""),
        str(candidate.get("current_company") or ""),
        " ".join(str(skill) for skill in candidate.get("skills") or []),
    ]).lower()
    scores: Dict[str, int] = {}
    weights: Dict[str, float] = {}
    for name, (weight, keywords) in dimensions.items():
        scores[name] = keyword_dimension(text, keywords)
        weights[name] = weight
    company_value, _ = recent_company_score(candidate)
    years = float(candidate.get("years_experience") or 0)
    scores["最近大厂/互联网/知名公司"] = company_value
    weights["最近大厂/互联网/知名公司"] = 0.15
    scores["工作年限"] = 100 if 3 <= years <= 8 else 75 if years > 8 else 30
    weights["工作年限"] = 0.10
    scores["地点匹配"] = location_score(str(candidate.get("location") or ""), target_location)
    weights["地点匹配"] = 0.05
    overall = sum(scores[name] * weights[name] for name in scores)
    return round(overall, 1), scores, weights


def evaluate(candidate: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    company = candidate.get("current_company", "")
    years = candidate.get("years_experience") or 0
    age = infer_age(candidate)

    # 硬性筛选
    if age >= 35:
        return None
    if is_academic(company):
        return None
    source = str(candidate.get("source") or "")
    if source == "generated":
        return None
    ruisheng, ruisheng_dims, ruisheng_weights = job_rule_score(candidate, RUISHENG_DIMENSIONS, "深圳")
    jinghua, jinghua_dims, jinghua_weights = job_rule_score(candidate, JINGHUA_DIMENSIONS, "北京")
    if age > 32:
        jinghua = 0.0
    matched_jd = "瑞声科技-AI产品经理" if ruisheng >= jinghua else "荆华密算-用户产品经理"
    overall = max(ruisheng, jinghua)
    scores = ruisheng_dims if matched_jd.startswith("瑞声") else jinghua_dims
    weights = ruisheng_weights if matched_jd.startswith("瑞声") else jinghua_weights
    company_value, company_evidence = recent_company_score(candidate)

    return {
        **candidate,
        "age": age,
        "pre_score": round(overall, 1),
        "overall": round(overall, 1),
        "recommendation": "待LLM评析",
        "matched_jd": matched_jd,
        "ruisheng_rule_score": ruisheng,
        "jinghua_rule_score": jinghua,
        "company_background_score": company_value,
        "company_background_evidence": company_evidence,
        "dimension_scores": scores,
        "dimension_weights": weights,
    }


def build_llm_prompt(candidate: Dict[str, Any]) -> str:
    return f"""你是资深AI产品猎头。仅根据下面候选人资料评估两个岗位，禁止猜测或补写经历。

岗位A：瑞声科技-AI产品经理。核心画像：深圳，B端/企业级AI产品，3年以上，大模型、RAG、Function Calling、工具编排、AI Agent，从0到1和产品交付；工业/制造业加分。
岗位B：荆华密算-用户产品经理。核心画像：北京，32岁以内，3年以上，过往大厂背景，C端用户产品，用户体验/策略/增长，数据和bad case迭代；不强制AI经验。

共同硬条件已由程序检查：年龄<35，当前不在大学/研究院工作。
如果只有搜索摘要，必须在风险中说明“项目细节待核实”，不得因职称直接打高分。

返回严格JSON：
{{
  "ruisheng_score": 0-100,
  "jinghua_score": 0-100,
  "matched_jd": "瑞声科技-AI产品经理/荆华密算-用户产品经理",
  "analysis": "150字内的匹配结论",
  "strengths": ["明确匹配点"],
  "risks": ["不匹配点或待核实项"],
  "evidence_quotes": ["候选人资料中的原文短句"]
}}

候选人资料：
{candidate.get('raw_text', '')}
"""


async def llm_evaluate_candidate(client: AsyncOpenAI, candidate: Dict[str, Any], semaphore: asyncio.Semaphore) -> Dict[str, Any]:
    async with semaphore:
        try:
            response = await client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": "你是严谨的猎头评估员，只输出JSON，不得幻觉候选人经历。"},
                    {"role": "user", "content": build_llm_prompt(candidate)},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=900,
            )
            content = response.choices[0].message.content or "{}"
            result = json.loads(content)
            ruisheng_score = max(0.0, min(100.0, float(result.get("ruisheng_score", 0))))
            jinghua_score = max(0.0, min(100.0, float(result.get("jinghua_score", 0))))
            if candidate["age"] > 32:
                jinghua_score = 0.0
            matched_jd = "瑞声科技-AI产品经理" if ruisheng_score >= jinghua_score else "荆华密算-用户产品经理"
            llm_score = max(ruisheng_score, jinghua_score)
            years = float(candidate.get("years_experience") or 0)
            exp_score = 100 if years >= 3 else 30
            target_location = "深圳" if matched_jd.startswith("瑞声") else "北京"
            loc_score = location_score(str(candidate.get("location") or ""), target_location)
            overall = round(
                llm_score * 0.65
                + candidate["company_background_score"] * 0.15
                + exp_score * 0.05
                + loc_score * 0.05
                + candidate["pre_score"] * 0.10,
                1,
            )
            quotes = result.get("evidence_quotes") if isinstance(result.get("evidence_quotes"), list) else []
            raw_text = candidate.get("raw_text", "")
            verified_quotes = [str(quote) for quote in quotes if str(quote).strip() in raw_text]
            candidate.update({
                "llm_status": "completed",
                "llm_ruisheng_score": ruisheng_score,
                "llm_jinghua_score": jinghua_score,
                "llm_analysis": str(result.get("analysis") or ""),
                "llm_strengths": result.get("strengths") if isinstance(result.get("strengths"), list) else [],
                "llm_risks": result.get("risks") if isinstance(result.get("risks"), list) else [],
                "llm_evidence_quotes": verified_quotes,
                "matched_jd": matched_jd,
                "overall": overall,
                "score_formula": "LLM岗位适配65% + 最近公司背景15% + 画像规则分10% + 工作年限5% + 地点5%",
            })
        except Exception as exc:
            candidate.update({
                "llm_status": "error",
                "llm_error_type": type(exc).__name__,
                "llm_analysis": "LLM评析失败，暂使用规则预评分排序。",
                "llm_strengths": [],
                "llm_risks": ["LLM评析待重试"],
            })
        if candidate["overall"] >= 82:
            candidate["recommendation"] = "强推"
        elif candidate["overall"] >= 72:
            candidate["recommendation"] = "建议沟通"
        elif candidate["overall"] >= 60:
            candidate["recommendation"] = "备选"
        else:
            candidate["recommendation"] = "弱匹配"
        return candidate


async def llm_evaluate_all(candidates: List[Dict[str, Any]], api_key: str, concurrency: int = 8) -> List[Dict[str, Any]]:
    client = AsyncOpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)
    semaphore = asyncio.Semaphore(concurrency)
    return list(await asyncio.gather(*(llm_evaluate_candidate(client, candidate, semaphore) for candidate in candidates)))


def safe(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        value = ", ".join(str(item) for item in value)
    return html_lib.escape(str(value), quote=True)


def render_html(candidates: List[Dict[str, Any]], output: Path, logs: List[str], title: str = "AI 产品经理人才筛选评分报告") -> None:
    # 按得分排序
    ranked = sorted(candidates, key=lambda x: x["overall"], reverse=True)

    # 排名表
    rows = []
    for idx, c in enumerate(ranked, 1):
        anchor = f"candidate-{idx:03d}"
        dim_summary = "<br>".join(
            f"{k}: {v}（权重 {c['dimension_weights'][k]:.0%}）"
            for k, v in c["dimension_scores"].items()
        )
        rows.append({
            "rank": idx,
            "anchor": anchor,
            "name": c.get("name", ""),
            "company": c.get("current_company", ""),
            "role": c.get("current_role", ""),
            "age": c["age"],
            "exp": c.get("years_experience", ""),
            "location": c.get("location", "未知"),
            "education": c.get("education", ""),
            "skills": ", ".join(c.get("skills", [])[:6]),
            "overall": c["overall"],
            "recommendation": c["recommendation"],
            "matched_jd": c.get("matched_jd", ""),
            "company_evidence": c.get("company_background_evidence", ""),
            "source_type": c.get("source_type", ""),
            "link": c.get("link", ""),
            "dim_summary": dim_summary,
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
            <td>{safe(r['matched_jd'])}</td>
            <td>{safe(r['company_evidence'])}</td>
            <td>{jump_link} | {external_link}</td>
            <td>{r['dim_summary']}</td>
            </tr>"""
        )

    # 完整简历明细
    detail_sections = []
    for idx, c in enumerate(ranked, 1):
        anchor = f"candidate-{idx:03d}"
        raw_text = safe(c.get("raw_text") or c.get("profile_summary", {}).get("raw_resume_text", "")).replace("\n", "<br>")
        source_payload = safe(json.dumps(c.get("source_payload") or {}, ensure_ascii=False, indent=2, default=str))
        work_info = c.get("work_information") or []
        work_html = ""
        if work_info:
            work_html = "<ul>" + "".join(
                f"<li>{safe(w.get('company',''))} | {safe(w.get('job_title',''))} | {safe(w.get('duration',''))}</li>"
                for w in work_info
            ) + "</ul>"

        detail_sections.append(
            f"""<div class="detail" id="{anchor}">
            <h2>#{idx} {safe(c.get('name',''))} — {safe(c.get('current_company',''))} — 综合得分 {safe(c['overall'])}</h2>
            <p>
              <strong>当前职位：</strong>{safe(c.get('current_role',''))} |
              <strong>年限：</strong>{safe(c.get('years_experience',''))} 年 |
              <strong>年龄：</strong>{safe(c['age'])} 岁（{safe(c.get('age_source',''))}） |
              <strong>学历：</strong>{safe(c.get('education',''))} |
              <strong>地点：</strong>{safe(c.get('location','未知'))}
            </p>
            <p><strong>技能：</strong>{safe(', '.join(c.get('skills', [])))}</p>
            <p><strong>推荐：</strong>{safe(c['recommendation'])} | <strong>数据源：</strong>{safe(c.get('source_type',''))}</p>
            <p><strong>最匹配岗位：</strong>{safe(c.get('matched_jd',''))} | <strong>最近公司背景：</strong>{safe(c.get('company_background_evidence',''))}</p>
            <p><strong>LLM评析：</strong>{safe(c.get('llm_analysis',''))}</p>
            <p><strong>匹配优势：</strong>{safe(c.get('llm_strengths', []))}</p>
            <p><strong>风险/待核实：</strong>{safe(c.get('llm_risks', []))}</p>
            <p><strong>LLM岗位分：</strong>瑞声 {safe(c.get('llm_ruisheng_score','-'))} | 荆华 {safe(c.get('llm_jinghua_score','-'))}</p>
            <p><strong>线上链接：</strong> {f'<a href="{safe(c.get("link",""))}" target="_blank" rel="noopener noreferrer">{safe(c.get("link",""))}</a>' if c.get('link') else '无（本地库无线上链接）'}</p>
            <h3>维度得分</h3>
            <ul>{''.join(f"<li><strong>{safe(k)}</strong> (权重 {c['dimension_weights'][k]:.0%}): {safe(v)}</li>" for k, v in c['dimension_scores'].items())}</ul>
            <h3>工作经历</h3>
            {work_html or '<p>（本地库未提供工作经历明细）</p>'}
            <h3>完整简历原文</h3>
            <div class="raw">{raw_text}</div>
            <h3>API/本地库完整原始字段（未删减）</h3>
            <pre class="raw">{source_payload}</pre>
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
  thead {{ display: table-header-group; }}
  tr {{ break-inside: avoid; page-break-inside: avoid; }}
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
<div class="meta">筛选后 {len(ranked)} 人 · 生成时间 {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>
<div class="warning">
<strong>筛选规则：</strong>年龄严格 &lt; 35 岁；当前在大学/学院/研究院/研究所工作直接排除；总分=LLM岗位适配65%+最近公司背景15%+画像规则分10%+年限5%+地点5%。
</div>
<div class="logs"><strong>数据拉取日志：</strong><br>{logs_html}</div>

<h2>评分排名表</h2>
<div style="overflow-x:auto"><table>
<thead><tr>
  <th>排名</th><th>姓名</th><th>公司</th><th>职位</th><th>年龄</th><th>年限</th><th>地点</th><th>学历</th><th>技能</th><th>得分</th><th>推荐</th><th>最匹配JD</th><th>最近公司加分证据</th><th>链接</th><th>维度详情</th>
</tr></thead>
<tbody>{''.join(trs)}</tbody>
</table></div>

<h2>完整简历明细（保留原始信息，未解析筛选）</h2>
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
            landscape=True,
            margin={"top": "1cm", "right": "1cm", "bottom": "1cm", "left": "1cm"},
            print_background=True,
            display_header_footer=True,
            header_template='<div style="font-size:8px;color:#6c757d;width:100%;text-align:center;">两岗位 AI 产品经理 - LLM 评分报告</div>',
            footer_template='<div style="font-size:8px;color:#6c757d;width:100%;text-align:center;">Page <span class="pageNumber"></span> / <span class="totalPages"></span></div>',
        )
        browser.close()


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser(description="全链路人才筛选评分报告")
    parser.add_argument("--keyword", default="AI产品经理", help="搜索关键词")
    parser.add_argument("--limit", type=int, default=100, help="每个数据源拉取数量")
    parser.add_argument("--target-count", type=int, default=TARGET_COUNT, help="最终PDF候选人数")
    parser.add_argument("--llm-shortlist", type=int, default=100, help="送入LLM评析的规则预选人数")
    parser.add_argument("--api-only", action="store_true", help="仅使用 TTC API 真实数据，跳过本地 Source MySQL")
    parser.add_argument("--output-dir", type=str, default=str(DEFAULT_OUTPUT_DIR), help="输出目录")
    parser.add_argument("--jwt", type=str, default="", help="TTC JWT Token")
    args = parser.parse_args()

    token = args.jwt or os.getenv("TTC_JWT_TOKEN", "")
    deepseek_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not deepseek_key:
        print("错误：引入LLM评析需要 DEEPSEEK_API_KEY", file=sys.stderr)
        return 1
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    keywords = list(dict.fromkeys([args.keyword, *SEARCH_QUERIES]))
    print(f"[Pipeline] 开始拉取数据，召回策略：{len(keywords)} 组")
    if args.api_only:
        print("[Pipeline] 模式：仅使用 TTC API 真实数据")
    all_candidates, logs = fetch_candidates(keywords, args.limit, token, api_only=args.api_only)
    print("\n".join(logs))
    print(f"[Pipeline] 去重后共 {len(all_candidates)} 人")

    # 筛选 + 评分
    scored = []
    filtered_out = {"age": 0, "academic": 0, "experience": 0, "degree": 0, "role": 0, "generated": 0}
    for c in all_candidates:
        company = c.get("current_company", "")
        age = infer_age(c)
        if age >= 35:
            filtered_out["age"] += 1
            continue
        if is_academic(company):
            filtered_out["academic"] += 1
            continue
        if str(c.get("source") or "") == "generated":
            filtered_out["generated"] += 1
            continue
        if float(c.get("years_experience") or 0) < 3:
            filtered_out["experience"] += 1
            continue
        if not bachelor_or_above(c):
            filtered_out["degree"] += 1
            continue
        if not has_product_experience(c):
            filtered_out["role"] += 1
            continue
        result = evaluate(c)
        if not result:
            continue
        scored.append(result)

    logs.append(
        f"[硬筛] 年龄≥35 {filtered_out['age']}人；当前学术机构 {filtered_out['academic']}人；"
        f"年限<3 {filtered_out['experience']}人；学历不足/未知 {filtered_out['degree']}人；"
        f"无产品经历 {filtered_out['role']}人；生成测试数据 {filtered_out['generated']}人"
    )
    scored.sort(key=lambda item: item["pre_score"], reverse=True)
    shortlist = scored[: max(args.target_count, args.llm_shortlist)]
    logs.append(f"[规则预选] 硬筛通过 {len(scored)} 人，前 {len(shortlist)} 人进入LLM双JD评析")
    print(f"[Pipeline] 进入 LLM 评析 {len(shortlist)} 人")
    scored = asyncio.run(llm_evaluate_all(shortlist, deepseek_key))
    llm_errors = sum(1 for candidate in scored if candidate.get("llm_status") == "error")
    logs.append(f"[LLM评析] 完成 {len(scored) - llm_errors} 人，失败并降级使用规则分 {llm_errors} 人")

    # 按综合得分排序
    scored.sort(key=lambda x: x["overall"], reverse=True)

    if len(scored) == 0:
        logs.append("[输出] 无符合要求的候选人")
    elif len(scored) > args.target_count:
        scored = scored[:args.target_count]
        logs.append(f"[输出] 取LLM综合评分最高的前 {args.target_count} 人")

    # 保存 JSON
    json_path = output_dir / "full_pipeline_scored.json"
    json_path.write_text(
        json.dumps({
            "meta": {
                "keywords": keywords,
                "generated_at": datetime.now().isoformat(),
                "token_used": bool(token),
                "total_before_filter": len(all_candidates),
                "total_after_filter": len(scored),
            },
            "data": scored,
        }, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"[OK] JSON 已保存：{json_path}")

    # 生成 HTML/PDF
    html_path = output_dir / "full_pipeline_report.html"
    render_html(scored, html_path, logs)
    print(f"[OK] HTML 已保存：{html_path}")

    pdf_path = output_dir / "full_pipeline_report.pdf"
    try:
        html_to_pdf(html_path, pdf_path)
        print(f"[OK] PDF 已保存：{pdf_path}")
    except Exception as e:
        print(f"[WARN] PDF 生成失败：{e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
