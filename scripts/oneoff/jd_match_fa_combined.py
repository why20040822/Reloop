#!/usr/bin/env python3
# ONE-OFF (2026-08-03)
# Input: inspect --help and the operator invocation record before running.
# Execution: do not rerun without explicit operator confirmation.

"""
时来资本 FA 分析师 JD 筛选 — 结合本地 PDF + TTC 云端人才库。

流程：
1. 从 TTC TalentStore API 按 FA/投行/咨询/分析师等关键词召回候选人。
2. 解析本地 ./简历数据/ 中的 PDF。
3. 用 DeepSeek LLM 统一打分。
4. 去重、排序、取前 50。
5. 对入选者恢复手机号（本地 PDF 用 OCR/视觉；云端以 TTC 链接为主）。
6. 输出 JSON + HTML 报告。

用法：
    cd /Users/ashley/Downloads/ttc的交易系统
    reloop/.venv/bin/python scripts/jd_match_fa_combined.py --output-dir data/fa_shilai_match_combined --top-n 50
"""

from __future__ import annotations

import argparse
import asyncio
import html as html_lib
import json
import os
import re
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openai import AsyncOpenAI

REPO_ROOT = Path(__file__).resolve().parents[2]
CANDIDATE_COLLECTOR = REPO_ROOT / "reloop"
DATA_DIR = REPO_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
DEFAULT_OUTPUT_DIR = DATA_DIR / "fa_shilai_match_combined"

RESUME_DIR = REPO_ROOT / "简历数据"
TTC_WEB_BASE = "https://app.ttcadvisory.com"

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"


@dataclass
class JdSpec:
    title: str
    company: str
    location: Optional[str]
    min_years: float
    max_age: int
    require_degree: str
    jd_text: str
    scoring_dimensions: Tuple[str, ...]
    dimension_weights: Tuple[float, ...]
    must_have: Tuple[str, ...]
    preferred: Tuple[str, ...]


JD_SHILAI_FA = JdSpec(
    title="时来资本-FA分析师",
    company="时来资本",
    location=None,
    min_years=0.5,
    max_age=27,
    require_degree="本科",
    jd_text="""时来资本FA（分析师）

岗位职责：
1. 负责热门赛道项目的深度研究与执行落地；
2. 独立完成尽调、财务模型搭建、BP/路演材料制作，跟进交易谈判与交割；
3. 维护与创业者、机构的合作关系，保障项目闭环交付。

任职要求：
1. 本科及以上，金融/理工相关专业，复合背景优先；
2. 0.5-3年一线FA/VC/投行/咨询FA承做相关经验；
3. 具备扎实的商业分析与项目执行能力，能承受高压高效产出；
4. 本科211起，年龄27岁及以下。""",
    scoring_dimensions=(
        "FA/VC/投行/咨询承做经验",
        "财务模型与BP/路演能力",
        "行业研究与执行落地",
        "教育背景（211+金融/理工）",
        "商业分析与抗压执行",
    ),
    dimension_weights=(0.30, 0.20, 0.20, 0.15, 0.15),
    must_have=(
        "本科及以上",
        "年龄27岁及以下",
        "0.5-3年FA/VC/投行/咨询承做经验",
        "金融、理工或复合专业背景",
    ),
    preferred=(
        "211/985院校",
        "有财务模型、尽调、BP/路演材料经验",
        "热门赛道研究经验",
        "项目执行闭环经验",
    ),
)


# ---------------------------------------------------------------------------
# 环境加载
# ---------------------------------------------------------------------------

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
        Path.home() / ".ttc" / "deepseek.env",
        Path.home() / ".ttc" / "ttc_jwt.env",
    ]:
        for k, v in _parse_env_file(path).items():
            os.environ.setdefault(k, v)


# ---------------------------------------------------------------------------
# TTC 云端召回
# ---------------------------------------------------------------------------

def _ttc_search_queries() -> List[str]:
    return [
        "FA",
        "投行 分析师",
        "VC 投资经理",
        "PE 投资经理",
        "咨询顾问",
        "FA 承做",
        "投资分析师",
        "行业研究 金融",
        "融资顾问",
        "并购 分析师",
    ]


def _build_cloud_candidate(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """把 TTC search 结果转成统一候选结构。"""
    pid = item.get("person_leads_id")
    name = (item.get("cn_name") or item.get("name") or "").strip()
    if not name:
        return None

    work = item.get("work_information") or []
    latest = work[0] if work else {}
    company = latest.get("company") or latest.get("formatted_company") or ""
    role = item.get("job_title") or latest.get("job_title") or ""
    if company and role and company == role and len(work) >= 2:
        company = work[1].get("company") or work[1].get("formatted_company") or ""

    years = item.get("years_experience")
    if not years and work:
        years = sum(w.get("duration_in_years", 0) for w in work)
    years = round(float(years or 0), 1)

    edu_list = item.get("education_information") or []
    if edu_list:
        top = edu_list[0]
        education_summary = "·".join(p for p in [top.get("school"), top.get("degree"), top.get("major")] if p)
    else:
        education_summary = item.get("degree") or ""

    work_lines = []
    for w in work[:5]:
        dur = round(float(w.get("duration_in_years", 0) or 0), 1)
        work_lines.append(f"{w.get('company','')} | {w.get('job_title','')} | {dur}年 | {w.get('start_time','')} 至 {w.get('end_time','')}")

    edu_lines = []
    for e in edu_list[:3]:
        edu_lines.append(f"{e.get('school','')} | {e.get('major','')} | {e.get('degree','')}")

    raw_text = "\n".join([
        f"姓名: {name}",
        f"年龄: {item.get('age') or '未知'}",
        f"base地: {item.get('locations_display') or '未知'}",
        f"当前职位: {role}",
        f"当前公司: {company}",
        f"工作年限: {years}年",
        f"教育背景: {education_summary}",
        "工作经历:\n" + "\n".join(work_lines),
        "教育经历:\n" + "\n".join(edu_lines),
        f"技能标签: {', '.join(item.get('tags') or item.get('skills') or [])}",
    ])

    return {
        "source": "ttc_api",
        "person_leads_id": pid,
        "link": f"{TTC_WEB_BASE}/app/talent/{pid}" if pid else "",
        "file_path": None,
        "file_name": None,
        "name": name,
        "phone": None,
        "email": None,
        "current_company": company,
        "current_title": role,
        "school": (edu_list[0].get("school") if edu_list else "") or "",
        "degree": (edu_list[0].get("degree") if edu_list else "") or "",
        "major": (edu_list[0].get("major") if edu_list else "") or "",
        "education_summary": education_summary,
        "work_experiences": [
            {"company": w.get("company"), "role": w.get("job_title"), "period": f"{w.get('start_time','')} 至 {w.get('end_time','')}"}
            for w in work
        ],
        "years_experience": years,
        "age": item.get("age"),
        "raw_text": raw_text,
        "skills": item.get("tags") or item.get("skills") or [],
        "has_phone_in_ttc": bool(item.get("has_phone")),
    }


def fetch_cloud_candidates(token: str, queries: List[str], limit: int = 100) -> List[Dict[str, Any]]:
    from ttc_talent_search import search_ttc_talent

    all_items: List[Dict[str, Any]] = []
    for q in queries:
        try:
            items = search_ttc_talent(q, token, limit)
            print(f"  [TTC] '{q}' 召回 {len(items)} 人")
            all_items.extend(items)
        except Exception as exc:
            print(f"  [TTC] '{q}' 失败：{exc}")

    # 去重
    seen: Dict[str, Dict[str, Any]] = {}
    for item in all_items:
        pid = str(item.get("person_leads_id") or "").strip()
        key = pid if pid else f"{item.get('cn_name','')}|{item.get('name','')}"
        seen[key] = item
    return list(seen.values())


# ---------------------------------------------------------------------------
# 本地 PDF 解析
# ---------------------------------------------------------------------------

def _extract_years_from_filename(filename: str) -> Optional[float]:
    m = re.search(r"_(\d+\.?\d*)年", filename)
    if m:
        return float(m.group(1))
    if "一年以内" in filename:
        return 0.0
    return None


def _extract_graduation_year(record: Any) -> Optional[int]:
    if record.education and record.education.graduation_year:
        return record.education.graduation_year
    m = re.search(r"(20\d{2})\s*年?\s*(?:毕业|届)", record.raw_text or "")
    if m:
        return int(m.group(1))
    return None


def _infer_experience_years(record: Any, filename: str) -> Optional[float]:
    years = _extract_years_from_filename(filename)
    if years is not None:
        return years
    grad = _extract_graduation_year(record)
    if grad:
        base = 2026 - grad
        deg = (record.education.degree or "") if record.education else ""
        if "博士" in deg:
            return max(0.0, base - 5)
        if "硕士" in deg or "研究生" in deg or "MBA" in deg:
            return max(0.0, base - 3)
        return max(0.0, base)
    return None


def _infer_age(record: Any, filename: str) -> Optional[int]:
    years = _infer_experience_years(record, filename)
    grad = _extract_graduation_year(record)
    if grad:
        deg = (record.education.degree or "") if record.education else ""
        start_age = 22
        if "博士" in deg:
            start_age = 27
        elif "硕士" in deg or "研究生" in deg or "MBA" in deg:
            start_age = 25
        return (2026 - grad) + start_age
    if years is not None:
        return int(years) + 24
    return None


def parse_local_candidates(pdf_dir: Path) -> List[Dict[str, Any]]:
    from reloop.parsing.unified_parser import parse_resume_file

    candidates: List[Dict[str, Any]] = []
    for pdf in sorted(pdf_dir.glob("*.pdf")):
        try:
            record = parse_resume_file(pdf)
        except Exception as exc:
            print(f"  [Parse Error] {pdf.name}: {exc}")
            continue

        filename = pdf.name
        years = _infer_experience_years(record, filename)
        age = _infer_age(record, filename)
        education_summary = ""
        if record.education:
            education_summary = " ".join(
                p for p in [
                    record.education.school,
                    record.education.degree,
                    str(record.education.graduation_year) if record.education.graduation_year else None,
                    record.education.major,
                ] if p
            )

        candidates.append({
            "source": "local_pdf",
            "person_leads_id": None,
            "link": None,
            "file_path": str(pdf),
            "file_name": filename,
            "name": record.name or "",
            "phone": record.phone,
            "email": record.email,
            "current_company": record.current_company or "",
            "current_title": record.current_title or "",
            "school": record.school or (record.education.school if record.education else None) or "",
            "degree": (record.education.degree if record.education else None) or "",
            "major": (record.education.major if record.education else None) or "",
            "education_summary": education_summary,
            "work_experiences": [
                {"company": w.company, "role": w.role, "period": w.period}
                for w in (record.work_experiences or [])
            ],
            "years_experience": years,
            "age": age,
            "raw_text": record.raw_text or "",
            "skills": record.skills or [],
            "has_phone_in_ttc": None,
        })
    return candidates


# ---------------------------------------------------------------------------
# LLM 评分
# ---------------------------------------------------------------------------

def build_llm_prompt(candidate: Dict[str, Any], spec: JdSpec) -> str:
    dims = "\n".join(f"- {d}" for d in spec.scoring_dimensions)
    weighted = "\n".join(
        f"- {name}：{weight:.0%}" for name, weight in zip(spec.scoring_dimensions, spec.dimension_weights)
    )
    must = "\n".join(f"- {item}" for item in spec.must_have)
    preferred = "\n".join(f"- {item}" for item in spec.preferred)

    exp_lines = "\n".join(
        f"  {i+1}. {w.get('company')} | {w.get('role')} | {w.get('period')}"
        for i, w in enumerate(candidate.get("work_experiences") or [])
    ) or "  （未解析到）"

    return f"""你是一位资深一级市场猎头顾问，正在根据以下 JD 评估候选人简历。

岗位：{spec.title}

要求：
1. 先判断硬条件是否满足，再评估软性匹配。
2. 只根据简历中明确写出的经历打分，不要推测、不要脑补。
3. 工作年限需在 {spec.min_years} 到 3 年之间；年龄需 ≤ {spec.max_age} 岁；学历需本科及以上。
4. 如果简历中没有明确证据，必须记为 unknown，不得根据职称推断。
5. 每条证据必须是候选人资料中的原文短句，禁止改写或生成经历。
6. 地点不是硬性要求，但可在北京/上海等一线城市的描述中作为加分项参考。

必须满足的画像：
{must}

加分画像：
{preferred}

评分维度与权重：
{weighted}

请输出 JSON：
{{
  "hard_pass": true/false,
  "hard_fail_reason": "不通过则说明原因，通过则留空",
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

候选人资料：
姓名：{candidate.get('name') or '未知'}
年龄（推断）：{candidate.get('age') if candidate.get('age') else '未知'}
工作年限（推断）：{candidate.get('years_experience') if candidate.get('years_experience') is not None else '未知'}
当前公司：{candidate.get('current_company') or '未知'}
当前岗位：{candidate.get('current_title') or '未知'}
学校/学历/专业：{candidate.get('education_summary') or '未知'}
技能：{', '.join(candidate.get('skills') or [])}

工作经历：
{exp_lines}

完整简历原文：
{candidate['raw_text'][:12000]}
"""


def validate_llm_result(result: Any, spec: JdSpec) -> Dict[str, Any]:
    if not isinstance(result, dict):
        raise ValueError("LLM result is not an object")
    dims = result.get("dimensions")
    if not isinstance(dims, dict):
        raise ValueError("dimensions missing")
    clean_dims: Dict[str, int] = {}
    for name in spec.scoring_dimensions:
        v = dims.get(name, 0)
        clean_dims[name] = max(0, min(100, int(v) if isinstance(v, (int, float)) else 0))
    calculated = sum(clean_dims[name] * weight for name, weight in zip(spec.scoring_dimensions, spec.dimension_weights))
    must = result.get("must_have") if isinstance(result.get("must_have"), dict) else {}
    unmet = [k for k, v in must.items() if v == "unmet"]
    hard_pass = bool(result.get("hard_pass")) and not unmet
    overall = min(100, round(calculated, 1))
    rec = result.get("recommendation", "不匹配")
    if not hard_pass:
        rec = "不匹配"
    return {
        "hard_pass": hard_pass,
        "hard_fail_reason": result.get("hard_fail_reason", ""),
        "overall": overall,
        "recommendation": rec,
        "dimensions": clean_dims,
        "must_have": must,
        "evidence_quotes": [str(q) for q in result.get("evidence_quotes", []) if str(q).strip()],
        "risks": [str(r) for r in result.get("risks", []) if str(r).strip()],
        "evidence": str(result.get("evidence", "")),
    }


async def evaluate_candidate(
    client: AsyncOpenAI,
    candidate: Dict[str, Any],
    spec: JdSpec,
    sem: asyncio.Semaphore,
) -> Dict[str, Any]:
    async with sem:
        prompt = build_llm_prompt(candidate, spec)
        try:
            resp = await client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": "你是严谨的猎头评估员，只输出JSON，不得幻觉候选人经历。"},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                max_tokens=900,
                temperature=0.1,
            )
            content = resp.choices[0].message.content or "{}"
            llm_result = validate_llm_result(json.loads(content), spec)
        except Exception as e:
            llm_result = {
                "hard_pass": False,
                "hard_fail_reason": f"LLM 调用失败：{type(e).__name__}",
                "overall": 0,
                "recommendation": "不匹配",
                "dimensions": {d: 0 for d in spec.scoring_dimensions},
                "must_have": {},
                "evidence_quotes": [],
                "risks": [str(e)],
                "evidence": "LLM 调用失败",
            }
        candidate.update({
            "jd_title": spec.title,
            "hard_pass": llm_result["hard_pass"],
            "hard_fail_reason": llm_result["hard_fail_reason"],
            "overall": llm_result["overall"],
            "recommendation": llm_result["recommendation"],
            "dimension_scores": llm_result["dimensions"],
            "evidence": llm_result["evidence"],
            "evidence_quotes": llm_result["evidence_quotes"],
            "risks": llm_result["risks"],
            "must_have_assessment": llm_result["must_have"],
        })
        return candidate


# ---------------------------------------------------------------------------
# 去重与合并
# ---------------------------------------------------------------------------

def merge_candidates(local: List[Dict[str, Any]], cloud: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """以 person_leads_id / name+company 去重；本地 PDF 有手机号时优先保留。"""
    merged: Dict[str, Dict[str, Any]] = {}

    def key(c: Dict[str, Any]) -> str:
        pid = c.get("person_leads_id")
        if pid:
            return f"pid:{pid}"
        name = (c.get("name") or "").strip()
        company = (c.get("current_company") or "").strip()
        return f"nc:{name}|{company}"

    for c in cloud:
        merged[key(c)] = c

    for c in local:
        k = key(c)
        if k in merged:
            existing = merged[k]
            # 本地有手机号，补进去
            if c.get("phone") and not existing.get("phone"):
                existing["phone"] = c["phone"]
                existing["phone_source"] = "local_pdf"
            existing["file_path"] = c.get("file_path")
            existing["file_name"] = c.get("file_name")
            existing["source"] = "local_pdf+ttc_api"
        else:
            merged[k] = c

    return list(merged.values())


# ---------------------------------------------------------------------------
# 手机号恢复
# ---------------------------------------------------------------------------

PHONE_RE = re.compile(r"(?<![\d])1[3-9]\d{9}(?![\d])")


def _regex_phone(text: str) -> Optional[str]:
    if not text:
        return None
    m = PHONE_RE.search(text.replace(" ", "").replace("-", ""))
    return m.group(0) if m else None


async def _llm_extract_phone(raw_text: str, client: AsyncOpenAI) -> Optional[str]:
    prompt = f"""从以下简历文本中找出候选人本人的中国大陆手机号（11位，1开头）。
如果没有、被 masking 或无法确定，返回 null。只输出 JSON：{{"phone": "..." | null}}

简历文本：
{raw_text[:8000]}
"""
    try:
        resp = await client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=100,
            temperature=0.1,
        )
        data = json.loads(resp.choices[0].message.content or "{}")
        phone = data.get("phone")
        if phone:
            digits = "".join(ch for ch in str(phone) if ch.isdigit())
            if PHONE_RE.fullmatch(digits):
                return digits
    except Exception:
        pass
    return None


def _vision_recover_phone(pdf_path: str) -> Optional[Dict[str, Any]]:
    from reloop.parsing.mosaic_phone_recovery import recover_phone
    from reloop.parsing.unified_parser import parse_resume_file

    path = Path(pdf_path)
    try:
        record = parse_resume_file(path)
    except Exception:
        record = None
    parser_name = record.parser_name if record else "paddleocr"
    result = recover_phone(path, parser_name=parser_name)
    if result and result.phone:
        return {
            "phone": result.phone,
            "confidence": result.confidence,
            "reasoning": result.reasoning,
            "source": result.source,
        }
    return None


async def recover_phones(candidates: List[Dict[str, Any]], client: AsyncOpenAI) -> List[Dict[str, Any]]:
    for c in candidates:
        if c.get("phone"):
            c["phone_recovery"] = {"status": "already_visible", "phone": c["phone"]}
            continue

        # 本地 PDF 可尝试正则/LLM/视觉
        if c.get("file_path"):
            phone = _regex_phone(c.get("raw_text", ""))
            if phone:
                c["phone"] = phone
                c["phone_recovery"] = {"status": "regex", "phone": phone}
                continue

            phone = await _llm_extract_phone(c.get("raw_text", ""), client)
            if phone:
                c["phone"] = phone
                c["phone_recovery"] = {"status": "llm_text", "phone": phone}
                continue

            vision = _vision_recover_phone(c["file_path"])
            if vision:
                c["phone"] = vision["phone"]
                c["phone_recovery"] = {
                    "status": "vision_needs_review",
                    "phone": vision["phone"],
                    "confidence": vision["confidence"],
                    "reasoning": vision["reasoning"],
                }
                continue

        # 云端候选仅标记
        if c.get("has_phone_in_ttc"):
            c["phone_recovery"] = {"status": "ttc_has_phone", "phone": None, "note": "TTC 平台显示有手机号，需登录查看"}
        else:
            c["phone_recovery"] = {"status": "failed", "phone": None, "note": "无本地 PDF，无法自动恢复"}
    return candidates


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------

def safe(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        value = ", ".join(str(item) for item in value)
    return html_lib.escape(str(value), quote=True)


def render_html(candidates: List[Dict[str, Any]], spec: JdSpec, output: Path, logs: List[str]) -> None:
    ranked = sorted(candidates, key=lambda x: x["overall"], reverse=True)
    rows = []
    for idx, c in enumerate(ranked, 1):
        dim_summary = "<br>".join(f"{k}: {v}" for k, v in c.get("dimension_scores", {}).items())
        recovery = c.get("phone_recovery", {})
        recovery_html = f"{recovery.get('status')} | {safe(recovery.get('phone'))}"
        link_html = f'<a href="{safe(c.get("link"))}" target="_blank">TTC 详情</a>' if c.get("link") else ""
        rows.append({
            "rank": idx,
            "source": c.get("source", ""),
            "name": c.get("name", ""),
            "company": c.get("current_company", ""),
            "role": c.get("current_title", ""),
            "age": c.get("age") if c.get("age") else "未知",
            "exp": c.get("years_experience") if c.get("years_experience") is not None else "未知",
            "school": c.get("school", ""),
            "degree": c.get("degree", ""),
            "overall": c["overall"],
            "recommendation": c.get("recommendation", ""),
            "strict_match": "是" if c.get("strict_match") else "否",
            "phone": c.get("phone") or "",
            "email": c.get("email") or "",
            "recovery": recovery_html,
            "evidence": c.get("evidence", ""),
            "dim_summary": dim_summary,
            "link": link_html,
            "file": c.get("file_name") or "",
        })

    trs = []
    for r in rows:
        trs.append(
            f"""<tr>
            <td>{safe(r['rank'])}</td>
            <td>{safe(r['source'])}</td>
            <td>{safe(r['name'])}</td>
            <td>{safe(r['company'])}</td>
            <td>{safe(r['role'])}</td>
            <td>{safe(r['age'])}</td>
            <td>{safe(r['exp'])}</td>
            <td>{safe(r['school'])}</td>
            <td>{safe(r['degree'])}</td>
            <td><strong>{safe(r['overall'])}</strong></td>
            <td>{safe(r['recommendation'])}</td>
            <td>{safe(r['strict_match'])}</td>
            <td>{safe(r['phone'])}</td>
            <td>{safe(r['email'])}</td>
            <td>{r['recovery']}</td>
            <td>{safe(r['evidence'])}</td>
            <td>{r['dim_summary']}</td>
            <td>{r['link']}</td>
            <td>{safe(r['file'])}</td>
            </tr>"""
        )

    logs_html = "<br>".join(safe(line) for line in logs)
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>时来资本 FA 分析师 — 云端+本地联合筛选报告</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 1.5rem; background: #fff; color: #212529; line-height: 1.6; }}
  h1 {{ font-size: 1.5rem; margin-bottom: .5rem; }}
  .meta {{ color: #6c757d; font-size: .875rem; margin-bottom: 1rem; }}
  .logs {{ background: #f8f9fa; border-left: 4px solid #0d6efd; padding: .75rem; margin: 1rem 0; font-size: .85rem; }}
  table {{ width: 100%; border-collapse: collapse; margin: 1rem 0; font-size: .72rem; }}
  th, td {{ padding: .35rem; text-align: left; border: 1px solid #dee2e6; vertical-align: top; }}
  th {{ background: #e9ecef; font-weight: 600; }}
  tr:nth-child(even) {{ background: #f8f9fa; }}
  a {{ color: #0d6efd; }}
</style>
</head>
<body>
<h1>{safe(spec.title)} — 云端+本地联合筛选报告</h1>
<div class="meta">入选 {len(ranked)} 人 · 生成时间 {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>
<div class="logs"><strong>执行日志：</strong><br>{logs_html}</div>

<h2>排名表</h2>
<div style="overflow-x:auto"><table>
<thead><tr>
  <th>排名</th><th>来源</th><th>姓名</th><th>公司</th><th>岗位</th><th>年龄</th><th>年限</th><th>学校</th><th>学历</th><th>得分</th><th>推荐</th><th>严格匹配</th><th>手机</th><th>邮箱</th><th>恢复状态</th><th>证据</th><th>维度</th><th>链接</th><th>本地文件</th>
</tr></thead>
<tbody>{''.join(trs)}</tbody>
</table></div>
</body>
</html>"""
    output.write_text(html, encoding="utf-8")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

async def main_async() -> int:
    load_env()
    arg_parser = argparse.ArgumentParser(description="云端+本地 FA JD 联合筛选")
    arg_parser.add_argument("--resume-dir", type=str, default=str(RESUME_DIR), help="本地简历 PDF 目录")
    arg_parser.add_argument("--output-dir", type=str, default=str(DEFAULT_OUTPUT_DIR), help="输出目录")
    arg_parser.add_argument("--top-n", type=int, default=50, help="最终保留人数")
    arg_parser.add_argument("--concurrency", type=int, default=5, help="LLM 并发数")
    arg_parser.add_argument("--cloud-limit", type=int, default=100, help="每个关键词云端召回数量")
    args = arg_parser.parse_args()

    ds_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not ds_key:
        print("错误：未配置 DEEPSEEK_API_KEY", file=sys.stderr)
        return 1
    ttc_token = os.environ.get("TTC_JWT_TOKEN", "")
    if not ttc_token:
        print("错误：未配置 TTC_JWT_TOKEN", file=sys.stderr)
        return 1

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    logs: List[str] = []

    print("[1/5] 云端 TTC 召回 ...")
    cloud_raw = fetch_cloud_candidates(ttc_token, _ttc_search_queries(), args.cloud_limit)
    cloud = []
    for item in cloud_raw:
        c = _build_cloud_candidate(item)
        if c:
            cloud.append(c)
    logs.append(f"云端召回：{len(cloud)} 人（去重后）")
    print(f"  云端 {len(cloud)} 人")

    print("[2/5] 解析本地 PDF ...")
    local = parse_local_candidates(Path(args.resume_dir))
    logs.append(f"本地 PDF：{len(local)} 份")
    print(f"  本地 {len(local)} 份")

    print("[3/5] 合并去重 ...")
    candidates = merge_candidates(local, cloud)
    logs.append(f"合并去重后：{len(candidates)} 人")
    print(f"  合并 {len(candidates)} 人")

    print("[4/5] LLM 语义评分 ...")
    client = AsyncOpenAI(api_key=ds_key, base_url=DEEPSEEK_BASE_URL)
    sem = asyncio.Semaphore(args.concurrency)
    scored = await asyncio.gather(*(
        evaluate_candidate(client, c, JD_SHILAI_FA, sem) for c in candidates
    ))
    scored = list(scored)
    scored.sort(key=lambda x: x["overall"], reverse=True)

    passing = [s for s in scored if s.get("hard_pass") and s.get("overall", 0) >= 60]
    logs.append(f"严格匹配（硬条件通过且得分≥60）：{len(passing)} 人")
    print(f"  严格通过 {len(passing)} 人")

    if len(passing) >= args.top_n:
        top = passing[: args.top_n]
    else:
        non_passing = [s for s in scored if not (s.get("hard_pass") and s.get("overall", 0) >= 60)]
        top = passing + non_passing[: args.top_n - len(passing)]
    for c in top:
        c["strict_match"] = bool(c.get("hard_pass") and c.get("overall", 0) >= 60)
    logs.append(f"取前 {len(top)} 人（严格匹配 {sum(c['strict_match'] for c in top)} 人）")
    print(f"  前 {len(top)} 人已选出")

    print("[5/5] 手机号恢复 ...")
    top = await recover_phones(top, client)
    recovered = sum(1 for c in top if c.get("phone"))
    logs.append(f"有手机号/恢复成功：{recovered} / {len(top)}")
    print(f"  有手机 {recovered} / {len(top)}")

    meta = {
        "jd_title": JD_SHILAI_FA.title,
        "generated_at": datetime.now().isoformat(),
        "cloud_count": len(cloud),
        "local_count": len(local),
        "merged_count": len(candidates),
        "strict_match_count": len(passing),
        "top_n": len(top),
    }
    full_json_path = output_dir / "fa_shilai_all_scored.json"
    full_json_path.write_text(
        json.dumps({"meta": {**meta, "top_n": len(top)}, "data": scored}, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    json_path = output_dir / "fa_shilai_top50.json"
    json_path.write_text(
        json.dumps({"meta": meta, "data": top}, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    html_path = output_dir / "fa_shilai_report.html"
    render_html(top, JD_SHILAI_FA, html_path, logs)

    print(f"\n报告已保存：")
    print(f"  全量 JSON：{full_json_path}")
    print(f"  Top50 JSON：{json_path}")
    print(f"  HTML：{html_path}")
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
