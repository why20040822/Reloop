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
    "last_active_at", "tags", "raw",
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
                       "updatedAt", "更新时间", "updateTime"),
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
            return dt.datetime.fromtimestamp(ts)
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
        return dt.datetime.now() - dt.timedelta(days=n * delta)
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
      motivation/目标/学历/技能 拼接   -> summary (供 embedding/文本匹配)
    """
    basic = item.get("basic") or {}
    dyn_macro = (item.get("dynamic") or {}).get("macro") or {}
    edu_macro = (item.get("education") or {}).get("macro") or {}
    work_macro = (item.get("work") or {}).get("macro") or {}
    skill = item.get("skill") or {}

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

    target_positions = dyn_macro.get("target_positions") or []
    tags = list(dict.fromkeys([*target_positions, *([position] if position else [])]))

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
        "tags": tags or [],
        "raw": item,
    }


def normalize_talent(raw_item: dict) -> Optional[dict]:
    """单条 TTC 原始记录 -> 标准结构化 dict (STANDARD_KEYS)。"""
    if not isinstance(raw_item, dict):
        return None
    # 真实接口返回嵌套结构, 走专用映射; 否则按平面字段别名(页面导出 JSON)处理
    if _is_ttc_api_item(raw_item):
        return _normalize_ttc_api_item(raw_item)

    skills = _pick(raw_item, "skills")
    if isinstance(skills, str):
        skills = [s.strip() for s in re.split(r"[,，、/;；|]", skills) if s.strip()]

    name = _pick(raw_item, "name") or "未知"
    company = _pick(raw_item, "company")
    position = _pick(raw_item, "position")

    # summary 为空时拼一个基础画像文本, 保证 embedding 有输入
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
        "tags": skills or [],
        "raw": raw_item,
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
