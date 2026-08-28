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
import hashlib
import re
from typing import Optional

# 标准结构化格式的全部 key (写入 talent_profiles 前的中间格式)
STANDARD_KEYS = (
    "source_id", "name", "base_location", "company", "position",
    "work_years", "education", "skills", "summary",
    "last_active_at", "resume_updated_at", "tags", "raw",
    "notes", "stability", "work_history", "projects", "delivery_records",
    "contact_phone", "contact_email", "seek_status",
    "current_salary", "expected_salary", "target_positions",
    "education_history", "contact_status",
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
        parsed = dt.datetime.fromisoformat(text)
        # 统一转 UTC naive, 避免带时区 datetime 入库 MySQL DATETIME 时区混乱
        if parsed.tzinfo is not None:
            return parsed.astimezone(dt.timezone.utc).replace(tzinfo=None)
        return parsed
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


def talent_fingerprint(item: dict) -> str:
    """缺 id 时的稳定指纹兜底(F1, 2026-08-28): 绝不落空 source_id。

    source_id 为空 => sync 编排跳过查重 => 每次导入无条件 INSERT => 重复数据。
    用 name/phone/email/company/position 生成确定性指纹, 同一人重复导入得到
    相同指纹 -> 走 upsert 更新而不是新增。真实 id 永远优先, 指纹只是兜底。
    """
    parts = [
        str((item.get("basic") or {}).get("name") or item.get("name") or ""),
        str(_first((item.get("basic") or {}).get("phone") or []) or item.get("contact_phone") or ""),
        str(_first((item.get("basic") or {}).get("email") or []) or item.get("contact_email") or ""),
        str(((item.get("work") or {}).get("macro") or {}).get("current_company_name") or item.get("company") or ""),
        str(((item.get("work") or {}).get("macro") or {}).get("current_position") or item.get("position") or ""),
    ]
    raw = "|".join(parts).strip().lower()
    return "fp_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _trunc(value, n: int):
    """截断到列长度上限(超长字段全文仍在 raw/source_payload 里留底)。"""
    if isinstance(value, str) and len(value) > n:
        return value[:n]
    return value


def _normalize_ttc_api_item(item: dict) -> dict:
    """真实 TTC 接口嵌套结构 -> 标准格式 (2026-08-26 按真实 XHR 重构)。

    实测字段结构(gateway.ttcadvisory.com/api/private-talent/v1/all-talents/{sid}/talents):
      id                              -> source_id
      basic.name.cn_name / en_name    -> name
      basic.location[0]               -> base_location
      basic.phone / basic.email       -> contact_phone / contact_email (联系方式)
      work.macro.current_company_name -> company
      work.macro.current_position     -> position
      work.macro.work_experience_months / 12 -> work_years
      work.items[]                    -> work_history (多段工作经历, 含起止时间/公司/岗位/
                                           职级/职责长文本/管理规模/公司类别/业务领域/是否实习)
      work.macro.*                    -> stability (稳定性指标 JSON, 月->年)
      education.macro.highest_degree  -> education
      education.items[]               -> education_history (教育经历明细)
      project.items[]                 -> projects (项目经验)
      skill.ai_ability                -> skills (AI 能力标签)
      dynamic.macro.last_updated_at   -> last_active_at (人才最后更新 = 简历更新时间, 活跃度核心)
      dynamic.macro.resume_updated_at -> resume_updated_at
      dynamic.macro.seek_status       -> seek_status (求职状态)
      dynamic.macro.current_salary_raw/expected_salary -> 薪资
      dynamic.macro.target_positions  -> target_positions (目标岗位)
      dynamic.macro.concern_reason/concern_tags -> notes (人才库运营备注)
      dynamic.macro.motivation        -> summary 求职动机段
      motivation/目标/学历/技能 拼接   -> summary (供 embedding/文本匹配)
    """
    basic = item.get("basic") or {}
    dyn_macro = (item.get("dynamic") or {}).get("macro") or {}
    edu_macro = (item.get("education") or {}).get("macro") or {}
    work_macro = (item.get("work") or {}).get("macro") or {}
    skill = item.get("skill") or {}
    work_items = (item.get("work") or {}).get("items") or []
    edu_items = (item.get("education") or {}).get("items") or []
    project_items = (item.get("project") or {}).get("items") or []

    name_obj = basic.get("name") or {}
    name = name_obj.get("cn_name") or name_obj.get("en_name") or "未知"
    base_location = _first(basic.get("location") or [])
    company = work_macro.get("current_company_name")
    position = work_macro.get("current_position")
    months = work_macro.get("work_experience_months")
    work_years = round(months / 12.0, 2) if isinstance(months, (int, float)) else None
    education = normalize_education(edu_macro.get("highest_degree"))
    # 技能: 真实字段是 skill.ai_ability (AI 能力标签); 兼容旧字段 skill.language
    skills = skill.get("ai_ability") or skill.get("language") or []
    if isinstance(skills, str):
        skills = [s.strip() for s in re.split(r"[,，、/;；|]", skills) if s.strip()]

    # 联系方式(列表取首个)
    contact_phone = _first(basic.get("phone") or [])
    contact_email = _first(basic.get("email") or [])

    # 活跃时间(v3 2026-08-28): 只信真实时间字段, 不再用 created_at 兜底——
    # created_at 是"入库时间", 兜底会让新导入记录全员伪装"刚活跃",
    # 是"全员活跃"失真的数据源头。缺字段就落 None(未知), 宁缺勿假。
    last_active_at = parse_datetime(dyn_macro.get("last_updated_at"))
    resume_updated_at = parse_datetime(
        dyn_macro.get("resume_updated_at")
        or dyn_macro.get("resumeUpdatedAt")
        or dyn_macro.get("last_updated_at")
    )

    target_positions = dyn_macro.get("target_positions") or []
    tags = list(dict.fromkeys([*target_positions, *([position] if position else [])]))

    # ---- 备注(收藏状态/联系状态/备注语句) ----
    # 人才库运营备注: 关注原因(concern_reason) 是最有价值的备注信号
    concern_tags = dyn_macro.get("concern_tags") or []
    concern_reason = dyn_macro.get("concern_reason")
    notes = None
    note_parts = []
    if concern_reason:
        note_parts.append("；".join(concern_reason) if isinstance(concern_reason, list) else str(concern_reason))
    if concern_tags:
        note_parts.append("关注标签: " + ("、".join(concern_tags) if isinstance(concern_tags, list) else str(concern_tags)))
    if note_parts:
        notes = " | ".join(note_parts)
    if not notes:
        notes = dyn_macro.get("notes") or dyn_macro.get("remark") or None
    # 联系状态: 由求职状态推导默认值(未联系), 人工可改
    seek_status = dyn_macro.get("seek_status") or None
    contact_status = None
    if seek_status:
        if "已离职" in str(seek_status) or "离职" in str(seek_status):
            contact_status = "未联系"  # 离职找工作中, 值得优先联系
    # 薪资: 保留原文(current_salary_raw 更可读) + 数字(万/月)
    current_salary = dyn_macro.get("current_salary_raw") or dyn_macro.get("current_salary")
    expected_salary = dyn_macro.get("expected_salary")

    stability = _parse_stability(work_macro, work_items)
    work_history = _parse_work_history(work_items)
    projects = _parse_projects(project_items)
    education_history = _parse_education_history(edu_items)
    delivery_records = _parse_delivery_records(item)

    # ---- summary: 画像摘要文本(供 embedding 与文本匹配, 尽量全) ----
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
        parts.append("技能:" + " ".join(skills))
    if seek_status:
        parts.append(f"求职状态:{seek_status}")
    if current_salary:
        parts.append(f"现薪:{current_salary}")
    if target_positions:
        parts.append("目标:" + " ".join(target_positions))
    motivation = dyn_macro.get("motivation")
    if motivation:
        parts.append(f"动机:{motivation}")
    # 工作职责摘要(前 200 字, 匹配信号强)
    if work_history:
        wh_summary = " ".join(
            f"{w.get('company') or ''}{w.get('business_line') or ''}{w.get('position') or ''}"
            f"{'(' + str(w.get('management_scale')) + ')' if w.get('management_scale') else ''}:"
            f"{(w.get('description') or '')[:200]}"
            for w in work_history[:3]
        )
        if wh_summary:
            parts.append("经历:" + wh_summary)
    if notes:
        parts.append(f"备注:{notes}")
    summary = " | ".join(p for p in parts if p)

    return {
        "source_id": str(item.get("id") or "") or talent_fingerprint(item),
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
        "contact_phone": _trunc(contact_phone, 64),
        "contact_email": _trunc(contact_email, 128),
        "seek_status": _trunc(seek_status, 64),
        "current_salary": _trunc(str(current_salary) if current_salary is not None else None, 64),
        "expected_salary": _trunc(str(expected_salary) if expected_salary is not None else None, 64),
        "target_positions": target_positions or [],
        "education_history": education_history,
        "contact_status": contact_status,
    }


def _parse_stability(work_macro: dict, work_items: list = None) -> Optional[dict]:
    """从 work.macro 解析稳定性指标(月 -> 年)。work_items 用于补 company_count。"""
    if not work_macro:
        return None
    avg_tenure_month = work_macro.get("avg_tenure_month") or work_macro.get("avg_tenure")
    max_tenure_month = work_macro.get("max_tenure_month") or work_macro.get("max_tenure")
    recent_tenure_month = work_macro.get("latest_tenure_month") or work_macro.get("recent_tenure") or work_macro.get("current_tenure")
    company_count = work_macro.get("company_count") or work_macro.get("company_number")
    if company_count is None and work_items:
        company_count = len({(w.get("company_name") or w.get("company") or "") for w in work_items if isinstance(w, dict)})
    out = {}
    if avg_tenure_month is not None:
        out["avg_tenure"] = round(float(avg_tenure_month) / 12.0, 2)
    if max_tenure_month is not None:
        out["max_tenure"] = round(float(max_tenure_month) / 12.0, 2)
    if recent_tenure_month is not None:
        out["recent_tenure"] = round(float(recent_tenure_month) / 12.0, 2)
    if company_count is not None:
        out["company_count"] = int(company_count)
    # 补充: 是否有大厂经验 / 管理经验 / 最高管理规模 (前端展示用)
    if "has_big_company_exp" in work_macro:
        out["has_big_company_exp"] = bool(work_macro["has_big_company_exp"])
    if "has_management_exp" in work_macro:
        out["has_management_exp"] = bool(work_macro["has_management_exp"])
    if work_macro.get("max_management_scale"):
        out["max_management_scale"] = str(work_macro["max_management_scale"])
    return out if out else None


def _parse_work_history(work_items) -> Optional[list]:
    """从 work.items 解析工作经历列表(多段, 对齐 TTC 真实格式)。

    每段包含: 基本信息(公司/业务线/岗位·职级)、工作职责(description 长文本)、
    管理规模(management_scale)、起止时间、任职时长、公司类别、业务领域、是否实习。
    同时兼容旧路径 work.detail.experiences / work.detail.history。
    """
    if work_items is None:
        return None
    if isinstance(work_items, dict):
        work_items = work_items.get("experiences") or work_items.get("history") or []
    if not work_items or not isinstance(work_items, list):
        return None
    out = []
    for wh in work_items:
        if not isinstance(wh, dict):
            continue
        is_intern = wh.get("is_internship")
        if isinstance(is_intern, dict):
            is_intern = is_intern.get("label") in ("Y", "是", "true")
        company = wh.get("company_name") or wh.get("company") or wh.get("company_std")
        position = wh.get("position") or wh.get("title")
        entry = {
            "company": company,
            "company_std": wh.get("company_name_std") or wh.get("company_std"),
            "business_line": wh.get("business_line") or wh.get("business_domain"),
            "position": position,
            "position_std": wh.get("position_std"),
            "job_level": wh.get("job_level") or wh.get("job_level_raw"),
            "start_date": wh.get("start_time") or wh.get("start_date"),
            "end_date": wh.get("end_time") or wh.get("end_date"),
            "tenure_months": wh.get("tenure_months") or wh.get("months") or wh.get("duration_months"),
            "duration_months": wh.get("tenure_months") or wh.get("months") or wh.get("duration_months"),
            "description": wh.get("description") or wh.get("responsibility") or wh.get("duty"),
            "management_scale": wh.get("management_scale") or wh.get("team_size"),
            "has_management": wh.get("has_management"),
            "company_category": wh.get("company_category") or wh.get("company_tier"),
            "business_domain_category": wh.get("business_domain_category") or wh.get("industry_domain") or wh.get("industry"),
            "is_internship": bool(is_intern),
            "latest_performance": wh.get("latest_performance"),
        }
        out.append(entry)
    return out if out else None


def _parse_projects(project_items) -> Optional[list]:
    """从 project.items 解析项目经验列表(对齐 TTC 真实格式)。兼容旧路径。"""
    if project_items is None:
        return None
    if isinstance(project_items, dict):
        project_items = project_items.get("items") or []
    if not project_items or not isinstance(project_items, list):
        return None
    out = []
    for p in project_items:
        if not isinstance(p, dict):
            continue
        industry = p.get("industry_track") or p.get("industry") or p.get("industry_domain")
        scenario = p.get("business_scenario") or p.get("scenario") or p.get("business_scenario_list")
        out.append({
            "name": p.get("project_name") or p.get("name") or p.get("title"),
            "company": p.get("company_name") or p.get("company"),
            "role": p.get("role"),
            # 兼容旧前端字段名 (industry/scenario/tech_stack/description)
            "industry": industry,
            "scenario": scenario,
            "tech_stack": p.get("tech_stack") or p.get("technologies"),
            "start_date": p.get("project_start_month") or p.get("start_time") or p.get("start_date"),
            "end_date": p.get("project_end_month") or p.get("end_time") or p.get("end_date"),
            "description": p.get("project_description") or p.get("description") or p.get("desc"),
            "core_achievement": p.get("core_achievement"),
            "project_nature": p.get("project_nature") or p.get("nature"),
            "project_highlight": p.get("project_highlight") or [],
            "is_ai_project": p.get("is_ai_project"),
            "has_landing": p.get("has_landing"),
            "is_zero_to_one": p.get("is_zero_to_one"),
        })
    return out if out else None


def _parse_education_history(edu_items) -> Optional[list]:
    """从 education.items 解析教育经历明细列表。"""
    if not edu_items or not isinstance(edu_items, list):
        return None
    out = []
    for e in edu_items:
        if not isinstance(e, dict):
            continue
        out.append({
            "school": e.get("school_name") or e.get("school"),
            "school_std": e.get("school_name_std"),
            "major": e.get("major"),
            "degree": e.get("degree"),
            "start_date": e.get("start_time") or e.get("start_date"),
            "end_date": e.get("end_time") or e.get("end_date"),
            "school_tier": e.get("school_tier") or e.get("tier") or [],
            "is_full_time": e.get("is_full_time"),
            "overseas_region": e.get("overseas_region"),
            "qs_ranking": e.get("qs_ranking"),
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
        "source_id": str(_pick(raw_item, "source_id") or "") or talent_fingerprint(raw_item),
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
        "contact_phone": _pick(raw_item, "contact_phone"),
        "contact_email": _pick(raw_item, "contact_email"),
        "seek_status": _pick(raw_item, "seek_status"),
        "current_salary": _pick(raw_item, "current_salary"),
        "expected_salary": _pick(raw_item, "expected_salary"),
        "target_positions": _pick(raw_item, "target_positions"),
        "education_history": _pick(raw_item, "education_history"),
        "contact_status": _pick(raw_item, "contact_status"),
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
