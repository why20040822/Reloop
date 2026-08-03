from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from contextlib import closing
from datetime import UTC, datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import fitz
from fastapi import HTTPException, Query, Request
from fastapi.responses import FileResponse

from reloop.api.schemas import (
    CapturePayload,
    FeedbackPayload,
    FeishuReplyAckPayload,
    FeishuWebMessagePayload,
    IngestFilePayload,
    IngestTextPayload,
    LocalDownloadPayload,
    ReviewCorrections,
    ReviewRejectPayload,
    SearchPayload,
    TextPayload,
    UrlPayload,
)
from reloop.config import DATA_DIR, PROJECT_ROOT
from reloop.domain import jd_aligned
from reloop.domain.models import CandidateRecord, Education, WorkExperience
from reloop.ingestion.delivery import DeliveryStore
from reloop.ingestion.pipeline import _enqueue_for_delivery, ingest_file, ingest_text
from reloop.ingestion.review import _apply_corrections, review_detail, review_queue
from reloop.ingestion.review import approve_record as review_approve_record
from reloop.ingestion.review import reject_record as review_reject_record
from reloop.ingestion.search import add_feedback, list_feedback, search_candidates
from reloop.parsing.ocr import ocr_pdf
from reloop.parsing.unified_parser import _extract_education, _extract_experiences
from reloop.sinks.gmail import sync as gmail_sync

ROOT = PROJECT_ROOT
DB_PATH = DATA_DIR / "candidates.db"
MAX_TEXT = 600_000
MAX_FILE = 12 * 1024 * 1024


EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"(?<![\d])1[3-9]\d{9}(?![\d])")


def extract_phone(text: str) -> str:
    match = PHONE_RE.search(text)
    return match.group(0) if match else ""


def extract_email(text: str) -> str:
    match = EMAIL_RE.search(text)
    return match.group(0) if match else ""


class VisibleTextParser(HTMLParser):
    hidden = {"script", "style", "noscript", "svg", "template"}

    def __init__(self) -> None:
        super().__init__()
        self.depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in self.hidden:
            self.depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self.hidden and self.depth:
            self.depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.depth:
            self.parts.append(data)


def db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with closing(db()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                platform TEXT NOT NULL,
                source_url TEXT,
                source_type TEXT NOT NULL,
                title TEXT,
                location TEXT,
                explicit_age INTEGER,
                experience_years REAL,
                undergraduate_school TEXT,
                undergraduate_tier TEXT,
                current_company TEXT,
                current_role TEXT,
                phone TEXT NOT NULL DEFAULT '',
                email TEXT NOT NULL DEFAULT '',
                employment_status TEXT NOT NULL DEFAULT '',
                expected_salary TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                experiences_json TEXT NOT NULL DEFAULT '[]',
                education_json TEXT NOT NULL DEFAULT '{}',
                keywords_json TEXT NOT NULL DEFAULT '[]',
                hard_filter_reason TEXT NOT NULL DEFAULT '',
                consulting_evidence TEXT,
                inhouse_evidence TEXT,
                product_evidence TEXT,
                brand_evidence TEXT,
                channel_evidence TEXT,
                client_evidence TEXT,
                score INTEGER NOT NULL,
                jd_score REAL,
                jd_recommendation TEXT,
                jd_scores_json TEXT,
                recommendation TEXT NOT NULL,
                strengths_json TEXT NOT NULL,
                risks_json TEXT NOT NULL,
                raw_text TEXT NOT NULL,
                collected_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS feishu_web_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint TEXT NOT NULL UNIQUE,
                client_id TEXT NOT NULL DEFAULT 'default',
                chat_title TEXT NOT NULL DEFAULT '',
                sender TEXT NOT NULL DEFAULT '',
                text TEXT NOT NULL,
                url TEXT NOT NULL DEFAULT '',
                message_time TEXT NOT NULL DEFAULT '',
                page_title TEXT NOT NULL DEFAULT '',
                captured_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS feishu_web_replies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER NOT NULL,
                client_id TEXT NOT NULL DEFAULT 'default',
                chat_title TEXT NOT NULL DEFAULT '',
                reply_text TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(message_id) REFERENCES feishu_web_messages(id)
            )
            """
        )
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(candidates)").fetchall()}
        migrations = {
            "employment_status": "TEXT NOT NULL DEFAULT ''",
            "expected_salary": "TEXT NOT NULL DEFAULT ''",
            "summary": "TEXT NOT NULL DEFAULT ''",
            "experiences_json": "TEXT NOT NULL DEFAULT '[]'",
            "education_json": "TEXT NOT NULL DEFAULT '{}'",
            "keywords_json": "TEXT NOT NULL DEFAULT '[]'",
            "hard_filter_reason": "TEXT NOT NULL DEFAULT ''",
            "jd_score": "REAL",
            "jd_recommendation": "TEXT",
            "jd_scores_json": "TEXT",
            "phone": "TEXT NOT NULL DEFAULT ''",
            "email": "TEXT NOT NULL DEFAULT ''",
            "review_status": "TEXT NOT NULL DEFAULT 'pending'",
            "attachment_path": "TEXT",
        }
        for column, definition in migrations.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE candidates ADD COLUMN {column} {definition}")
        conn.commit()


def clean_text(value: str) -> str:
    value = unescape(value).replace("\u00a0", " ").replace("\u200b", "")
    lines: list[str] = []
    seen: set[str] = set()
    for raw in value.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line or line in seen:
            continue
        seen.add(line)
        lines.append(line)
    return "\n".join(lines)[:MAX_TEXT]


def detect_platform(url: str, explicit: str = "") -> str:
    if explicit:
        return explicit.strip()
    host = urllib.parse.urlparse(url).netloc.lower()
    mapping = {
        "zhipin.com": "BOSS直聘",
        "liepin.com": "猎聘",
        "maimai.cn": "脉脉",
        "linkedin.com": "LinkedIn",
        "51job.com": "前程无忧",
        "zhaopin.com": "智联招聘",
    }
    return next((label for domain, label in mapping.items() if domain in host), host or "本地导入")


def evidence(text: str, words: list[str], limit: int = 2) -> str:
    lines = text.splitlines()
    matches = [line for line in lines if any(word.lower() in line.lower() for word in words)]
    return " | ".join(matches[:limit])[:800]


def first_match(patterns: list[str], text: str, group: int = 1) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return match.group(group).strip()
    return ""


def infer_name(title: str, heading: str, text: str) -> str:
    stop = {
        "在线简历", "候选人", "求职者", "BOSS直聘", "猎聘", "脉脉", "个人简历",
        "能力简介", "工作经历", "教育背景", "项目经历", "个人技能", "北京", "上海", "深圳", "广州",
        "设置", "消息", "登录", "职位", "筛选", "推荐", "搜索", "前一个月", "后一个月",
    }
    candidates = [heading]
    titled_name = re.search(r"[】\]]\s*([\u4e00-\u9fff·]{2,6})(?:\s*[-_ ]?\s*\d+年)?(?:\.pdf)?$", title, re.I)
    resume_name = re.search(r"(?:个人简历|简历)[-_ ]*([\u4e00-\u9fff·]{2,6})(?:\.pdf)?$", title, re.I)
    leading_name = re.search(r"^([\u4e00-\u9fff·]{2,6})[-_](?=战略|品牌|产品|咨询|市场|运营)", title)
    for match in (titled_name, resume_name, leading_name):
        if match:
            candidates.append(match.group(1))
    for line in text.splitlines()[:20]:
        bilingual = re.search(r"(?:[A-Za-z][A-Za-z .'-]{2,40}\s+)([\u4e00-\u9fff·]{2,6})$", line)
        if bilingual:
            candidates.append(bilingual.group(1))
        candidates.append(line)
    candidates.extend(re.split(r"[-_|\s()]+", title))
    for item in candidates:
        item = re.sub(r"[男女]\s*\d{2}岁.*$", "", item).strip(" -_|:：")
        if item in stop:
            continue
        if re.fullmatch(r"[\u4e00-\u9fff·]{2,8}", item):
            return item
        if re.fullmatch(r"[A-Za-z][A-Za-z .'-]{2,30}", item):
            return item
    return "待识别候选人"


SCHOOLS_985 = ["复旦大学", "武汉大学", "中国人民大学", "清华大学", "北京大学", "上海交通大学", "浙江大学", "南京大学", "中山大学"]
SCHOOLS_211 = ["中央财经大学", "上海财经大学", "中南财经政法大学", "对外经济贸易大学", "中国传媒大学", "北京外国语大学"]


PERIOD_RE = re.compile(
    r"^(?:"
    r"(?:19|20)\d{2}(?:\.\d{1,2})?\s*[-–—至]\s*(?:至今|(?:19|20)\d{2}(?:\.\d{1,2})?)"
    r"|(?:19|20)\d{2}年\s*\d{1,2}月\s*[-–—至]\s*(?:至今|(?:19|20)\d{2}年\s*\d{1,2}月)"
    r"|(?:19|20)\d{2}[/\-]\d{1,2}\s*[-–—至]\s*(?:至今|(?:19|20)\d{2}[/\-]\d{1,2})"
    r"|(?:19|20)\d{2}\s*[-–—至]\s*(?:至今|(?:19|20)\d{2})"
    r")$"
)


def parse_boss_experiences(text: str) -> list[dict[str, Any]]:
    lines = text.splitlines()
    try:
        start = lines.index("工作经历") + 1
    except ValueError:
        return []
    end = next(
        (index for index in range(start, len(lines)) if lines[index] in {"教育经历", "项目经历", "志愿经历"}),
        len(lines),
    )
    section = lines[start:end]
    entries: list[dict[str, Any]] = []
    index = 0
    while index + 2 < len(section):
        first, second, third = section[index:index + 3]
        company = role = period = ""

        # Order: company / role / period
        if PERIOD_RE.match(third) and len(first) <= 100 and len(second) <= 60:
            company, role, period = first, second, third
        # Order: company / period / role
        elif PERIOD_RE.match(second) and len(first) <= 100 and len(third) <= 60:
            company, role, period = first, third, second

        if company and role and period:
            next_index = index + 3
            highlights: list[str] = []
            while next_index < len(section):
                if next_index + 2 < len(section) and PERIOD_RE.match(section[next_index + 2]):
                    break
                line = section[next_index]
                if len(line) >= 20 and not line.startswith("查看"):
                    highlights.append(line)
                next_index += 1
            entries.append({
                "company": company,
                "role": role,
                "period": period,
                "highlights": highlights[:6],
            })
            index = next_index
            continue
        index += 1
    return entries


def parse_boss_education(text: str) -> dict[str, str]:
    lines = text.splitlines()
    try:
        start = lines.index("教育经历") + 1
    except ValueError:
        return {}
    section = lines[start:start + 10]
    school = next((line for line in section if line.endswith(("大学", "学院"))), "")
    degree = next((line for line in section if line in {"本科", "硕士", "博士", "大专"}), "")
    tier = "985" if any("985" in line for line in section) else "211" if any("211" in line for line in section) else ""
    period = next((line for line in section if re.match(r"^(?:19|20)\d{2}\s*[-–—至]\s*(?:19|20)\d{2}$", line)), "")
    major = ""
    if school and school in section:
        pos = section.index(school)
        if pos + 1 < len(section) and section[pos + 1] not in {degree, period}:
            major = section[pos + 1]
    return {"school": school, "major": major, "degree": degree, "period": period, "tier": tier}


def parse_summary(text: str) -> str:
    lines = text.splitlines()
    stop = {"最近关注", "工作经历", "查看全部"}
    collected: list[str] = []
    for line in lines[:40]:
        if line in stop:
            if collected:
                break
            continue
        if len(line) >= 35:
            collected.append(line)
    return " ".join(collected[:3])[:1200]


def parse_candidate(payload: CapturePayload) -> dict[str, Any]:
    # 优先使用扩展传入的结构化分节数据；BOSS 页面噪声大，分节能显著提升解析质量。
    structured = payload.structured_data or {}
    sections = structured.get("sections") if isinstance(structured.get("sections"), list) else None
    if sections:
        text = clean_text("\n".join(f"{s.get('heading', '')}\n{s.get('text', '')}" for s in sections))
    else:
        text = clean_text(payload.text)
    explicit_age = first_match([
        r"(?:年龄[\s：:]*)([2-5]\d)(?:岁)?",
        r"(?:\b|[｜|,，;；\s])([2-5]\d)岁",
    ], text)
    years = first_match([
        r"(\d+(?:\.\d+)?)年(?:工作|经验)",
        r"工作(?:年限|经验)[\s：:]*(\d+(?:\.\d+)?)年",
        r"(?m)^(\d{1,2})年$",
    ], text)
    employment_status = first_match([
        r"(在职[-—–]考虑机会|在职[-—–]暂不考虑|离职[-—–]随时到岗|离职[-—–]正在找工作|考虑机会)"
    ], text)
    expected_salary = first_match([r"(\d{1,3}\s*-\s*\d{1,3}K)"], text)
    platform = detect_platform(payload.url, payload.platform)
    boss_native = platform == "BOSS直聘" or any(
        marker in text for marker in ("牛人最近7天沟通过的职位", "最近关注", "在职-考虑机会")
    )
    if boss_native:
        experiences = parse_boss_experiences(text)
        education = parse_boss_education(text)
    else:
        unified_exps, _ = _extract_experiences(text)
        experiences = [e.model_dump() for e in unified_exps]
        edu_record = _extract_education(text)
        education = edu_record.model_dump() if edu_record else {}
    locations = ["北京", "上海", "深圳", "广州", "杭州", "成都", "苏州", "南京"]
    location = next((city for city in locations if city in text[:3000]), "")
    school = education.get("school") or next((s for s in SCHOOLS_985 + SCHOOLS_211 if s in text), "")
    tier = (
        education.get("tier")
        or ("985" if school in SCHOOLS_985 else "211" if school in SCHOOLS_211 else "待核验")
    )

    consulting = evidence(text, ["罗兰贝格", "Strategy&", "思略特", "帕特侬", "Parthenon", "贝恩", "麦肯锡", "BCG", "普华永道", "德勤", "久谦", "沙利文", "咨询顾问", "管理咨询"])
    inhouse = evidence(text, ["宝洁", "联合利华", "百事", "玛氏", "欧莱雅", "可口可乐", "美团", "沃尔玛", "山姆", "盒马", "元气森林", "王小卤", "万科", "滴灌通", "零售", "品牌方"])
    product = evidence(text, ["产品定义", "产品创新", "产品体系", "产品能力", "菜单调整", "新品", "品类策略", "产品组合", "SKU", "pipeline", "爆品", "爆款"])
    brand = evidence(text, ["品牌定位", "品牌策略", "品牌焕新", "消费者洞察", "用户研究", "人群画像", "品牌增长", "品牌健康"])
    channel = evidence(text, ["渠道策略", "渠道增长", "GTM", "市场进入", "经销商", "即时零售", "全渠道"])
    client = evidence(text, ["创始人", "CEO", "总裁", "管理层", "客户沟通", "客户管理", "售前", "报价", "续约"])

    score = 0
    strengths: list[str] = []
    risks: list[str] = []
    if consulting:
        score += 20
        strengths.append("有咨询公司/咨询项目证据")
    else:
        risks.append("未识别到正式咨询经历")
    if inhouse:
        score += 18
        strengths.append("有消费或零售甲方证据")
    else:
        risks.append("甲方消费经历待验证")
    if consulting and inhouse:
        score += 10
        strengths.append("咨询＋甲方组合命中")
    if tier in {"985", "211"}:
        score += 10 if tier == "985" else 8
        strengths.append(f"本科院校命中 {tier}")
    else:
        risks.append("第一学历待核验")
    for item, label, points in [(product, "产品创新", 10), (brand, "品牌增长", 10), (channel, "渠道策略", 8), (client, "高层/客户沟通", 8)]:
        if item:
            score += points
            strengths.append(f"有{label}证据")
    if explicit_age:
        age = int(explicit_age)
        if 29 <= age <= 33:
            score += 6
            strengths.append("年龄位于 29–33 柔性区间")
        else:
            risks.append("年龄不在目标柔性区间，仅作人工参考")
    else:
        risks.append("年龄未明确公开，不做自动淘汰")
    score = min(score, 100)
    hard_filter_reason = ""
    if explicit_age and int(explicit_age) > 33:
        score = 0
        hard_filter_reason = "年龄超过33岁"
        risks.insert(0, "年龄超过33岁：按当前硬筛规则总分直接归零")
        recommendation = "不符合年龄硬性要求"
    else:
        recommendation = "强推" if score >= 85 else "建议沟通" if score >= 70 else "备选/需补证" if score >= 50 else "信息不足"

    keyword_pool = [
        "战略规划", "商业分析", "行业研究", "投资研究", "战略投资", "品牌定位",
        "品牌增长", "产品创新", "渠道策略", "新业务孵化", "投后管理", "投后孵化",
        "消费者洞察", "尽职调查", "估值建模", "跨部门协同", "AI工作流",
    ]
    keywords = [keyword for keyword in keyword_pool if keyword in text]

    # JD 对齐评分（启承资本画像）
    jd = jd_aligned.evaluate(text)

    return {
        "name": infer_name(payload.title, payload.heading, text),
        "phone": extract_phone(text),
        "email": extract_email(text),
        "platform": platform,
        "source_url": payload.url,
        "source_type": payload.source_type,
        "title": payload.title,
        "location": location,
        "explicit_age": int(explicit_age) if explicit_age else None,
        "experience_years": float(years) if years else None,
        "undergraduate_school": school,
        "undergraduate_tier": tier,
        "current_company": experiences[0]["company"] if experiences else "",
        "current_role": experiences[0]["role"] if experiences else "",
        "employment_status": employment_status,
        "expected_salary": expected_salary,
        "summary": parse_summary(text),
        "experiences": experiences,
        "education": education,
        "keywords": keywords,
        "hard_filter_reason": hard_filter_reason,
        "consulting_evidence": consulting,
        "inhouse_evidence": inhouse,
        "product_evidence": product,
        "brand_evidence": brand,
        "channel_evidence": channel,
        "client_evidence": client,
        "score": score,
        "jd_score": jd.overall,
        "jd_recommendation": jd.recommendation,
        "jd_scores": jd.scores,
        "recommendation": recommendation,
        "strengths": strengths,
        "risks": risks,
        "raw_text": text,
    }


def _legacy_record_to_canonical(
    parsed: dict[str, Any],
    payload: CapturePayload,
    attachment_path: str | None,
) -> CandidateRecord:
    """Convert the legacy response shape before committing the outbox job."""

    education = parsed.get("education") or {}
    experiences = parsed.get("experiences") or []
    return CandidateRecord(
        name=parsed.get("name") or None,
        phone=parsed.get("phone") or None,
        email=parsed.get("email") or None,
        current_company=parsed.get("current_company") or None,
        current_title=parsed.get("current_role") or None,
        current_location=parsed.get("location") or None,
        employment_status=parsed.get("employment_status") or None,
        expected_salary=parsed.get("expected_salary") or None,
        school=parsed.get("undergraduate_school") or None,
        education=Education(**education) if isinstance(education, dict) and education else None,
        work_experiences=[WorkExperience(**item) for item in experiences if isinstance(item, dict)],
        raw_text=parsed.get("raw_text") or "",
        source_platform=parsed.get("platform") or payload.platform or "legacy_api",
        source_url=parsed.get("source_url") or payload.url or None,
        source_type=parsed.get("source_type") or payload.source_type or "legacy_api",
        captured_at=payload.captured_at,
        original_attachment_path=attachment_path,
    )


def save_candidate(payload: CapturePayload, attachment_path: str | None = None) -> dict[str, Any]:
    record = parse_candidate(payload)
    canonical = _legacy_record_to_canonical(record, payload, attachment_path)
    _enqueue_for_delivery(canonical, canonical.fingerprint())
    stable = (
        f"url|{record['source_url']}"
        if record["source_url"]
        else f"text|{record['name']}|{record['raw_text'][:3000]}"
    )
    fingerprint = hashlib.sha256(stable.encode("utf-8")).hexdigest()
    now = datetime.now(UTC).isoformat()
    columns = [
        "fingerprint", "name", "phone", "email", "platform", "source_url", "source_type", "title", "location",
        "explicit_age", "experience_years", "undergraduate_school", "undergraduate_tier",
        "current_company", "current_role", "employment_status", "expected_salary", "summary",
        "experiences_json", "education_json", "keywords_json", "hard_filter_reason",
        "consulting_evidence", "inhouse_evidence",
        "product_evidence", "brand_evidence", "channel_evidence", "client_evidence", "score",
        "jd_score", "jd_recommendation", "jd_scores_json",
        "recommendation", "strengths_json", "risks_json", "raw_text", "review_status", "attachment_path",
        "collected_at", "updated_at",
    ]
    values = [
        fingerprint, record["name"], record["phone"], record["email"], record["platform"], record["source_url"], record["source_type"],
        record["title"], record["location"], record["explicit_age"], record["experience_years"],
        record["undergraduate_school"], record["undergraduate_tier"], record["current_company"],
        record["current_role"], record["employment_status"], record["expected_salary"], record["summary"],
        json.dumps(record["experiences"], ensure_ascii=False),
        json.dumps(record["education"], ensure_ascii=False),
        json.dumps(record["keywords"], ensure_ascii=False),
        record["hard_filter_reason"], record["consulting_evidence"], record["inhouse_evidence"],
        record["product_evidence"], record["brand_evidence"], record["channel_evidence"],
        record["client_evidence"], record["score"], record["jd_score"], record["jd_recommendation"],
        json.dumps(record["jd_scores"], ensure_ascii=False),
        record["recommendation"],
        json.dumps(record["strengths"], ensure_ascii=False), json.dumps(record["risks"], ensure_ascii=False),
        record["raw_text"], "pending", attachment_path,
        payload.captured_at or now, now,
    ]
    with closing(db()) as conn:
        conn.execute(
            f"INSERT INTO candidates ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)}) "
            "ON CONFLICT(fingerprint) DO UPDATE SET updated_at=excluded.updated_at, name=excluded.name, "
            "phone=excluded.phone, email=excluded.email, "
            "location=excluded.location, explicit_age=excluded.explicit_age, experience_years=excluded.experience_years, "
            "undergraduate_school=excluded.undergraduate_school, undergraduate_tier=excluded.undergraduate_tier, "
            "current_company=excluded.current_company, current_role=excluded.current_role, "
            "employment_status=excluded.employment_status, expected_salary=excluded.expected_salary, summary=excluded.summary, "
            "experiences_json=excluded.experiences_json, education_json=excluded.education_json, "
            "keywords_json=excluded.keywords_json, hard_filter_reason=excluded.hard_filter_reason, "
            "score=excluded.score, jd_score=excluded.jd_score, jd_recommendation=excluded.jd_recommendation, "
            "jd_scores_json=excluded.jd_scores_json, recommendation=excluded.recommendation, "
            "strengths_json=excluded.strengths_json, risks_json=excluded.risks_json, "
            "review_status=excluded.review_status, attachment_path=excluded.attachment_path",
            values,
        )
        conn.commit()
        row = conn.execute("SELECT * FROM candidates WHERE fingerprint=?", (fingerprint,)).fetchone()
    return row_to_dict(row)


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["strengths"] = json.loads(item.pop("strengths_json"))
    item["risks"] = json.loads(item.pop("risks_json"))
    item["experiences"] = json.loads(item.pop("experiences_json", "[]"))
    item["education"] = json.loads(item.pop("education_json", "{}"))
    item["keywords"] = json.loads(item.pop("keywords_json", "[]"))
    item["jd_scores"] = json.loads(item.pop("jd_scores_json") or "{}")
    return item


def reprocess_existing() -> None:
    with closing(db()) as conn:
        rows = conn.execute("SELECT * FROM candidates").fetchall()
        for row in rows:
            record = parse_candidate(CapturePayload(
                url=row["source_url"] or "",
                title=row["title"] or "",
                text=row["raw_text"],
                platform=row["platform"],
                source_type=row["source_type"],
                captured_at=row["collected_at"],
            ))
            conn.execute(
                """
                UPDATE candidates SET
                    name=?, phone=?, email=?, location=?, explicit_age=?, experience_years=?,
                    undergraduate_school=?, undergraduate_tier=?, current_company=?, current_role=?,
                    employment_status=?, expected_salary=?, summary=?, experiences_json=?,
                    education_json=?, keywords_json=?, hard_filter_reason=?,
                    consulting_evidence=?, inhouse_evidence=?, product_evidence=?, brand_evidence=?,
                    channel_evidence=?, client_evidence=?, score=?, jd_score=?, jd_recommendation=?,
                    jd_scores_json=?, recommendation=?, strengths_json=?, risks_json=?, updated_at=?
                WHERE id=?
                """,
                (
                    record["name"], record["phone"], record["email"], record["location"], record["explicit_age"], record["experience_years"],
                    record["undergraduate_school"], record["undergraduate_tier"],
                    record["current_company"], record["current_role"], record["employment_status"],
                    record["expected_salary"], record["summary"],
                    json.dumps(record["experiences"], ensure_ascii=False),
                    json.dumps(record["education"], ensure_ascii=False),
                    json.dumps(record["keywords"], ensure_ascii=False),
                    record["hard_filter_reason"], record["consulting_evidence"],
                    record["inhouse_evidence"], record["product_evidence"], record["brand_evidence"],
                    record["channel_evidence"], record["client_evidence"], record["score"],
                    record["jd_score"], record["jd_recommendation"],
                    json.dumps(record["jd_scores"], ensure_ascii=False),
                    record["recommendation"], json.dumps(record["strengths"], ensure_ascii=False),
                    json.dumps(record["risks"], ensure_ascii=False), datetime.now(UTC).isoformat(),
                    row["id"],
                ),
            )
        conn.commit()


def _blocked_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return any((
        address.is_private,
        address.is_loopback,
        address.is_link_local,
        address.is_reserved,
        address.is_multicast,
        address.is_unspecified,
        not address.is_global,
    ))


def validate_public_url(value: str) -> str:
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(400, "请提供有效的 http/https 公开链接")
    if parsed.username or parsed.password:
        raise HTTPException(400, "链接不能包含用户名或密码")
    try:
        port = parsed.port
    except ValueError as exc:
        raise HTTPException(400, "链接端口无效") from exc
    if port not in {None, 80, 443}:
        raise HTTPException(400, "只允许 HTTP/HTTPS 默认端口")
    host = (parsed.hostname or "").rstrip(".").lower()
    if not host or host == "localhost" or host.endswith(".local") or _blocked_ip(host):
        raise HTTPException(400, "不允许访问本地或内网地址")
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise HTTPException(400, "链接域名无法解析") from exc
    if not addresses or any(_blocked_ip(address) for address in addresses):
        raise HTTPException(400, "不允许访问本地或内网地址")
    return value


class _PublicRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Validate every redirect target instead of trusting the first URL."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ):
        validate_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def row_to_feishu_message(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def row_to_feishu_reply(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def build_feishu_reply(payload: FeishuWebMessagePayload) -> str:
    """生成给飞书网页脚本回填的保守草稿。

    这里不调用外部模型，先用本地规则做招聘场景的安全默认回复：
    - 有简历/候选人意图：提示已收到，并给本地系统入口；
    - 含候选人材料：尝试解析入库后给评分摘要；
    - 其他消息：默认不生成，避免打扰群聊。
    """
    text = clean_text(payload.text)
    intent_words = ["简历", "候选人", "boss", "BOSS", "猎聘", "面试", "推荐", "帮我看", "评估", "JD", "岗位"]
    if not any(word in text for word in intent_words):
        return ""

    candidate = None
    if len(text) >= 80 and any(word in text for word in ["工作经历", "教育经历", "战略", "品牌", "咨询", "投后", "消费"]):
        try:
            candidate = save_candidate(CapturePayload(
                url=payload.url,
                title=payload.page_title or payload.chat_title or "飞书网页消息",
                text=text,
                platform="飞书网页",
                source_type="feishu_web_message",
                captured_at=payload.captured_at,
            ))
        except Exception:
            candidate = None

    if candidate:
        strengths = "；".join(candidate.get("strengths", [])[:3]) or "已提取基础画像，建议打开本地系统看证据"
        risks = "；".join(candidate.get("risks", [])[:2]) or "暂无明显风险"
        return (
            f"已读取并入库这份候选人资料：{candidate['name']}。\n"
            f"本地评分：{candidate['score']}，JD对齐：{candidate.get('jd_score')}\n"
            f"推荐结论：{candidate.get('jd_recommendation') or candidate.get('recommendation')}\n"
            f"主要证据：{strengths}\n"
            f"待验证：{risks}\n"
            "我建议先作为可沟通候选人进入人工复核。"
        )

    return (
        "收到，我先把这条候选人/简历相关信息记录到本地系统了。"
        "如果你把完整简历或 BOSS 页面内容发出来，我可以继续按启承资本画像做打分和面试优先级。"
    )


def save_feishu_web_message(payload: FeishuWebMessagePayload) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    text = clean_text(payload.text)
    stable = "|".join([
        payload.client_id or "default",
        payload.chat_title,
        payload.sender,
        payload.message_time,
        text[:2000],
    ])
    fingerprint = hashlib.sha256(stable.encode("utf-8")).hexdigest()
    with closing(db()) as conn:
        conn.execute(
            """
            INSERT INTO feishu_web_messages (
                fingerprint, client_id, chat_title, sender, text, url,
                message_time, page_title, captured_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(fingerprint) DO UPDATE SET captured_at=excluded.captured_at
            """,
            (
                fingerprint,
                payload.client_id or "default",
                payload.chat_title,
                payload.sender,
                text,
                payload.url,
                payload.message_time,
                payload.page_title,
                payload.captured_at or now,
                now,
            ),
        )
        conn.commit()
        message = conn.execute(
            "SELECT * FROM feishu_web_messages WHERE fingerprint=?",
            (fingerprint,),
        ).fetchone()

        reply_text = build_feishu_reply(payload) if payload.auto_reply else ""
        reply = None
        if reply_text:
            existing = conn.execute(
                "SELECT * FROM feishu_web_replies WHERE message_id=? AND status IN ('queued','fetched')",
                (message["id"],),
            ).fetchone()
            if existing:
                reply = existing
            else:
                conn.execute(
                    """
                    INSERT INTO feishu_web_replies (
                        message_id, client_id, chat_title, reply_text, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'queued', ?, ?)
                    """,
                    (message["id"], payload.client_id or "default", payload.chat_title, reply_text, now, now),
                )
                conn.commit()
                reply = conn.execute(
                    "SELECT * FROM feishu_web_replies WHERE message_id=? ORDER BY id DESC LIMIT 1",
                    (message["id"],),
                ).fetchone()

    return {
        "message": row_to_feishu_message(message),
        "reply": row_to_feishu_reply(reply) if reply else None,
    }



def startup() -> None:
    init_db()
    reprocess_existing()
    gmail_sync.start_watcher(interval_seconds=300)



def index() -> FileResponse:
    return FileResponse(ROOT / "static" / "index.html")



def feishu_web_bridge_script() -> FileResponse:
    return FileResponse(
        ROOT / "feishu-web-bridge.user.js",
        media_type="application/javascript; charset=utf-8",
        filename="feishu-web-bridge.user.js",
    )



def health() -> dict[str, Any]:
    return {"ok": True, "service": "reloop", "version": "0.1.0"}



def gmail_status() -> dict[str, Any]:
    return gmail_sync.LAST_STATUS



def gmail_sync_now(limit: int = Query(default=25, ge=1, le=100)) -> dict[str, Any]:
    return gmail_sync.sync_gmail(limit=limit)



def candidates(q: str = Query(default="", max_length=100)) -> list[dict[str, Any]]:
    sql = "SELECT * FROM candidates"
    args: tuple[Any, ...] = ()
    if q:
        sql += " WHERE name LIKE ? OR raw_text LIKE ? OR platform LIKE ?"
        term = f"%{q}%"
        args = (term, term, term)
    sql += " ORDER BY score DESC, updated_at DESC"
    with closing(db()) as conn:
        return [row_to_dict(row) for row in conn.execute(sql, args).fetchall()]



def candidate_detail(candidate_id: int) -> dict[str, Any]:
    with closing(db()) as conn:
        row = conn.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone()
    if not row:
        raise HTTPException(404, "候选人不存在")
    return row_to_dict(row)



def capture(payload: CapturePayload) -> dict[str, Any]:
    return {"ok": True, "candidate": save_candidate(payload)}



def feishu_web_message(payload: FeishuWebMessagePayload) -> dict[str, Any]:
    saved = save_feishu_web_message(payload)
    return {"ok": True, **saved}



def feishu_web_messages(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    with closing(db()) as conn:
        rows = conn.execute(
            "SELECT * FROM feishu_web_messages ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return {"ok": True, "messages": [row_to_feishu_message(row) for row in rows]}



def feishu_web_pending_replies(
    client_id: str = Query(default="default", max_length=120),
    limit: int = Query(default=5, ge=1, le=20),
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    with closing(db()) as conn:
        rows = conn.execute(
            """
            SELECT * FROM feishu_web_replies
            WHERE client_id=? AND status='queued'
            ORDER BY id ASC LIMIT ?
            """,
            (client_id, limit),
        ).fetchall()
        ids = [row["id"] for row in rows]
        if ids:
            conn.executemany(
                "UPDATE feishu_web_replies SET status='fetched', updated_at=? WHERE id=?",
                [(now, reply_id) for reply_id in ids],
            )
            conn.commit()
            rows = conn.execute(
                f"SELECT * FROM feishu_web_replies WHERE id IN ({','.join('?' for _ in ids)}) ORDER BY id ASC",
                ids,
            ).fetchall()
    return {"ok": True, "replies": [row_to_feishu_reply(row) for row in rows]}



def feishu_web_reply_ack(payload: FeishuReplyAckPayload) -> dict[str, Any]:
    allowed = {"filled", "sent", "skipped", "failed"}
    status = payload.status if payload.status in allowed else "filled"
    with closing(db()) as conn:
        conn.execute(
            "UPDATE feishu_web_replies SET status=?, updated_at=? WHERE id=?",
            (status, datetime.now(UTC).isoformat(), payload.reply_id),
        )
        conn.commit()
    return {"ok": True, "reply_id": payload.reply_id, "status": status}



def import_text(payload: TextPayload) -> dict[str, Any]:
    capture_payload = CapturePayload(text=payload.text, title=payload.title, url=payload.url, source_type="manual_text")
    return {"ok": True, "candidate": save_candidate(capture_payload)}



def import_url(payload: UrlPayload) -> dict[str, Any]:
    url = validate_public_url(payload.url)
    if detect_platform(url) in {"BOSS直聘", "猎聘", "脉脉", "LinkedIn", "前程无忧", "智联招聘"}:
        raise HTTPException(400, "登录型招聘网站请使用 Chrome 扩展读取当前已授权页面，不能使用公开URL导入。")
    request = urllib.request.Request(url, headers={"User-Agent": "TTC-CandidateCollector/0.1 (+authorized-public-pages-only)"})
    try:
        opener = urllib.request.build_opener(_PublicRedirectHandler())
        with opener.open(request, timeout=20) as response:
            raw = response.read(3_000_000)
            content_type = response.headers.get_content_charset() or "utf-8"
    except (urllib.error.URLError, TimeoutError) as exc:
        raise HTTPException(422, f"公开页读取失败：{exc}") from exc
    html = raw.decode(content_type, errors="replace")
    parser = VisibleTextParser()
    parser.feed(html)
    title = first_match([r"<title[^>]*>(.*?)</title>"], html)
    result = save_candidate(CapturePayload(url=url, title=clean_text(title), text="\n".join(parser.parts), source_type="public_url"))
    return {"ok": True, "candidate": result, "note": "只处理了无需登录的公开 HTML；JS 页请使用浏览器扩展收藏当前可见内容。"}


def _extract_upload_text(body: bytes, suffix: str, attachment_path: Path) -> str:
    """Extract text from an uploaded file, with OCR fallback for scanned PDFs."""
    if suffix == ".pdf":
        text = "\n".join(page.get_text("text") for page in fitz.open(stream=body, filetype="pdf"))
        # Fallback to OCR for scanned PDFs.
        if len(clean_text(text)) < 30:
            ocr_result = ocr_pdf(attachment_path, filetype="pdf", engine="auto")
            if ocr_result.text:
                text = ocr_result.text
    elif suffix in {".doc", ".docx"}:
        text = gmail_sync.extract_word_text(attachment_path)
    else:
        result = ocr_pdf(attachment_path, filetype=suffix.lstrip("."), engine="auto")
        text = result.text
    return text



async def import_file(
    request: Request,
    filename: str = Query(..., max_length=160),
    platform: str = Query(default="PDF", max_length=40),
    source_type: str = Query(default="local_pdf", max_length=80),
    source_url: str = Query(default="", max_length=2000),
) -> dict[str, Any]:
    body = await request.body()
    if not body or len(body) > MAX_FILE:
        raise HTTPException(413, "文件为空或超过 12MB")
    suffix = Path(filename).suffix.lower()
    if suffix not in {".pdf", ".doc", ".docx", ".png", ".jpg", ".jpeg", ".tiff"}:
        raise HTTPException(415, "当前版本仅支持 PDF、DOC、DOCX、PNG、JPG、JPEG、TIFF")
    # Persist uploaded file so the review page can display the original attachment.
    attachments_dir = ROOT / "data" / "attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^\w一-龥.-]", "_", filename)
    attachment_path = attachments_dir / f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}_{safe_name}"
    attachment_path.write_bytes(body)
    try:
        text = _extract_upload_text(body, suffix, attachment_path)
    except Exception as exc:
        raise HTTPException(422, f"解析失败：{exc}") from exc
    if len(clean_text(text)) < 20:
        raise HTTPException(422, "未提取到足够文字，可能需要 OCR 模型或人工录入")
    result = save_candidate(CapturePayload(
        url=source_url,
        title=filename,
        text=text,
        source_type=source_type,
        platform=platform,
    ), attachment_path=str(attachment_path))
    return {"ok": True, "candidate": result}



def import_local_download(payload: LocalDownloadPayload) -> dict[str, Any]:
    downloads = (Path.home() / "Downloads").resolve()
    path = Path(payload.path).expanduser().resolve()
    try:
        path.relative_to(downloads)
    except ValueError as exc:
        raise HTTPException(400, "只允许导入当前用户 Downloads 目录中的文件") from exc
    if not path.is_file():
        raise HTTPException(404, "下载文件不存在")
    if path.stat().st_size > MAX_FILE:
        raise HTTPException(413, "文件超过 12MB")
    suffix = path.suffix.lower()
    if suffix not in {".pdf", ".doc", ".docx"}:
        raise HTTPException(415, "只支持 PDF、DOC、DOCX")
    try:
        text = _extract_upload_text(path.read_bytes(), suffix, path)
    except Exception as exc:
        raise HTTPException(422, f"解析失败：{exc}") from exc
    if len(clean_text(text)) < 20:
        raise HTTPException(422, "文件未提取到足够文字")
    result = save_candidate(CapturePayload(
        url=payload.source_url,
        title=path.name,
        text=text,
        source_type="gmail_browser_download",
        platform="Gmail",
    ), attachment_path=str(path))
    return {"ok": True, "candidate": result}



def _safe_ingest_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser().resolve()
    allowed_roots = {
        ROOT.resolve(),
        DATA_DIR.resolve(),
        (Path.home() / "Downloads").resolve(),
    }
    if not any(path == root or root in path.parents for root in allowed_roots):
        raise HTTPException(400, "只允许导入项目、数据或 Downloads 目录中的文件")
    if not path.is_file():
        raise HTTPException(404, "文件不存在")
    if path.stat().st_size > MAX_FILE:
        raise HTTPException(413, "文件超过 12MB")
    if path.suffix.lower() not in {".pdf", ".doc", ".docx", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"}:
        raise HTTPException(415, "只支持 PDF、DOC、DOCX 或图片")
    return path


def ingest_v2_file(payload: IngestFilePayload) -> dict[str, Any]:
    """New ingestion pipeline: parse local file and write to Feishu Base.

    Default is dry-run; set dry_run=false to actually create a Base record.
    """
    path = _safe_ingest_path(payload.path)
    return ingest_file(
        path,
        dry_run=payload.dry_run,
        skip_duplicates=payload.skip_duplicates,
        check_feishu_exists=payload.check_feishu_exists,
        source_platform=payload.source_platform,
        source_url=payload.source_url,
        source_extra=payload.source_extra,
    )



def ingest_v2_text(payload: IngestTextPayload) -> dict[str, Any]:
    """New ingestion pipeline: parse raw text and write to Feishu Base."""
    return ingest_text(
        payload.text,
        title=payload.title,
        source_url=payload.source_url,
        dry_run=payload.dry_run,
    )



def ingest_v2_log(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    """Recent ingestion log entries."""
    from reloop.ingestion.pipeline import _db_conn
    with closing(_db_conn()) as conn:
        rows = conn.execute(
            "SELECT * FROM ingestion_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return {"ok": True, "count": len(rows), "items": [dict(r) for r in rows]}



def evaluate_jd(candidate_id: int) -> dict[str, Any]:
    """对指定候选人重新运行 JD 对齐评分并保存。"""
    with closing(db()) as conn:
        row = conn.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone()
    if not row:
        raise HTTPException(404, "候选人不存在")
    record = parse_candidate(CapturePayload(
        url=row["source_url"] or "",
        title=row["title"] or "",
        text=row["raw_text"],
        platform=row["platform"],
        source_type=row["source_type"],
        captured_at=row["collected_at"],
    ))
    with closing(db()) as conn:
        conn.execute(
            """
            UPDATE candidates SET
                jd_score=?, jd_recommendation=?, jd_scores_json=?, updated_at=?
            WHERE id=?
            """,
            (
                record["jd_score"], record["jd_recommendation"],
                json.dumps(record["jd_scores"], ensure_ascii=False),
                datetime.now(UTC).isoformat(), candidate_id,
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone()
    return {"ok": True, "candidate": row_to_dict(row)}



def export_jd(min_score: int = Query(default=0, ge=0, le=100)) -> dict[str, Any]:
    """导出候选人按 JD 对齐评分排序，用于批量推人。"""
    with closing(db()) as conn:
        rows = conn.execute(
            "SELECT * FROM candidates WHERE jd_score >= ? OR score >= ? ORDER BY jd_score DESC NULLS LAST, score DESC",
            (min_score, min_score),
        ).fetchall()
    items = [row_to_dict(row) for row in rows]
    return {
        "ok": True,
        "count": len(items),
        "min_score": min_score,
        "candidates": [
            {
                "id": c["id"],
                "name": c["name"],
                "phone": c.get("phone"),
                "email": c.get("email"),
                "platform": c["platform"],
                "source_url": c["source_url"],
                "jd_score": c.get("jd_score"),
                "jd_recommendation": c.get("jd_recommendation"),
                "score": c["score"],
                "recommendation": c["recommendation"],
                "current_company": c["current_company"],
                "current_role": c["current_role"],
                "location": c["location"],
                "undergraduate_school": c["undergraduate_school"],
                "undergraduate_tier": c["undergraduate_tier"],
                "strengths": c["strengths"][:4],
                "risks": c["risks"][:2],
            }
            for c in items
        ],
    }



def search(payload: SearchPayload) -> dict[str, Any]:
    """Search local candidates by keyword/phrase with highlights."""
    return search_candidates(
        payload.q,
        min_score=payload.min_score,
        platform=payload.platform,
        limit=payload.limit,
    )



def feedback(payload: FeedbackPayload) -> dict[str, Any]:
    """Record human feedback on a candidate or parse result."""
    return add_feedback(
        candidate_id=payload.candidate_id,
        fingerprint=payload.fingerprint,
        feedback_type=payload.feedback_type,
        field=payload.field,
        note=payload.note,
    )



def list_candidate_feedback(
    candidate_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """List feedback entries, optionally filtered by candidate."""
    return list_feedback(candidate_id=candidate_id, limit=limit)


# ---------------------------------------------------------------------------
# Human review endpoints
# ---------------------------------------------------------------------------


def _safe_attachment_path(path: str | None) -> Path:
    """Resolve and validate an attachment path before serving it.

    Allowed roots: project root, user Downloads, and /tmp.
    """
    if not path:
        raise HTTPException(404, "无附件")
    raw = Path(path).expanduser()
    if not raw.is_absolute():
        raw = (ROOT / raw).resolve()
    else:
        raw = raw.resolve()
    allowed_roots = {ROOT.resolve(), (Path.home() / "Downloads").resolve(), Path("/tmp").resolve()}
    for root in allowed_roots:
        try:
            raw.relative_to(root)
            if raw.is_file():
                return raw
        except ValueError:
            continue
    raise HTTPException(403, "附件路径不在允许范围内")


# ----- v2 review (ingestion_log) -----


def review_queue_endpoint(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    return review_queue(limit=limit)



def review_detail_endpoint(log_id: int) -> dict[str, Any]:
    detail = review_detail(log_id)
    if not detail.get("ok"):
        raise HTTPException(404, detail.get("error", "记录不存在"))
    return detail



def review_approve_endpoint(log_id: int, corrections: ReviewCorrections) -> dict[str, Any]:
    result = review_approve_record(log_id, corrections.model_dump(exclude_unset=True))
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "审批失败"))
    return result



def review_reject_endpoint(log_id: int, payload: ReviewRejectPayload) -> dict[str, Any]:
    result = review_reject_record(log_id, payload.reason)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "驳回失败"))
    return result



def review_attachment_endpoint(log_id: int) -> FileResponse:
    detail = review_detail(log_id)
    if not detail.get("ok"):
        raise HTTPException(404, detail.get("error", "记录不存在"))
    candidate = detail.get("candidate", {})
    attachment_path = candidate.get("original_attachment_path")
    path = _safe_attachment_path(attachment_path)
    return FileResponse(path)


# ----- v1 review (candidates table) -----

def _candidate_v1_to_record(row: sqlite3.Row) -> CandidateRecord:
    """Convert a v1 candidates table row to a CandidateRecord for Feishu writeback."""
    experiences = json.loads(row["experiences_json"] or "[]")
    education = json.loads(row["education_json"] or "{}")
    return CandidateRecord(
        name=row["name"] or None,
        phone=row["phone"] or None,
        email=row["email"] or None,
        current_company=row["current_company"] or None,
        current_title=row["current_role"] or None,
        current_location=row["location"] or None,
        employment_status=row["employment_status"] or None,
        expected_salary=row["expected_salary"] or None,
        school=row["undergraduate_school"] or None,
        education=Education(**education) if education else None,
        work_experiences=[WorkExperience(**e) for e in experiences] if experiences else [],
        raw_text=row["raw_text"] or "",
        source_url=row["source_url"] or None,
        source_type=row["source_type"] or "v1_candidate",
        source_platform=row["platform"] or "v1_candidate",
        review_status=row["review_status"] or "pending",
    )



def review_v1_queue_endpoint(
    status: str = Query(default="pending"),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    with closing(db()) as conn:
        rows = conn.execute(
            "SELECT id, name, phone, current_company, current_role, review_status, attachment_path, updated_at "
            "FROM candidates WHERE review_status = ? ORDER BY updated_at DESC LIMIT ?",
            (status, limit),
        ).fetchall()
    return {
        "ok": True,
        "count": len(rows),
        "items": [dict(r) for r in rows],
    }



def review_v1_detail_endpoint(candidate_id: int) -> dict[str, Any]:
    with closing(db()) as conn:
        row = conn.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone()
    if not row:
        raise HTTPException(404, "候选人不存在")
    record = _candidate_v1_to_record(row)
    return {
        "ok": True,
        "candidate_id": candidate_id,
        "candidate": record.model_dump(),
        "attachment_path": row["attachment_path"],
        "review_status": row["review_status"],
        "raw_text": row["raw_text"],
    }


def _update_candidates_table_from_record(conn: sqlite3.Connection, candidate_id: int, record: CandidateRecord) -> None:
    """Persist corrected CandidateRecord values back to the v1 candidates table."""
    conn.execute(
        """
        UPDATE candidates SET
            name=?, phone=?, email=?, current_company=?, current_role=?,
            undergraduate_school=?, expected_salary=?,
            experiences_json=?, education_json=?, updated_at=?
        WHERE id=?
        """,
        (
            record.name or "",
            record.phone or "",
            record.email or "",
            record.current_company or "",
            record.current_title or "",
            record.school or "",
            record.expected_salary or "",
            json.dumps([e.model_dump() for e in record.work_experiences], ensure_ascii=False),
            json.dumps(record.education.model_dump() if record.education else {}, ensure_ascii=False),
            datetime.now(UTC).isoformat(),
            candidate_id,
        ),
    )



def review_v1_approve_endpoint(candidate_id: int, corrections: ReviewCorrections) -> dict[str, Any]:
    with closing(db()) as conn:
        row = conn.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone()
    if not row:
        raise HTTPException(404, "候选人不存在")

    record = _candidate_v1_to_record(row)
    _apply_corrections(record, corrections.model_dump(exclude_unset=True))

    store = DeliveryStore()
    existing = store.get_by_fingerprint(record.fingerprint())
    if existing and existing.local_status == "delivered":
        raise HTTPException(409, "该候选人已完成投递，不能原地重新审批；请创建新版本")
    job = (
        store.reset_for_delivery(existing.id, record)
        if existing
        else store.enqueue(record, fingerprint=record.fingerprint())
    )

    with closing(db()) as conn:
        _update_candidates_table_from_record(conn, candidate_id, record)
        conn.execute(
            "UPDATE candidates SET review_status='approved' WHERE id=?",
            (candidate_id,),
        )
        conn.commit()
    return {
        "ok": True,
        "action": "approved",
        "feishu_record_id": None,
        "feishu_write_status": "blocked",
        "job_id": job.id,
        "delivery": "queued",
    }



def review_v1_reject_endpoint(candidate_id: int, payload: ReviewRejectPayload) -> dict[str, Any]:
    with closing(db()) as conn:
        row = conn.execute("SELECT id FROM candidates WHERE id=?", (candidate_id,)).fetchone()
        if not row:
            raise HTTPException(404, "候选人不存在")
        conn.execute(
            "UPDATE candidates SET review_status='rejected', updated_at=? WHERE id=?",
            (datetime.now(UTC).isoformat(), candidate_id),
        )
        conn.commit()
    return {"ok": True, "action": "rejected"}



def review_v1_attachment_endpoint(candidate_id: int) -> FileResponse:
    with closing(db()) as conn:
        row = conn.execute("SELECT attachment_path FROM candidates WHERE id=?", (candidate_id,)).fetchone()
    if not row or not row["attachment_path"]:
        raise HTTPException(404, "无附件")
    path = _safe_attachment_path(row["attachment_path"])
    return FileResponse(path)


def quality_stats() -> dict[str, Any]:
    """Aggregate data quality metrics for the dashboard."""
    with closing(db()) as conn:
        total_candidates = conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0] or 0
        fields = {
            "name": "name",
            "phone": "phone",
            "email": "email",
            "current_company": "current_company",
            "current_title": "current_role",
            "school": "undergraduate_school",
            "expected_salary": "expected_salary",
        }
        completeness: dict[str, float] = {}
        for label, column in fields.items():
            filled = conn.execute(
                f"SELECT COUNT(*) FROM candidates WHERE {column} IS NOT NULL AND {column} != ''",
            ).fetchone()[0]
            completeness[label] = round(filled / total_candidates, 2) if total_candidates else 0.0

        pending_v1 = conn.execute(
            "SELECT COUNT(*) FROM candidates WHERE review_status='pending'",
        ).fetchone()[0]

        total_log = conn.execute("SELECT COUNT(*) FROM ingestion_log").fetchone()[0] or 0
        success = conn.execute(
            "SELECT COUNT(*) FROM ingestion_log WHERE feishu_write_status='success'",
        ).fetchone()[0]
        pending_v2 = conn.execute(
            "SELECT COUNT(*) FROM ingestion_log WHERE review_status='pending'",
        ).fetchone()[0]

        low_confidence = 0
        checked = 0
        for row in conn.execute("SELECT dry_run_payload FROM ingestion_log WHERE dry_run_payload IS NOT NULL"):
            try:
                payload = json.loads(row["dry_run_payload"])
                candidate = payload.get("candidate", {})
                pc = candidate.get("parse_confidence")
                if pc is not None:
                    checked += 1
                    if float(pc) < 0.7:
                        low_confidence += 1
            except Exception:
                continue

    return {
        "ok": True,
        "field_completeness": completeness,
        "low_confidence_ratio": round(low_confidence / checked, 2) if checked else 0.0,
        "pending_review_count": pending_v1 + pending_v2,
        "ingestion_success_rate": round(success / total_log, 2) if total_log else 0.0,
    }



def quality_trend(days: int = Query(default=30, ge=1, le=90)) -> dict[str, Any]:
    """Daily ingestion trend for the last N days."""
    with closing(db()) as conn:
        rows = conn.execute(
            f"""
            SELECT date(created_at) AS day,
                   COUNT(*) AS total,
                   SUM(CASE WHEN feishu_write_status='success' THEN 1 ELSE 0 END) AS success,
                   SUM(CASE WHEN review_status='pending' THEN 1 ELSE 0 END) AS pending
            FROM ingestion_log
            WHERE created_at >= date('now', '-{days} days')
            GROUP BY day
            ORDER BY day
            """,
        ).fetchall()
    return {"ok": True, "trend": [dict(r) for r in rows]}
