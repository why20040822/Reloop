"""TTC 原始数据 -> 标准结构化人才格式 (Normalizer)。

标准格式 (STANDARD_KEYS) 是后续算法的直接输入, 带 key:
  source_id       TTC 人才 ID
  name            姓名
  base_location   base 地点
  company         当前公司
  position        当前职位
  work_years      经验年限(年, float; 由 "X年X月经验" 解析)
  education       学历
  skills          技能列表
  summary         画像摘要文本(供 embedding 匹配)
  last_active_at  平台最近活跃/更新时间(活跃度因子来源)
  tags            标签(粗筛用)
  raw             原始记录留底

TTC 页面需飞书登录, 真实接口字段以站点 XHR 为准;
本模块的 FIELD_ALIASES 覆盖常见中英文字段名, 拿到真实字段后只需在此补映射。
"""

import datetime as dt
import re
from typing import Optional

# 标准结构化格式的全部 key (写入 talent_profiles 前的中间格式)
STANDARD_KEYS = (
    "source_id", "name", "base_location", "company", "position",
    "work_years", "education", "skills", "summary",
    "last_active_at", "resume_updated_at", "tags", "raw",
    "notes", "stability", "work_history", "projects", "delivery_records",
)

# TTC 字段别名映射: 标准key -> 站点可能出现的字段名(按顺序取第一个命中)
FIELD_ALIASES = {
    "source_id": ("id", "talentId", "talent_id", "人才ID"),
    "name": ("name", "姓名", "userName"),
    "base_location": ("base", "baseLocation", "base地点", "城市", "所在城市", "地点"),
    "company": ("company", "公司", "currentCompany", "公司名称"),
    "position": ("position", "职位", "title", "当前职位", "岗位"),
    "work_years": ("workYears", "work_years", "经验", "工作年限", "经验年限"),
    "education": ("education", "学历", "degree", "最高学历"),
    "skills": ("skills", "技能", "tags", "标签", "skillTags"),
    "summary": ("summary", "简介", "备注", "remark", "description", "描述"),
    "last_active_at": ("lastActiveAt", "last_active_at", "最近活跃", "最近活跃时间",
                       "updatedAt", "更新时间", "updateTime", "resumeUpdatedAt"),
    "resume_updated_at": ("resumeUpdatedAt", "resume_updated_at", "简历更新时间", "resumeUpdateTime"),
    "notes": ("notes", "备注", "remark", "运营备注", "联系记录", "顾问备注"),
    "stability": ("stability", "稳定性", "tenure", "任期"),
    "work_history": ("workHistory", "work_history", "工作经历", "experience", "experiences"),
    "projects": ("projects", "projectHistory", "project_history", "项目经验", "projects_list", "projectExperiences"),
    "delivery_records": ("deliveryRecords", "delivery_records", "投递记录", "applications", "jobApplications", "投递历史"),
}

# 学历归一
EDUCATION_MAP = {
    "博士": "博士", "phd": "博士", "doctor": "博士",
    "硕士": "硕士", "master": "硕士", "研究生": "硕士", "mba": "硕士",
    "本科": "本科", "bachelor": "本科",
    "大专": "大专", "专科": "大专", "associate": "大专",
    "高中": "高中", "其他": "其他",
}

_WORK_YEARS_RE = re.compile(r"(\d+)\s*年(?:\s*(\d+)\s*个月?)?")
_MONTHS_ONLY_RE = re.compile(r"^(\d+)\s*个月?$")
_RELATIVE_RE = re.compile(r"(\d+)\s*(秒|分|小时|天|周|月|年)前")


def parse_work_years(value) -> Optional[float]:
    """解析经验年限: '5年3个月经验' / '5年' / '8个月' / 5.5 -> 年(float)。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    m = _WORK_YEARS_RE.search(text)
    if m:
        years = int(m.group(1))
        months = int(m.group(2) or 0)
        return round(years + months / 12.0, 2)
    m = _MONTHS_ONLY_RE.match(text)
    if m:
        return round(int(m.group(1)) / 12.0, 2)
    digits = re.findall(r"\d+", text)
    return float(digits[0]) if digits else None


def parse_datetime(value) -> Optional[dt.datetime]:
    """解析时间: ISO 字符串 / 时间戳(秒/毫秒) / '3天前' 相对时间。"""
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value
    if isinstance(value, dt.date):
        return dt.datetime.combine(value, dt.time())
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:  # 毫秒
            ts /= 1000.0
        try:
            # 统一使用UTC时间，避免本地时区混用
            return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).replace(tzinfo=None)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    m = _RELATIVE_RE.search(text)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = {"秒": 1 / 86400, "分": 1 / 1440, "小时": 1 / 24,
                 "天": 1, "周": 7, "月": 30, "年": 365}[unit]
        # 统一使用UTC时间，避免本地时区混用
        return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(days=n * delta)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d",
                "%Y年%m月%d日", "%m-%d %H:%M"):
        try:
            return dt.datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return dt.datetime.fromisoformat(text)
    except ValueError:
        return None


def normalize_education(value) -> Optional[str]:
    if value is None or isinstance(value, (dict, list)):
        return None
    text = str(value).strip()
    for k, v in EDUCATION_MAP.items():
        if k.lower() in text.lower():
            return v
    return text or None


def _pick(item: dict, standard_key: str):
    for alias in FIELD_ALIASES.get(standard_key, ()):
        if alias in item and item[alias] not in (None, "", []):
            return item[alias]
    return None


# ---------------- 真实 TTC 接口嵌套结构适配 ----------------
def _is_ttc_api_item(item: dict) -> bool:
    """真实 TTC 接口(/api/private-talent/v1/all-talents/{sid}/talents)返回的嵌套结构。

    用 owner_user_id / basic 作标记(部分人才缺 dynamic 段, 不能要求同时具备)。
    """
    return "owner_user_id" in item or isinstance(item.get("basic"), dict)


def _first(seq):
    return seq[0] if seq else None


def _trunc(value, n: int):
    """截断到列长度上限(超长字段全文仍在 raw/source_payload 里留底)。"""
    if isinstance(value, str) and len(value) > n:
        return value[:n]
    return value


def _normalize_ttc_api_item(item: dict) -> dict:
    """真实 TTC 接口嵌套结构 -> 标准格式。

    字段映射(站点 gateway.ttcadvisory.com):
      id                              -> source_id
      basic.name.cn_name              -> name
      basic.location[0]               -> base_location
      work.macro.current_company_name -> company
      work.macro.current_position     -> position
      work.macro.work_experience_months / 12 -> work_years
      education.macro.highest_degree  -> education
      skill.language                  -> skills
      dynamic.macro.last_updated_at   -> last_active_at
      dynamic.macro.target_positions  -> tags (粗筛命中岗位关键词)
      dynamic.macro.notes/remark      -> notes (运营备注)
      work.macro.stability/tenure     -> stability (稳定性指标 JSON)
      work.detail/history             -> work_history (工作经历 JSON list)
      motivation/目标/学历/技能 拼接   -> summary (供 embedding/文本匹配)
    """
    basic = item.get("basic") or {}
    dyn_macro = (item.get("dynamic") or {}).get("macro") or {}
    edu_macro = (item.get("education") or {}).get("macro") or {}
    work_macro = (item.get("work") or {}).get("macro") or {}
    skill = item.get("skill") or {}
    work_detail = (item.get("work") or {}).get("detail") or {}
    work_history_raw = work_detail.get("experiences") or work_detail.get("history") or []

    name = (basic.get("name") or {}).get("cn_name") or "未知"
    base_location = _first(basic.get("location") or [])
    company = work_macro.get("current_company_name")
    position = work_macro.get("current_position")
    months = work_macro.get("work_experience_months")
    work_years = round(months / 12.0, 2) if isinstance(months, (int, float)) else None
    education = normalize_education(edu_macro.get("highest_degree"))
    skills = skill.get("language") or []
    if isinstance(skills, str):
        skills = [s.strip() for s in re.split(r"[,，、/;；|]", skills) if s.strip()]
    last_active_at = parse_datetime(dyn_macro.get("last_updated_at") or item.get("created_at"))
    # 简历最新更新时间(活跃度核心参考维度, 数据获取成本低且准确性高)
    resume_updated_at = parse_datetime(dyn_macro.get("resumeUpdatedAt") or dyn_macro.get("resume_updated_at") or dyn_macro.get("last_updated_at"))

    target_positions = dyn_macro.get("target_positions") or []
    tags = list(dict.fromkeys([*target_positions, *([position] if position else [])]))

    # 新字段: notes / stability / work_history / projects / delivery_records
    notes = dyn_macro.get("notes") or dyn_macro.get("remark") or None
    stability = _parse_stability(work_macro)
    work_history = _parse_work_history(work_history_raw)
    projects = _parse_projects(item)
    delivery_records = _parse_delivery_records(item)

    parts = [str(name)]
    if company:
        parts.append(company)
    if position:
        parts.append(position)
    if base_location:
        parts.append(f"base{base_location}")
    if work_years is not None:
        parts.append(f"{work_years}年经验")
    if education:
        parts.append(education)
    if skills:
        parts.append(" ".join(skills))
    if target_positions:
        parts.append("目标:" + " ".join(target_positions))
    motivation = dyn_macro.get("motivation")
    if motivation:
        parts.append(motivation)
    if notes:
        parts.append(f"备注:{notes}")
    summary = " | ".join(p for p in parts if p)

    return {
        "source_id": str(item.get("id") or ""),
        "name": _trunc(str(name), 128),
        "base_location": _trunc(base_location, 64),
        "company": _trunc(company, 128),
        "position": _trunc(position, 128),
        "work_years": work_years,
        "education": _trunc(education, 64),
        "skills": skills or [],
        "summary": summary,
        "last_active_at": last_active_at,
        "resume_updated_at": resume_updated_at,
        "tags": tags or [],
        "raw": item,
        "notes": notes,
        "stability": stability,
        "work_history": work_history,
        "projects": projects,
        "delivery_records": delivery_records,
    }


def _parse_stability(work_macro: dict) -> Optional[dict]:
    """从 work.macro 解析稳定性指标。"""
    if not work_macro:
        return None
    avg_tenure = work_macro.get("avg_tenure") or work_macro.get("average_tenure")
    max_tenure = work_macro.get("max_tenure") or work_macro.get("longest_tenure")
    recent_tenure = work_macro.get("recent_tenure") or work_macro.get("current_tenure")
    company_count = work_macro.get("company_count") or work_macro.get("company_number")
    if any(v is not None for v in [avg_tenure, max_tenure, recent_tenure, company_count]):
        return {
            "avg_tenure": float(avg_tenure) if avg_tenure is not None else None,
            "max_tenure": float(max_tenure) if max_tenure is not None else None,
            "recent_tenure": float(recent_tenure) if recent_tenure is not None else None,
            "company_count": int(company_count) if company_count is not None else None,
        }
    return None


def _parse_work_history(work_history_raw) -> Optional[list]:
    """从 work.detail/history 解析工作经历列表。"""
    if not work_history_raw or not isinstance(work_history_raw, list):
        return None
    out = []
    for wh in work_history_raw:
        if not isinstance(wh, dict):
            continue
        out.append({
            "company": wh.get("company") or wh.get("company_name"),
            "position": wh.get("position") or wh.get("title"),
            "start_date": wh.get("start_date") or wh.get("startTime"),
            "end_date": wh.get("end_date") or wh.get("endTime"),
            "duration_months": wh.get("duration_months") or wh.get("months"),
            "industry": wh.get("industry") or wh.get("industry_domain"),
            "business_domain": wh.get("business_domain") or wh.get("domain"),
        })
    return out if out else None


def _parse_projects(item: dict) -> Optional[list]:
    """从 TTC 原始数据解析项目经验列表。"""
    # 常见字段路径: item.projects / item.projectHistory / item.dynamic.macro.projects
    raw = item.get("projects") or item.get("projectHistory") or item.get("project_history")
    if not raw:
        dyn_macro = (item.get("dynamic") or {}).get("macro") or {}
        raw = dyn_macro.get("projects") or dyn_macro.get("projectExperiences")
    if not raw or not isinstance(raw, list):
        return None
    out = []
    for p in raw:
        if not isinstance(p, dict):
            continue
        out.append({
            "name": p.get("name") or p.get("title") or p.get("project_name"),
            "industry": p.get("industry") or p.get("industry_domain") or p.get("sector"),
            "scenario": p.get("scenario") or p.get("business_scenario") or p.get("description"),
            "tech_stack": p.get("tech_stack") or p.get("techStack") or p.get("technologies"),
            "description": p.get("description") or p.get("desc"),
        })
    return out if out else None


def _parse_delivery_records(item: dict) -> Optional[list]:
    """从 TTC 原始数据解析投递记录列表。"""
    raw = item.get("deliveryRecords") or item.get("delivery_records") or item.get("applications") or item.get("jobApplications")
    if not raw or not isinstance(raw, list):
        return None
    out = []
    for d in raw:
        if not isinstance(d, dict):
            continue
        out.append({
            "position": d.get("position") or d.get("job_title") or d.get("title"),
            "company": d.get("company") or d.get("company_name"),
            "date": d.get("date") or d.get("created_at") or d.get("apply_date"),
            "status": d.get("status") or d.get("application_status"),
            "source": d.get("source") or d.get("channel"),
        })
    return out if out else None


def normalize_talent(raw_item: dict) -> Optional[dict]:
    """单条 TTC 原始记录 -> 标准结构化 dict (STANDARD_KEYS)。"""
    if not isinstance(raw_item, dict):
        return None
    if _is_ttc_api_item(raw_item):
        return _normalize_ttc_api_item(raw_item)

    skills = _pick(raw_item, "skills")
    if isinstance(skills, str):
        skills = [s.strip() for s in re.split(r"[,，、/;；|]", skills) if s.strip()]

    name = _pick(raw_item, "name") or "未知"
    company = _pick(raw_item, "company")
    position = _pick(raw_item, "position")

    summary = _pick(raw_item, "summary")
    if not summary:
        parts = [str(name), company or "", position or ""]
        base = _pick(raw_item, "base_location")
        if base:
            parts.append(f"base{base}")
        wy = parse_work_years(_pick(raw_item, "work_years"))
        if wy is not None:
            parts.append(f"{wy}年经验")
        edu = normalize_education(_pick(raw_item, "education"))
        if edu:
            parts.append(edu)
        if skills:
            parts.append(" ".join(skills))
        summary = " | ".join(p for p in parts if p)

    return {
        "source_id": str(_pick(raw_item, "source_id") or ""),
        "name": str(name),
        "base_location": _pick(raw_item, "base_location"),
        "company": company,
        "position": position,
        "work_years": parse_work_years(_pick(raw_item, "work_years")),
        "education": normalize_education(_pick(raw_item, "education")),
        "skills": skills or [],
        "summary": summary,
        "last_active_at": parse_datetime(_pick(raw_item, "last_active_at")),
        "resume_updated_at": parse_datetime(_pick(raw_item, "resume_updated_at")),
        "tags": skills or [],
        "raw": raw_item,
        "notes": _pick(raw_item, "notes"),
        "stability": _pick(raw_item, "stability"),
        "work_history": _pick(raw_item, "work_history"),
        "projects": _pick(raw_item, "projects"),
        "delivery_records": _pick(raw_item, "delivery_records"),
    }


def normalize_batch(raw) -> list[dict]:
    """批量归一化: 接受 list 或 {data/list/items/records: [...]} 包装。"""
    if isinstance(raw, dict):
        items = raw.get("data") or raw.get("list") or raw.get("items") \
            or raw.get("records") or raw.get("talents") or []
    elif isinstance(raw, list):
        items = raw
    else:
        return []
    out = []
    for it in items:
        norm = normalize_talent(it)
        if norm:
            out.append(norm)
    return out
