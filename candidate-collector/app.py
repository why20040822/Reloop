from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import os
import re
import secrets
import socket
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from contextlib import closing
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import fitz
import gmail_sync
import httpx
import jd_aligned
import db_admin
import resume_scorer
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from image_processing.ocr import ocr_pdf
from ingestion.browser_capture import BrowserCapturePayload, import_browser_capture
from ingestion.pipeline import ingest_file, ingest_text
from ingestion.review import approve_record as review_approve_record
from ingestion.review import reject_record as review_reject_record
from ingestion.review import review_detail, review_queue
from ingestion.review import _apply_corrections
from ingestion.search import add_feedback, list_feedback, search_candidates
from adapters.feishu_base import FeishuBaseAdapter
from models import CandidateRecord, Education, WorkExperience
from parsers.unified_parser import _extract_education, _extract_experiences


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "candidates.db"
MAX_TEXT = 600_000
MAX_FILE = 12 * 1024 * 1024
BROWSER_PDF_MAX = 50 * 1024 * 1024
BROWSER_ATTACHMENT_DIR = ROOT / "data" / "browser_attachments"
CORS_ORIGIN_RE = re.compile(
    r"^(chrome-extension://[a-p]{32}|http://(127\.0\.0\.1|localhost)(:\d+)?)$"
)
EXTENSION_ORIGIN_RE = re.compile(r"^chrome-extension://[a-p]{32}$")


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


class CapturePayload(BaseModel):
    url: str = ""
    title: str = ""
    heading: str = ""
    text: str = Field(min_length=10, max_length=MAX_TEXT)
    platform: str = ""
    source_type: str = "authorized_visible_page"
    captured_at: str | None = None
    structured_data: dict[str, Any] | None = None


class TextPayload(BaseModel):
    text: str = Field(min_length=10, max_length=MAX_TEXT)
    title: str = "手动导入"
    url: str = ""


class UrlPayload(BaseModel):
    url: str


class LocalDownloadPayload(BaseModel):
    path: str = Field(min_length=1, max_length=1000)
    source_url: str = ""


class FeishuWebMessagePayload(BaseModel):
    client_id: str = Field(default="default", max_length=120)
    chat_title: str = Field(default="", max_length=300)
    sender: str = Field(default="", max_length=120)
    text: str = Field(min_length=1, max_length=80_000)
    url: str = Field(default="", max_length=2000)
    message_time: str = Field(default="", max_length=120)
    page_title: str = Field(default="", max_length=300)
    captured_at: str | None = None
    auto_reply: bool = True


class FeishuReplyAckPayload(BaseModel):
    reply_id: int
    status: str = Field(default="filled", max_length=40)


class IngestFilePayload(BaseModel):
    path: str = Field(min_length=1, max_length=1000)
    dry_run: bool = True
    skip_duplicates: bool = True
    check_feishu_exists: bool = False
    source_platform: str | None = Field(default=None, max_length=40)
    source_url: str | None = Field(default=None, max_length=2000)
    source_extra: dict[str, Any] | None = None


class IngestTextPayload(BaseModel):
    text: str = Field(min_length=10, max_length=MAX_TEXT)
    title: str = "手动导入"
    source_url: str = ""
    dry_run: bool = True


class IngestFromUrlPayload(BaseModel):
    url: str = Field(min_length=10, max_length=2000)
    dry_run: bool = True


class BrowserCaptureImportPayload(BaseModel):
    """Payload from the extension for direct Feishu Base import."""

    url: str = ""
    title: str = ""
    heading: str = ""
    text: str = Field(min_length=10, max_length=600_000)
    platform: str = ""
    source_type: str = "browser_capture"
    captured_at: str | None = None
    structured_data: dict[str, Any] | None = None
    dry_run: bool = False
    skip_duplicates: bool = True
    check_feishu_exists: bool = False


class ResumeScorePayload(BaseModel):
    resume_text: str = Field(min_length=10, max_length=MAX_TEXT)
    jd_text: str = Field(min_length=5, max_length=120_000)
    weights_config: list[dict[str, Any]] | None = None
    candidate_name: str = Field(default="", max_length=80)


class SearchPayload(BaseModel):
    q: str = Field(min_length=1, max_length=200)
    min_score: int | None = Field(default=None, ge=0, le=100)
    platform: str | None = Field(default=None, max_length=40)
    limit: int = Field(default=50, ge=1, le=200)


class FeedbackPayload(BaseModel):
    candidate_id: int | None = None
    fingerprint: str | None = Field(default=None, max_length=120)
    feedback_type: str = Field(min_length=1, max_length=80)
    field: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=1000)


class ReviewCorrections(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=120)
    current_company: str | None = Field(default=None, max_length=120)
    current_title: str | None = Field(default=None, max_length=120)
    school: str | None = Field(default=None, max_length=120)
    expected_salary: str | None = Field(default=None, max_length=80)
    work_experiences: list[dict[str, Any]] | None = None
    education: dict[str, Any] | None = None


class ReviewRejectPayload(BaseModel):
    reason: str = Field(default="", max_length=1000)


app = FastAPI(title="TTC 候选人数据收藏器", version="0.1.0")

# --- 本地 API 加固 ---
# 1) CORS: 默认 *(向后兼容浏览器扩展),可用 TTC_CORS_ORIGINS 收敛,例如
#    "chrome-extension://<扩展ID>,http://127.0.0.1:8765"。
# 2) 写操作鉴权: 设置 TTC_LOCAL_API_TOKEN 后,所有 POST/PUT/DELETE 必须带
#    请求头 X-TTC-Token; 未设置则保持开放但启动时打印告警。
_CORS_ORIGINS = [o.strip() for o in os.getenv("TTC_CORS_ORIGINS", "*").split(",") if o.strip()]
_LOCAL_API_TOKEN = os.getenv("TTC_LOCAL_API_TOKEN", "")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_origin_regex=CORS_ORIGIN_RE.pattern,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    allow_private_network=True,
)


@app.middleware("http")
async def _local_api_token_guard(request: Request, call_next):
    if _LOCAL_API_TOKEN and request.method in {"POST", "PUT", "DELETE", "PATCH"}:
        token = request.headers.get("x-ttc-token", "")
        if not secrets.compare_digest(token, _LOCAL_API_TOKEN):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "缺少或错误的 X-TTC-Token"}, status_code=401)
    return await call_next(request)


app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
app.include_router(db_admin.router)


def db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _safe_pdf_name(name: str | None, source_id: str | None) -> str:
    base = Path(name or "resume.pdf").name
    stem = re.sub(r"[^0-9A-Za-z._\u4e00-\u9fff-]+", "_", Path(base).stem).strip("._")
    if not stem:
        stem = re.sub(r"[^0-9A-Za-z-]+", "_", source_id or "resume")
    return f"{stem[:120]}.pdf"


def _validate_public_https_url(url: str) -> urllib.parse.SplitResult:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("PDF URL 必须是无凭据的 HTTPS 地址")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("PDF 地址无法解析") from exc
    for item in addresses:
        ip = ipaddress.ip_address(item[4][0])
        if not ip.is_global:
            raise ValueError("PDF 地址解析到非公网地址")
    return parsed


def _platform_allows_remote_pdf(url: str, platform: str) -> bool:
    """Limit server-side PDF fetches to platform-owned DNS zones.

    Other signed CDN URLs are still supported, but must be fetched by the
    already-authorized browser and uploaded as bytes. This keeps arbitrary
    page-provided hosts away from the localhost server's network boundary.
    """
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    hostname = parsed.hostname.lower().rstrip(".")
    platform = (platform or "").lower()
    if platform == "ttc":
        return hostname == "ttcadvisory.com" or hostname.endswith(".ttcadvisory.com")
    if platform == "maimai":
        return hostname == "maimai.cn" or hostname.endswith(".maimai.cn")
    return False


def _persist_pdf_bytes(data: bytes, filename: str, source_id: str | None) -> Path:
    if not data.startswith(b"%PDF-"):
        raise ValueError("附件不是有效 PDF 原件")
    if len(data) > BROWSER_PDF_MAX:
        raise ValueError("PDF 超过 50 MiB 限制")
    digest = hashlib.sha256(data).hexdigest()
    BROWSER_ATTACHMENT_DIR.mkdir(parents=True, exist_ok=True)
    destination = BROWSER_ATTACHMENT_DIR / f"{digest[:16]}_{_safe_pdf_name(filename, source_id)}"
    if not destination.exists():
        destination.write_bytes(data)
    return destination


def _download_browser_pdf(url: str, filename: str, source_id: str | None) -> Path:
    current = url
    with httpx.Client(
        timeout=httpx.Timeout(20.0, read=45.0),
        follow_redirects=False,
        trust_env=False,
    ) as client:
        for _ in range(4):
            _validate_public_https_url(current)
            with client.stream("GET", current, headers={"Accept": "application/pdf"}) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("PDF 重定向缺少目标地址")
                    current = urllib.parse.urljoin(current, location)
                    continue
                if response.status_code in {401, 403}:
                    raise PermissionError("PDF 下载需要浏览器登录态")
                response.raise_for_status()
                length = response.headers.get("content-length")
                if length and int(length) > BROWSER_PDF_MAX:
                    raise ValueError("PDF 超过 50 MiB 限制")
                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes(256 * 1024):
                    total += len(chunk)
                    if total > BROWSER_PDF_MAX:
                        raise ValueError("PDF 超过 50 MiB 限制")
                    chunks.append(chunk)
                return _persist_pdf_bytes(b"".join(chunks), filename, source_id)
    raise ValueError("PDF 重定向次数过多")


def _require_extension_or_direct_request(request: Request) -> None:
    """Reject browser-page CSRF while preserving direct localhost CLI/tests."""
    origin = request.headers.get("origin", "")
    if origin and not (
        EXTENSION_ORIGIN_RE.fullmatch(origin)
        or re.fullmatch(r"http://(127\.0\.0\.1|localhost)(:\d+)?", origin)
    ):
        raise HTTPException(403, "浏览器导入接口只接受本扩展或本机直接调用")


def _safe_pdf_download_error(exc: Exception) -> str:
    """Return a useful error without leaking a signed attachment URL."""
    if isinstance(exc, httpx.HTTPStatusError):
        return f"PDF 下载返回 HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.TimeoutException):
        return "PDF 下载超时"
    if isinstance(exc, httpx.RequestError):
        return "PDF 下载网络错误"
    return str(exc)[:300]


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


def save_candidate(payload: CapturePayload, attachment_path: str | None = None) -> dict[str, Any]:
    record = parse_candidate(payload)
    stable = (
        f"url|{record['source_url']}"
        if record["source_url"]
        else f"text|{record['name']}|{record['raw_text'][:3000]}"
    )
    fingerprint = hashlib.sha256(stable.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc).isoformat()
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

    # 云端同步：经统一入口（R5 唯一指纹 + R6 质量随行）；失败不阻塞本地入库
    try:
        from cloud_sync.config import rds_configured

        if rds_configured():
            from ingestion.entry import ingest_record
            from models import CandidateRecord

            cloud_record = CandidateRecord(
                name=record["name"] or None,
                phone=record["phone"] or None,
                email=record["email"] or None,
                current_company=record["current_company"] or None,
                current_title=record["current_role"] or None,
                current_location=record["location"] or None,
                raw_text=record["raw_text"] or "",
                expected_salary=record["expected_salary"] or None,
                employment_status=record["employment_status"] or None,
                school=record["undergraduate_school"] or None,
                source_platform=record["platform"] or None,
                source_type=record["source_type"] or "browser_capture",
                source_url=record["source_url"] or None,
                original_attachment_path=attachment_path,
                captured_at=payload.captured_at or now,
            )
            ingest_record(cloud_record, read_back=False)
    except Exception as exc:
        logging.getLogger(__name__).warning(f"cloud sync failed: {exc}")

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
                    json.dumps(record["risks"], ensure_ascii=False), datetime.now(timezone.utc).isoformat(),
                    row["id"],
                ),
            )
        conn.commit()


def validate_public_url(value: str) -> str:
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(400, "请提供有效的 http/https 公开链接")
    host = (parsed.hostname or "").lower()
    if host in {"localhost", "127.0.0.1", "::1"} or host.startswith("10.") or host.startswith("192.168."):
        raise HTTPException(400, "不允许访问本地或内网地址")
    return value


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
    now = datetime.now(timezone.utc).isoformat()
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


@app.on_event("startup")
def startup() -> None:
    # R1：结构版本闸门——live 落后 repo 即拒绝启动（未配置 RDS 的机器跳过）
    from cloud_sync.config import rds_configured

    if rds_configured():
        from cloud_sync.migrate import ensure_current

        ensure_current()
    init_db()
    reprocess_existing()
    gmail_sync.start_watcher(interval_seconds=300)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/db-admin")
def db_admin_page() -> FileResponse:
    return FileResponse(ROOT / "static" / "db_admin.html")


@app.get("/feishu-web-bridge.user.js")
def feishu_web_bridge_script() -> FileResponse:
    return FileResponse(
        ROOT / "feishu-web-bridge.user.js",
        media_type="application/javascript; charset=utf-8",
        filename="feishu-web-bridge.user.js",
    )


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "candidate-collector", "database": str(DB_PATH)}


@app.get("/api/gmail-status")
def gmail_status() -> dict[str, Any]:
    return gmail_sync.LAST_STATUS


@app.post("/api/gmail-sync")
def gmail_sync_now(limit: int = Query(default=25, ge=1, le=100)) -> dict[str, Any]:
    return gmail_sync.sync_gmail(limit=limit)


@app.get("/api/candidates")
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


@app.get("/api/candidates/{candidate_id}")
def candidate_detail(candidate_id: int) -> dict[str, Any]:
    with closing(db()) as conn:
        row = conn.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone()
    if not row:
        raise HTTPException(404, "候选人不存在")
    return row_to_dict(row)


@app.post("/api/capture")
def capture(payload: CapturePayload) -> dict[str, Any]:
    return {"ok": True, "candidate": save_candidate(payload)}


@app.post("/api/import-browser-capture")
def import_browser_capture_endpoint(
    payload: BrowserCaptureImportPayload,
    request: Request,
) -> dict[str, Any]:
    """Direct Feishu Base import for browser extension captures.

    Unlike ``/api/capture`` this endpoint writes directly to the configured
    Feishu Base (using ``FeishuBaseAdapter``) and returns the Feishu record ID
    on success. It also records the attempt in ``ingestion_log``.
    """
    _require_extension_or_direct_request(request)
    result = import_browser_capture(
        BrowserCapturePayload(**payload.model_dump()),
    )
    return {"ok": result.get("ok", False), **result}


@app.post("/api/import-browser-capture-v2")
async def import_browser_capture_v2_endpoint(
    request: Request,
    capture: str = Form(...),
    resume_pdf: UploadFile | None = File(default=None),
) -> dict[str, Any]:
    """Import an authorized browser capture and preserve its original PDF."""
    _require_extension_or_direct_request(request)
    if len(capture) > MAX_TEXT:
        raise HTTPException(413, "capture 元数据过大")
    try:
        raw_payload = json.loads(capture)
        payload = BrowserCapturePayload(**raw_payload)
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(422, f"capture 格式无效：{exc}") from exc

    attachment_path: Path | None = None
    if resume_pdf is not None:
        if resume_pdf.content_type not in {None, "", "application/pdf", "application/octet-stream"}:
            raise HTTPException(415, "resume_pdf 必须是 PDF")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = await resume_pdf.read(256 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > BROWSER_PDF_MAX:
                raise HTTPException(413, "PDF 超过 50 MiB 限制")
            chunks.append(chunk)
        try:
            attachment_path = _persist_pdf_bytes(
                b"".join(chunks),
                resume_pdf.filename or "resume.pdf",
                payload.source_candidate_id,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    else:
        resume = payload.resume or {}
        resume_url = str(resume.get("file_url") or resume.get("url") or "").strip()
        if resume_url:
            try:
                if not _platform_allows_remote_pdf(resume_url, payload.platform):
                    raise PermissionError("PDF 地址需由已授权浏览器获取")
                attachment_path = _download_browser_pdf(
                    resume_url,
                    str(resume.get("file_name") or resume.get("filename") or "resume.pdf"),
                    payload.source_candidate_id,
                )
            except Exception as exc:
                safe_error = _safe_pdf_download_error(exc)
                if not payload.pdf_fetch_failed_reason:
                    return {
                        "ok": False,
                        "action": "needs_browser_pdf",
                        "error": safe_error,
                    }
                payload.pdf_fetch_failed_reason = (
                    f"服务端下载失败：{safe_error}；浏览器下载失败：{payload.pdf_fetch_failed_reason}"
                )[:1000]

    result = import_browser_capture(payload, attachment_path=attachment_path)
    return {"ok": result.get("ok", False), **result}


@app.post("/api/feishu-web/message")
def feishu_web_message(payload: FeishuWebMessagePayload) -> dict[str, Any]:
    saved = save_feishu_web_message(payload)
    return {"ok": True, **saved}


@app.get("/api/feishu-web/messages")
def feishu_web_messages(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    with closing(db()) as conn:
        rows = conn.execute(
            "SELECT * FROM feishu_web_messages ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return {"ok": True, "messages": [row_to_feishu_message(row) for row in rows]}


@app.get("/api/feishu-web/pending-replies")
def feishu_web_pending_replies(
    client_id: str = Query(default="default", max_length=120),
    limit: int = Query(default=5, ge=1, le=20),
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
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


@app.post("/api/feishu-web/reply-ack")
def feishu_web_reply_ack(payload: FeishuReplyAckPayload) -> dict[str, Any]:
    allowed = {"filled", "sent", "skipped", "failed"}
    status = payload.status if payload.status in allowed else "filled"
    with closing(db()) as conn:
        conn.execute(
            "UPDATE feishu_web_replies SET status=?, updated_at=? WHERE id=?",
            (status, datetime.now(timezone.utc).isoformat(), payload.reply_id),
        )
        conn.commit()
    return {"ok": True, "reply_id": payload.reply_id, "status": status}


@app.post("/api/import-text")
def import_text(payload: TextPayload) -> dict[str, Any]:
    capture_payload = CapturePayload(text=payload.text, title=payload.title, url=payload.url, source_type="manual_text")
    return {"ok": True, "candidate": save_candidate(capture_payload)}


@app.post("/api/import-url")
def import_url(payload: UrlPayload) -> dict[str, Any]:
    url = validate_public_url(payload.url)
    if detect_platform(url) in {"BOSS直聘", "猎聘", "脉脉", "LinkedIn", "前程无忧", "智联招聘"}:
        raise HTTPException(400, "登录型招聘网站请使用 Chrome 扩展读取当前已授权页面，不能使用公开URL导入。")
    request = urllib.request.Request(url, headers={"User-Agent": "TTC-CandidateCollector/0.1 (+authorized-public-pages-only)"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
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


@app.post("/api/import-file")
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
    attachment_path = attachments_dir / f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{safe_name}"
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


@app.post("/api/import-local-download")
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


@app.post("/api/ingest-v2/file")
def ingest_v2_file(payload: IngestFilePayload) -> dict[str, Any]:
    """New ingestion pipeline: parse local file and write to Feishu Base.

    Default is dry-run; set dry_run=false to actually create a Base record.
    """
    path = Path(payload.path).expanduser().resolve()
    if not path.is_file():
        raise HTTPException(404, "文件不存在")
    return ingest_file(
        path,
        dry_run=payload.dry_run,
        skip_duplicates=payload.skip_duplicates,
        check_feishu_exists=payload.check_feishu_exists,
        source_platform=payload.source_platform,
        source_url=payload.source_url,
        source_extra=payload.source_extra,
    )


@app.post("/api/ingest-v2/text")
def ingest_v2_text(payload: IngestTextPayload) -> dict[str, Any]:
    """New ingestion pipeline: parse raw text and write to Feishu Base."""
    return ingest_text(
        payload.text,
        title=payload.title,
        source_url=payload.source_url,
        dry_run=payload.dry_run,
    )


@app.get("/api/ingest-v2/log")
def ingest_v2_log(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    """Recent ingestion log entries."""
    from ingestion.pipeline import _db_conn
    with closing(_db_conn()) as conn:
        rows = conn.execute(
            "SELECT * FROM ingestion_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return {"ok": True, "count": len(rows), "items": [dict(r) for r in rows]}


@app.get("/api/ingest-v2/jobs")
def ingest_v2_jobs(
    state: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    """Operational view of durable ingestion delivery jobs."""
    from ingestion.delivery import DeliveryStore
    from ingestion.pipeline import DB_PATH

    store = DeliveryStore(DB_PATH)
    store.init()
    items = store.list(state=state, limit=limit)
    # candidate_json may contain personal data and is intentionally not exposed.
    for item in items:
        item.pop("candidate_json", None)
    return {"ok": True, "stats": store.stats(), "count": len(items), "items": items}


@app.post("/api/ingest-v2/jobs/{job_id}/retry")
def retry_ingest_v2_job(job_id: str) -> dict[str, Any]:
    """Release a non-completed job for immediate worker retry."""
    from ingestion.delivery import DeliveryStore
    from ingestion.pipeline import DB_PATH

    store = DeliveryStore(DB_PATH)
    store.init()
    if not store.retry(job_id):
        raise HTTPException(409, "任务不存在或已经完成")
    return {"ok": True, "job_id": job_id, "state": "retrying"}


@app.post("/api/evaluate-jd/{candidate_id}")
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
                datetime.now(timezone.utc).isoformat(), candidate_id,
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone()
    return {"ok": True, "candidate": row_to_dict(row)}


@app.get("/api/export-jd")
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


@app.post("/api/search")
def search(payload: SearchPayload) -> dict[str, Any]:
    """Search local candidates by keyword/phrase with highlights."""
    return search_candidates(
        payload.q,
        min_score=payload.min_score,
        platform=payload.platform,
        limit=payload.limit,
    )


@app.post("/api/feedback")
def feedback(payload: FeedbackPayload) -> dict[str, Any]:
    """Record human feedback on a candidate or parse result."""
    return add_feedback(
        candidate_id=payload.candidate_id,
        fingerprint=payload.fingerprint,
        feedback_type=payload.feedback_type,
        field=payload.field,
        note=payload.note,
    )


@app.get("/api/feedback")
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

@app.get("/api/review/queue")
def review_queue_endpoint(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    return review_queue(limit=limit)


@app.get("/api/review/{log_id}")
def review_detail_endpoint(log_id: int) -> dict[str, Any]:
    detail = review_detail(log_id)
    if not detail.get("ok"):
        raise HTTPException(404, detail.get("error", "记录不存在"))
    return detail


@app.post("/api/review/{log_id}/approve")
def review_approve_endpoint(log_id: int, corrections: ReviewCorrections) -> dict[str, Any]:
    result = review_approve_record(log_id, corrections.model_dump(exclude_unset=True))
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "审批失败"))
    return result


@app.post("/api/review/{log_id}/reject")
def review_reject_endpoint(log_id: int, payload: ReviewRejectPayload) -> dict[str, Any]:
    result = review_reject_record(log_id, payload.reason)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "驳回失败"))
    return result


@app.get("/api/review/{log_id}/attachment")
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


@app.get("/api/review-v1/queue")
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


@app.get("/api/review-v1/{candidate_id}")
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
            datetime.now(timezone.utc).isoformat(),
            candidate_id,
        ),
    )


@app.post("/api/review-v1/{candidate_id}/approve")
def review_v1_approve_endpoint(candidate_id: int, corrections: ReviewCorrections) -> dict[str, Any]:
    with closing(db()) as conn:
        row = conn.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone()
    if not row:
        raise HTTPException(404, "候选人不存在")

    record = _candidate_v1_to_record(row)
    _apply_corrections(record, corrections.model_dump(exclude_unset=True))

    adapter = FeishuBaseAdapter()
    try:
        resp = adapter.create_record(record)
        feishu_record_id = _extract_record_id_from_adapter(resp)
    except Exception as exc:
        raise HTTPException(500, f"飞书写入失败：{exc}") from exc

    with closing(db()) as conn:
        _update_candidates_table_from_record(conn, candidate_id, record)
        conn.execute(
            "UPDATE candidates SET review_status='approved' WHERE id=?",
            (candidate_id,),
        )
        conn.commit()
    return {"ok": True, "action": "approved", "feishu_record_id": feishu_record_id}


@app.post("/api/review-v1/{candidate_id}/reject")
def review_v1_reject_endpoint(candidate_id: int, payload: ReviewRejectPayload) -> dict[str, Any]:
    with closing(db()) as conn:
        row = conn.execute("SELECT id FROM candidates WHERE id=?", (candidate_id,)).fetchone()
        if not row:
            raise HTTPException(404, "候选人不存在")
        conn.execute(
            "UPDATE candidates SET review_status='rejected', updated_at=? WHERE id=?",
            (datetime.now(timezone.utc).isoformat(), candidate_id),
        )
        conn.commit()
    return {"ok": True, "action": "rejected"}


@app.get("/api/review-v1/{candidate_id}/attachment")
def review_v1_attachment_endpoint(candidate_id: int) -> FileResponse:
    with closing(db()) as conn:
        row = conn.execute("SELECT attachment_path FROM candidates WHERE id=?", (candidate_id,)).fetchone()
    if not row or not row["attachment_path"]:
        raise HTTPException(404, "无附件")
    path = _safe_attachment_path(row["attachment_path"])
    return FileResponse(path)


def _extract_record_id_from_adapter(resp: dict[str, Any]) -> str | None:
    """Best-effort extraction of Feishu record ID from lark-cli response."""
    data = resp.get("data", {})
    if isinstance(data, dict):
        record_id_list = data.get("record_id_list")
        if isinstance(record_id_list, list) and record_id_list:
            return record_id_list[0]
        return data.get("record_id")
    if isinstance(data, list) and data:
        return data[0].get("record_id")
    return None


@app.get("/api/quality/stats")
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


@app.get("/api/quality/trend")
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


# ── 简历评估打分窗口（黑客松 R3） ─────────────────────────────────────

_SCORE_HISTORY: list[float] = []  # 进程内已评分数，用于「相对位置」


@app.get("/resume-score")
def resume_score_page() -> FileResponse:
    return FileResponse(ROOT / "static" / "resume_score.html")


@app.post("/api/resume-score")
async def resume_score(request: Request) -> dict[str, Any]:
    """简历评估打分：JSON（resume_text+jd_text）或 multipart（file 文件上传 + 表单字段）。"""
    content_type = request.headers.get("content-type", "")
    candidate_name = ""
    weights_config: list[dict[str, Any]] | None = None

    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        jd_text = str(form.get("jd_text") or "").strip()
        candidate_name = str(form.get("candidate_name") or "").strip()
        raw_weights = str(form.get("weights_config") or "").strip()
        if raw_weights:
            try:
                weights_config = json.loads(raw_weights)
            except json.JSONDecodeError as exc:
                raise HTTPException(400, f"weights_config 不是合法 JSON：{exc}") from exc
        resume_text = str(form.get("resume_text") or "").strip()
        upload = form.get("file")
        if upload is not None and getattr(upload, "filename", ""):
            body = await upload.read()
            if not body or len(body) > MAX_FILE:
                raise HTTPException(413, "文件为空或超过 12MB")
            suffix = Path(upload.filename or "").suffix.lower()
            if suffix not in {".pdf", ".doc", ".docx", ".txt"}:
                raise HTTPException(415, "仅支持 PDF、DOC、DOCX、TXT")
            tmp_dir = ROOT / "data" / "attachments"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            safe_name = re.sub(r"[^\w一-龥.-]", "_", upload.filename or "resume")
            tmp_path = tmp_dir / f"score_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{safe_name}"
            tmp_path.write_bytes(body)
            try:
                resume_text = clean_text(body.decode("utf-8", errors="replace")) if suffix == ".txt" else clean_text(_extract_upload_text(body, suffix, tmp_path))
            except Exception as exc:
                raise HTTPException(422, f"简历文件解析失败：{exc}") from exc
            if not candidate_name:
                candidate_name = Path(upload.filename or "").stem
        if len(resume_text) < 10:
            raise HTTPException(400, "请上传简历文件或粘贴简历文本（至少 10 字）")
        if len(jd_text) < 5:
            raise HTTPException(400, "请提供 JD 文本（至少 5 字）")
    else:
        payload = ResumeScorePayload(**(await request.json()))
        resume_text = clean_text(payload.resume_text)
        jd_text = payload.jd_text
        weights_config = payload.weights_config
        candidate_name = payload.candidate_name

    try:
        result = resume_scorer.score_resume(
            resume_text,
            jd_text,
            weights_config=weights_config,
            candidate_name=candidate_name,
            history=_SCORE_HISTORY,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    _SCORE_HISTORY.append(result["overall"])
    return {"ok": True, "result": result}


@app.get("/api/resume-score/history")
def resume_score_history() -> dict[str, Any]:
    return {"ok": True, "scores": _SCORE_HISTORY}


# ── Cloud RDS unified query API ─────────────────────────────────────

@app.get("/api/cloud/candidates")
def cloud_candidates(limit: int = Query(default=50, ge=1, le=500)) -> dict[str, Any]:
    """Return recent candidates from the cloud RDS MySQL instance."""
    try:
        from cloud_sync.client import CloudSyncClient
        from cloud_sync.config import rds_configured
    except ImportError:
        return {"ok": False, "error": "cloud_sync module not available"}
    if not rds_configured():
        return {"ok": False, "error": "RDS not configured"}
    client = CloudSyncClient()
    return {"ok": True, "candidates": client.list_recent_candidates(limit)}


@app.get("/api/cloud/search")
def cloud_search(
    q: str = Query(..., description="搜索关键词"),
    project_id: str = Query(default="ttc"),
    limit: int = Query(default=10, ge=1, le=100),
) -> dict[str, Any]:
    """Keyword search across cloud candidates and memories."""
    try:
        from cloud_sync.client import get_conn
        from cloud_sync.config import rds_configured
    except ImportError:
        return {"ok": False, "error": "cloud_sync module not available"}
    if not rds_configured():
        return {"ok": False, "error": "RDS not configured"}

    results = {"candidates": [], "memories": []}
    like = f"%{q}%"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT fingerprint, name, current_company, current_role,
                       LEFT(raw_text, 300) AS raw_text
                FROM cloud_candidates
                WHERE raw_text LIKE %s OR name LIKE %s OR current_company LIKE %s
                ORDER BY collected_at DESC
                LIMIT %s
                """,
                (like, like, like, limit),
            )
            cols = [d[0] for d in cur.description]
            results["candidates"] = [dict(zip(cols, r)) for r in cur.fetchall()]

            cur.execute(
                """
                SELECT source, content_type, LEFT(content_text, 400) AS content_text,
                       metadata, created_at
                FROM memories
                WHERE project_id = %s AND content_text LIKE %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (project_id, like, limit),
            )
            cols = [d[0] for d in cur.description]
            results["memories"] = [dict(zip(cols, r)) for r in cur.fetchall()]

    return {"ok": True, "q": q, **results}
