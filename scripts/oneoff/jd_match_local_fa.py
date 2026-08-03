#!/usr/bin/env python3
# ONE-OFF (2026-08-03)
# Input: inspect --help and the operator invocation record before running.
# Execution: do not rerun without explicit operator confirmation.

"""
本地简历 PDF 的 JD 语义筛选（时来资本 FA 分析师）。

流程：
1. 解析 ./简历数据/ 下所有 PDF，提取文本与结构化字段。
2. 用 DeepSeek LLM 对每个候选人做语义匹配评分。
3. 按综合得分排序，取前 50。
4. 对入选但手机号缺失的简历，依次尝试：正则重扫、文本 LLM 抽取、马赛克视觉恢复。
5. 输出 JSON 与 HTML 报告。

用法：
    cd /Users/ashley/Downloads/ttc的交易系统
    .venv/bin/python scripts/jd_match_local_fa.py --output-dir data/fa_shilai_match
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
DEFAULT_OUTPUT_DIR = DATA_DIR / "fa_shilai_match"

RESUME_DIR = REPO_ROOT / "简历数据"

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"


# ---------------------------------------------------------------------------
# JD 定义
# ---------------------------------------------------------------------------

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
    location=None,  # JD 未注明 base，不强制地点
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
# PDF 解析与字段推断
# ---------------------------------------------------------------------------

def _extract_years_from_filename(filename: str) -> Optional[float]:
    """从文件名后缀如 '_7年.pdf'、'_一年以内.pdf' 提取年限。"""
    m = re.search(r"_(\d+\.?\d*)年", filename)
    if m:
        return float(m.group(1))
    if "一年以内" in filename:
        return 0.0
    return None


def _extract_graduation_year(record: Any) -> Optional[int]:
    """从教育字段或工作年限推断本科毕业年份。"""
    if record.education and record.education.graduation_year:
        return record.education.graduation_year
    # 尝试从 raw_text 抓取 '20xx 年毕业'
    m = re.search(r"(20\d{2})\s*年?\s*(?:毕业|届)", record.raw_text or "")
    if m:
        return int(m.group(1))
    return None


def _infer_experience_years(record: Any, filename: str) -> Optional[float]:
    """优先文件名，其次毕业年份到2026。"""
    years = _extract_years_from_filename(filename)
    if years is not None:
        return years
    grad = _extract_graduation_year(record)
    if grad:
        # 硕士则加3年，博士加5年
        base = 2026 - grad
        deg = (record.education.degree or "") if record.education else ""
        if "博士" in deg:
            return max(0.0, base - 5)
        if "硕士" in deg or "研究生" in deg or "MBA" in deg:
            return max(0.0, base - 3)
        return max(0.0, base)
    return None


def _infer_age(record: Any, filename: str) -> Optional[int]:
    """根据本科毕业年份 + 22 估算年龄；若无则未知。"""
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
        return int(years) + 24  # 粗略估算
    return None


def _normalize_degree(deg: Optional[str]) -> str:
    if not deg:
        return ""
    deg = deg.lower()
    for d in ["博士", "硕士", "研究生", "mba", "本科", "学士", "大专", "专科"]:
        if d in deg:
            return d
    return ""


def _bachelor_or_above(record: Any) -> bool:
    deg = _normalize_degree(record.education.degree if record.education else "")
    text = f"{record.raw_text or ''}"
    return any(k in deg or k in text for k in ["本科", "学士", "硕士", "研究生", "博士", "mba"])


def parse_local_candidates(pdf_dir: Path) -> List[Dict[str, Any]]:
    from reloop.parsing.unified_parser import parse_resume_file

    candidates: List[Dict[str, Any]] = []
    for pdf in sorted(pdf_dir.glob("*.pdf")):
        try:
            record = parse_resume_file(pdf)
        except Exception as exc:
            print(f"[Parse Error] {pdf.name}: {exc}")
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
            "file_path": str(pdf),
            "file_name": filename,
            "name": record.name or "",
            "phone": record.phone,
            "email": record.email,
            "current_company": record.current_company or "",
            "current_title": record.current_title or "",
            "school": record.school or (record.education.school if record.education else None) or "",
            "degree": _normalize_degree(record.education.degree if record.education else "") or "",
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
            "parser_name": record.parser_name,
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
                "_scoring_error": type(e).__name__,
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
    """调用现有马赛克恢复模块；需要配置 vision-capable LLM。"""
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


async def recover_phones(
    candidates: List[Dict[str, Any]],
    client: AsyncOpenAI,
) -> List[Dict[str, Any]]:
    """对手机号缺失的入选简历做多层恢复。"""
    for c in candidates:
        if c.get("phone"):
            c["phone_recovery"] = {"status": "already_visible", "phone": c["phone"]}
            continue

        # 1. 正则重扫
        phone = _regex_phone(c.get("raw_text", ""))
        if phone:
            c["phone"] = phone
            c["phone_recovery"] = {"status": "regex", "phone": phone}
            continue

        # 2. 文本 LLM 抽取
        phone = await _llm_extract_phone(c.get("raw_text", ""), client)
        if phone:
            c["phone"] = phone
            c["phone_recovery"] = {"status": "llm_text", "phone": phone}
            continue

        # 3. 视觉马赛克恢复（依赖 ENABLE_MOSAIC_PHONE_RECOVERY + vision LLM）
        vision = _vision_recover_phone(c["file_path"])
        if vision:
            c["phone"] = vision["phone"]
            c["phone_recovery"] = {
                "status": "vision_needs_review",
                "phone": vision["phone"],
                "confidence": vision["confidence"],
                "reasoning": vision["reasoning"],
            }
        else:
            c["phone_recovery"] = {
                "status": "failed",
                "phone": None,
                "note": "未配置有效 vision LLM 或无法从图像恢复；请人工复核",
            }
    return candidates


# ---------------------------------------------------------------------------
# 报告输出
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
        rows.append({
            "rank": idx,
            "name": c.get("name", ""),
            "company": c.get("current_company", ""),
            "role": c.get("current_title", ""),
            "age": c.get("age") if c.get("age") else "未知",
            "exp": c.get("years_experience") if c.get("years_experience") is not None else "未知",
            "school": c.get("school", ""),
            "degree": c.get("degree", ""),
            "overall": c["overall"],
            "recommendation": c.get("recommendation", ""),
            "phone": c.get("phone") or "",
            "email": c.get("email") or "",
            "recovery": recovery_html,
            "evidence": c.get("evidence", ""),
            "dim_summary": dim_summary,
            "file": c.get("file_name", ""),
        })

    trs = []
    for r in rows:
        trs.append(
            f"""<tr>
            <td>{safe(r['rank'])}</td>
            <td>{safe(r['name'])}</td>
            <td>{safe(r['company'])}</td>
            <td>{safe(r['role'])}</td>
            <td>{safe(r['age'])}</td>
            <td>{safe(r['exp'])}</td>
            <td>{safe(r['school'])}</td>
            <td>{safe(r['degree'])}</td>
            <td><strong>{safe(r['overall'])}</strong></td>
            <td>{safe(r['recommendation'])}</td>
            <td>{safe(r['phone'])}</td>
            <td>{safe(r['email'])}</td>
            <td>{r['recovery']}</td>
            <td>{safe(r['evidence'])}</td>
            <td>{r['dim_summary']}</td>
            <td>{safe(r['file'])}</td>
            </tr>"""
        )

    logs_html = "<br>".join(safe(line) for line in logs)
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>时来资本 FA 分析师 — 本地简历筛选报告</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 1.5rem; background: #fff; color: #212529; line-height: 1.6; }}
  h1 {{ font-size: 1.5rem; margin-bottom: .5rem; }}
  .meta {{ color: #6c757d; font-size: .875rem; margin-bottom: 1rem; }}
  .logs {{ background: #f8f9fa; border-left: 4px solid #0d6efd; padding: .75rem; margin: 1rem 0; font-size: .85rem; }}
  table {{ width: 100%; border-collapse: collapse; margin: 1rem 0; font-size: .75rem; }}
  th, td {{ padding: .4rem; text-align: left; border: 1px solid #dee2e6; vertical-align: top; }}
  th {{ background: #e9ecef; font-weight: 600; }}
  tr:nth-child(even) {{ background: #f8f9fa; }}
</style>
</head>
<body>
<h1>{safe(spec.title)} — 本地简历筛选报告</h1>
<div class="meta">入选 {len(ranked)} 人 · 生成时间 {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>
<div class="logs"><strong>执行日志：</strong><br>{logs_html}</div>

<h2>排名表</h2>
<div style="overflow-x:auto"><table>
<thead><tr>
  <th>排名</th><th>姓名</th><th>公司</th><th>岗位</th><th>年龄</th><th>年限</th><th>学校</th><th>学历</th><th>得分</th><th>推荐</th><th>手机</th><th>邮箱</th><th>手机恢复</th><th>证据</th><th>维度</th><th>文件名</th>
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
    arg_parser = argparse.ArgumentParser(description="本地简历 PDF 的时来资本 FA JD 筛选")
    arg_parser.add_argument("--resume-dir", type=str, default=str(RESUME_DIR), help="简历 PDF 目录")
    arg_parser.add_argument("--output-dir", type=str, default=str(DEFAULT_OUTPUT_DIR), help="输出目录")
    arg_parser.add_argument("--top-n", type=int, default=50, help="最终保留人数")
    arg_parser.add_argument("--concurrency", type=int, default=5, help="LLM 并发数")
    args = arg_parser.parse_args()

    ds_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not ds_key:
        print("错误：未配置 DEEPSEEK_API_KEY（已尝试从 ~/.ttc/deepseek.env 加载）", file=sys.stderr)
        return 1

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    logs: List[str] = []

    resume_dir = Path(args.resume_dir)
    if not resume_dir.is_dir():
        print(f"错误：简历目录不存在 {resume_dir}", file=sys.stderr)
        return 1

    print(f"[1/4] 解析本地 PDF ...")
    candidates = parse_local_candidates(resume_dir)
    logs.append(f"解析完成：{len(candidates)} 份 PDF")
    print(f"  共解析 {len(candidates)} 份")

    print(f"[2/4] LLM 语义评分 ...")
    client = AsyncOpenAI(api_key=ds_key, base_url=DEEPSEEK_BASE_URL)
    sem = asyncio.Semaphore(args.concurrency)
    scored = await asyncio.gather(*(
        evaluate_candidate(client, c, JD_SHILAI_FA, sem) for c in candidates
    ))
    scored = [s for s in scored if s.get("scoring_error") is None or s.get("overall", 0) > 0]
    scored.sort(key=lambda x: x["overall"], reverse=True)
    logs.append(f"评分完成：{len(scored)} 人获得有效分数")

    # 只保留硬条件通过且得分 ≥ 60 的候选人
    passing = [s for s in scored if s.get("hard_pass") and s.get("overall", 0) >= 60]
    logs.append(f"硬条件通过且得分 ≥60：{len(passing)} 人")
    print(f"  严格通过 {len(passing)} 人")

    # 取前 N：严格人选不足时，用综合得分最高的其他人补齐 50 人，并在报告中标记
    if len(passing) >= args.top_n:
        top = passing[: args.top_n]
    else:
        non_passing = [s for s in scored if not (s.get("hard_pass") and s.get("overall", 0) >= 60)]
        non_passing.sort(key=lambda x: x["overall"], reverse=True)
        top = passing + non_passing[: args.top_n - len(passing)]
    for c in top:
        c["strict_match"] = bool(c.get("hard_pass") and c.get("overall", 0) >= 60)
    logs.append(f"取前 {len(top)} 人（严格匹配 {sum(c['strict_match'] for c in top)} 人，其余为最接近人选）")
    print(f"  前 {len(top)} 人已选出")

    print(f"[3/4] 手机号恢复 ...")
    top = await recover_phones(top, client)
    recovered = sum(1 for c in top if c.get("phone_recovery", {}).get("status") in ("regex", "llm_text", "vision_needs_review"))
    logs.append(f"手机号恢复成功：{recovered} / {len(top)}")
    print(f"  恢复成功 {recovered} / {len(top)}")

    print(f"[4/4] 保存报告 ...")
    meta = {
        "jd_title": JD_SHILAI_FA.title,
        "generated_at": datetime.now().isoformat(),
        "total_parsed": len(candidates),
        "top_n": len(top),
    }
    full_json_path = output_dir / "fa_shilai_all_scored.json"
    full_json_path.write_text(
        json.dumps({"meta": {**meta, "top_n": len(top), "passing_count": len(passing)}, "data": scored}, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"  Full JSON: {full_json_path}")

    json_path = output_dir / "fa_shilai_top50.json"
    json_path.write_text(
        json.dumps({"meta": meta, "data": top}, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"  Top JSON: {json_path}")

    html_path = output_dir / "fa_shilai_report.html"
    render_html(top, JD_SHILAI_FA, html_path, logs)
    print(f"  HTML: {html_path}")

    print("\n完成。")
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
