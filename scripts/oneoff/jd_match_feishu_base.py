#!/usr/bin/env python3
# ONE-OFF (2026-08-03)
# Input: inspect --help and the operator invocation record before running.
# Execution: do not rerun without explicit operator confirmation.

"""
飞书多维表格 JD 匹配 + 简历 PDF 下载 + 马赛克手机号恢复

针对启承资本「消费品牌投后咨询」岗位：
1. 从飞书候选人主表读取所有记录；
2. 用 DeepSeek 按 JD 画像评分、排序；
3. 取前 50 名下载原始简历附件到本地；
4. 对无手机号或手机号被遮挡的 PDF 执行视觉恢复。

用法：
    cd /Users/ashley/Downloads/ttc的交易系统
    reloop/.venv/bin/python scripts/jd_match_feishu_base.py \
        --base-token "$TTC_FEISHU_BASE_TOKEN" \
        --table-id tblWFuBQrPmllE9W \
        --output-dir data/qicheng_feishu_match \
        --top-n 50 \
        --concurrency 5

环境依赖：
    - DEEPSEEK_API_KEY（已配置在 ~/.ttc/deepseek.env）
    - TTC_LLM_API_KEY / TTC_LLM_BASE_URL / TTC_LLM_VISION_MODEL（马赛克恢复）
    - lark-cli 已登录且有该 base 读取权限
"""

from __future__ import annotations

import argparse
import asyncio
import html as html_lib
import json
import os
import re
import subprocess
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
    max_years: float
    max_age: int
    require_degree: str
    jd_text: str
    scoring_dimensions: Tuple[str, ...]
    dimension_weights: Tuple[float, ...]
    must_have: Tuple[str, ...]
    preferred: Tuple[str, ...]


JD_QICHENG_CONSUMER = JdSpec(
    title="启承资本-消费品牌投后咨询",
    company="启承资本",
    location=None,
    min_years=3.0,
    max_years=5.0,
    max_age=32,
    require_degree="本科",
    jd_text="""启承资本 消费品牌投后咨询

职位职责：
1. 深度参与新消费品牌投后项目的策略共建，围绕产品定义、品牌定位及增长模式等关键维度，提供系统性战略支持。
2. 协助开展消费市场趋势、用户需求变化及竞争格局分析，提炼对品牌成长具有实际价值的洞察与策略方向。
3. 与创始团队及投后团队紧密协作，参与产品结构梳理、品牌表达优化及增长路径探讨，推动策略共识与业务协同。
4. 结合行业研究与业务实际，推动策略在具体产品落地或品牌动作中的有效执行与反馈闭环。
5. 持续跟踪消费行业动态与新品牌实践，积累案例经验，沉淀可复用的行业认知与策略方法论。

任职要求：
1. 3–5年工作经验，具备消费品牌、战略咨询或品牌策略相关背景者优先。对消费行业保持长期关注与浓厚兴趣，具备对品牌、产品与用户关系的独立思考与理解。
2. 具备良好的结构化思维能力，能够从市场、产品和品牌等多维视角进行综合分析。
3. 具备较强的沟通协作能力，能够与创业团队高效对话，推动策略共识与落地执行。
4. 思维开放、好奇心强，对新兴品牌与消费趋势保持敏锐感知与持续学习意愿。
5. 第一学历本科211起；年龄32岁以下。""",
    scoring_dimensions=(
        "消费品牌/战略咨询/品牌策略经验",
        "行业研究与策略分析能力",
        "结构化思维与跨维分析",
        "沟通协作与项目落地",
        "教育背景与稳定性",
    ),
    dimension_weights=(0.30, 0.25, 0.20, 0.15, 0.10),
    must_have=(
        "3-5年工作经验",
        "年龄32岁以下",
        "第一学历本科211及以上",
        "消费品牌、战略咨询、品牌策略或相关经验",
    ),
    preferred=(
        "头部消费品牌、咨询公司、投行或PE/VC投后经验",
        "具备产品定义、品牌定位、增长策略项目经验",
        "有创业团队沟通或项目落地经验",
        "对新兴品牌、消费趋势有持续研究",
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
    # 兼容当前会话里的 ANTHROPIC_* Kimi 配置
    if not os.environ.get("TTC_LLM_API_KEY"):
        for src, dst in [
            ("ANTHROPIC_API_KEY", "TTC_LLM_API_KEY"),
            ("ANTHROPIC_AUTH_TOKEN", "TTC_LLM_API_KEY"),
            ("ANTHROPIC_BASE_URL", "TTC_LLM_BASE_URL"),
            ("ANTHROPIC_MODEL", "TTC_LLM_MODEL"),
        ]:
            if os.environ.get(src) and not os.environ.get(dst):
                os.environ[dst] = os.environ[src]
    if os.environ.get("TTC_LLM_BASE_URL") and "/v1" not in os.environ["TTC_LLM_BASE_URL"]:
        os.environ["TTC_LLM_BASE_URL"] = os.environ["TTC_LLM_BASE_URL"].rstrip("/") + "/v1"


# ---------------------------------------------------------------------------
# 飞书 Base 读取（修正 lark-cli 返回的 field_id_list 顺序）
# ---------------------------------------------------------------------------

class FeishuBaseReader:
    """Read Feishu Bitable records via lark-cli, mapping by response field_id_list."""

    def __init__(self, base_token: str, table_id: str, view_id: Optional[str] = None):
        self.base_token = base_token
        self.table_id = table_id
        self.view_id = view_id
        self._field_map: Dict[str, str] = {}  # field_id -> name

    @staticmethod
    def _run_cli(*args: str) -> Dict[str, Any]:
        cmd = ["lark-cli", "base", *args, "--as", "user", "--format", "json"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"lark-cli failed: {result.stderr or result.stdout}")
        stdout = result.stdout.strip()
        if stdout.startswith("```"):
            lines = stdout.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            stdout = "\n".join(lines)
        if not stdout:
            return {}
        return json.loads(stdout)

    def _refresh_field_map(self) -> None:
        resp = self._run_cli(
            "+field-list",
            "--base-token", self.base_token,
            "--table-id", self.table_id,
        )
        fields = resp.get("data", {}).get("fields", []) if isinstance(resp, dict) else []
        self._field_map = {f["id"]: f["name"] for f in fields if "id" in f and "name" in f}

    def list_records(
        self,
        page_size: int = 200,
        ignore_view: bool = True,
    ) -> List[Dict[str, Any]]:
        if not self._field_map:
            self._refresh_field_map()

        records: List[Dict[str, Any]] = []
        offset = 0
        while True:
            args = [
                "+record-list",
                "--base-token", self.base_token,
                "--table-id", self.table_id,
                "--limit", str(page_size),
                "--offset", str(offset),
            ]
            if self.view_id and not ignore_view:
                args.extend(["--view-id", self.view_id])

            resp = self._run_cli(*args)
            data = resp.get("data", {}) or {}
            rows = data.get("data", [])
            field_id_list = data.get("field_id_list", [])
            record_id_list = data.get("record_id_list", [])
            if not rows:
                break

            for row_idx, row in enumerate(rows):
                if not isinstance(row, list):
                    continue
                record: Dict[str, Any] = {"_record_id": record_id_list[row_idx] if row_idx < len(record_id_list) else None}
                for idx, field_id in enumerate(field_id_list):
                    name = self._field_map.get(field_id, field_id)
                    record[name] = row[idx] if idx < len(row) else None
                records.append(record)

            offset += len(rows)
            if len(rows) < page_size:
                break
        return records


# ---------------------------------------------------------------------------
# 候选对象构建
# ---------------------------------------------------------------------------

def _first_attachment(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    val = record.get("原始简历附件")
    if isinstance(val, list) and val:
        return val[0]
    return None


def _norm_phone(value: Any) -> Optional[str]:
    if not value:
        return None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        return digits
    return None


def _extract_years(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_candidate(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """把飞书记录转成统一候选字典。"""
    name = (record.get("姓名") or "").strip()
    if not name:
        return None

    attachment = _first_attachment(record)
    phone = _norm_phone(record.get("手机号"))
    years = _extract_years(record.get("工作年限"))

    work_summary = record.get("工作经历摘要") or ""
    project_summary = record.get("项目经历摘要") or ""
    ai_parse_raw = record.get("AI解析原文") or ""
    ai_profile = record.get("AI人才画像") or ""
    consultant_notes = record.get("顾问备注") or ""

    raw_text = "\n\n".join(
        p for p in [ai_parse_raw, work_summary, project_summary, ai_profile, consultant_notes] if p
    )

    return {
        "source": "feishu_base",
        "record_id": record.get("_record_id"),
        "name": name,
        "phone": phone,
        "email": (record.get("邮箱") or "").strip(),
        "current_company": (record.get("当前公司") or "").strip(),
        "current_title": (record.get("当前岗位") or "").strip(),
        "current_location": (record.get("所在城市") or "").strip(),
        "school": (record.get("学校") or "").strip(),
        "major": (record.get("专业") or "").strip(),
        "degree": (record.get("学历") or "").strip() if isinstance(record.get("学历"), str) else "",
        "years_experience": years,
        "job_intent": (record.get("求职意向") or "").strip(),
        "expected_location": (record.get("期望地点") or "").strip(),
        "expected_salary": (record.get("期望薪资") or "").strip(),
        "current_salary": (record.get("当前薪资") or "").strip(),
        "skills": record.get("技能标签") or [],
        "work_experience_summary": work_summary,
        "project_experience_summary": project_summary,
        "consultant_notes": consultant_notes,
        "ai_profile": ai_profile,
        "raw_text": raw_text,
        "attachment": attachment,
        "has_attachment": bool(attachment),
    }


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

    return f"""你是一位资深猎头顾问，正在根据以下 JD 评估飞书人才库中的候选人。

岗位：{spec.title}

要求：
1. 先判断硬条件是否满足，再评估软性匹配。
2. 只根据资料中明确写出的经历打分，不要推测、不要脑补。
3. 工作年限需在 {spec.min_years}-{spec.max_years} 年之间；年龄需 ≤ {spec.max_age} 岁；学历需 {spec.require_degree} 及以上，且第一学历 211 起。
4. 如果资料中没有明确证据，必须记为 unknown，不得根据职称推断。
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
工作年限：{candidate.get('years_experience') if candidate.get('years_experience') is not None else '未知'}
当前公司：{candidate.get('current_company') or '未知'}
当前岗位：{candidate.get('current_title') or '未知'}
所在城市：{candidate.get('current_location') or '未知'}
学校/学历/专业：{candidate.get('school') or '未知'} / {candidate.get('degree') or '未知'} / {candidate.get('major') or '未知'}
求职意向：{candidate.get('job_intent') or '未知'}
技能标签：{', '.join(candidate.get('skills') or [])}

工作经历摘要：
{candidate.get('work_experience_summary') or '（未提供）'}

项目经历摘要：
{candidate.get('project_experience_summary') or '（未提供）'}

顾问备注/AI画像：
{candidate.get('ai_profile') or candidate.get('consultant_notes') or '（未提供）'}

完整原文：
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
                "hard_fail_reason": f"LLM 调用失败：{type(e).__name__}: {e}",
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
# 附件下载
# ---------------------------------------------------------------------------

def download_attachment(
    base_token: str,
    table_id: str,
    record_id: str,
    file_token: str,
    output_dir: Path,
    filename: str,
) -> Optional[Path]:
    """使用 lark-cli 下载单个附件到 output_dir。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r'[\\/:*?"<>|]', "_", filename).strip() or "resume.pdf"
    dest = output_dir / safe_name
    counter = 1
    while dest.exists():
        stem = Path(safe_name).stem
        suffix = Path(safe_name).suffix or ".pdf"
        dest = output_dir / f"{stem}_{counter}{suffix}"
        counter += 1

    cmd = [
        "lark-cli", "base", "+record-download-attachment",
        "--as", "user",
        "--base-token", base_token,
        "--table-id", table_id,
        "--record-id", record_id,
        "--file-token", file_token,
        "--output", str(dest),
        "--overwrite",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print(f"  下载失败：{result.stderr or result.stdout}")
        return None
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    return None


def download_top_attachments(
    candidates: List[Dict[str, Any]],
    base_token: str,
    table_id: str,
    output_dir: Path,
) -> List[Dict[str, Any]]:
    """为每位候选人下载原始简历附件。"""
    results: List[Dict[str, Any]] = []
    for i, c in enumerate(candidates, 1):
        record_id = c.get("record_id")
        attachment = c.get("attachment")
        if not record_id or not attachment:
            c["pdf_path"] = None
            c["download_error"] = "无 record_id 或附件" if not record_id else "无附件"
            results.append({
                "rank": i,
                "name": c.get("name"),
                "record_id": record_id,
                "file": None,
                "error": c["download_error"],
            })
            continue

        print(f"[{i}/{len(candidates)}] 下载 {c.get('name')} 的简历 ...", end=" ", flush=True)
        file_token = attachment.get("file_token")
        filename = attachment.get("name") or f"{c.get('name', 'unknown')}.pdf"
        try:
            path = download_attachment(base_token, table_id, record_id, file_token, output_dir, filename)
        except Exception as exc:
            path = None
            c["download_error"] = str(exc)
            print(f"ERROR {exc}")
        if path:
            c["pdf_path"] = str(path)
            print(f"-> {path.name}")
            results.append({"rank": i, "name": c.get("name"), "record_id": record_id, "file": str(path), "error": None})
        else:
            c["pdf_path"] = None
            error = c.get("download_error") or "下载失败"
            print(f"ERROR {error}")
            results.append({"rank": i, "name": c.get("name"), "record_id": record_id, "file": None, "error": error})
    return results


# ---------------------------------------------------------------------------
# 手机号恢复
# ---------------------------------------------------------------------------

PHONE_RE = re.compile(r"(?<![\d])1[3-9]\d{9}(?![\d])")


def _regex_phone(text: str) -> Optional[str]:
    if not text:
        return None
    m = PHONE_RE.search(text.replace(" ", "").replace("-", ""))
    return m.group(0) if m else None


def _phone_needs_recovery(candidate: Dict[str, Any]) -> bool:
    """手机号缺失、不规范或从文本中无法提取时，需要尝试恢复。"""
    phone = candidate.get("phone")
    if not phone:
        return True
    return False


def recover_phones_for_candidates(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """对本地 PDF 执行正则/OCR/视觉恢复。"""
    from reloop.parsing.mosaic_phone_recovery import recover_phone
    from reloop.parsing.unified_parser import parse_resume_file

    for c in candidates:
        pdf_path = c.get("pdf_path")
        if not pdf_path or not Path(pdf_path).is_file():
            c["phone_recovery"] = {"status": "no_pdf", "phone": None}
            continue
        path = Path(pdf_path)

        # 1. 如果 Base 里已有手机号，直接保留
        if c.get("phone"):
            c["phone_recovery"] = {"status": "already_in_base", "phone": c["phone"]}
            continue

        # 2. 解析 PDF 文本正则提取
        try:
            record = parse_resume_file(path)
        except Exception:
            record = None
        parser_name = record.parser_name if record else "paddleocr"
        raw_text = (record.raw_text or "") if record else ""

        phone = _regex_phone(raw_text)
        if phone:
            c["phone"] = phone
            c["phone_recovery"] = {"status": "regex_from_pdf", "phone": phone}
            continue

        # 3. 视觉马赛克恢复
        recovered = recover_phone(path, parser_name=parser_name)
        if recovered and recovered.phone:
            c["phone"] = recovered.phone
            c["phone_recovery"] = {
                "status": "vision_needs_review",
                "phone": recovered.phone,
                "confidence": recovered.confidence,
                "reasoning": recovered.reasoning,
            }
        else:
            c["phone_recovery"] = {"status": "failed", "phone": None}
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
        attachment = c.get("attachment") or {}
        rows.append({
            "rank": idx,
            "name": c.get("name", ""),
            "company": c.get("current_company", ""),
            "role": c.get("current_title", ""),
            "age": "未知",
            "exp": c.get("years_experience") if c.get("years_experience") is not None else "未知",
            "school": c.get("school", ""),
            "degree": c.get("degree", ""),
            "overall": c["overall"],
            "recommendation": c.get("recommendation", ""),
            "strict_match": "是" if c.get("hard_pass") and c.get("overall", 0) >= 60 else "否",
            "phone": c.get("phone") or "",
            "email": c.get("email") or "",
            "recovery": recovery_html,
            "evidence": c.get("evidence", ""),
            "dim_summary": dim_summary,
            "pdf": Path(c["pdf_path"]).name if c.get("pdf_path") else "",
            "attachment_name": attachment.get("name", ""),
        })

    trs = []
    for r in rows:
        trs.append(
            f"""<tr>
            <td>{safe(r['rank'])}</td>
            <td>{safe(r['name'])}</td>
            <td>{safe(r['company'])}</td>
            <td>{safe(r['role'])}</td>
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
            <td>{safe(r['pdf'])}</td>
            </tr>"""
        )

    logs_html = "<br>".join(safe(line) for line in logs)
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{safe(spec.title)} — 飞书人才库匹配报告</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 1.5rem; background: #fff; color: #212529; line-height: 1.6; }}
  h1 {{ font-size: 1.5rem; margin-bottom: .5rem; }}
  .meta {{ color: #6c757d; font-size: .875rem; margin-bottom: 1rem; }}
  .logs {{ background: #f8f9fa; border-left: 4px solid #0d6efd; padding: .75rem; margin: 1rem 0; font-size: .85rem; }}
  table {{ width: 100%; border-collapse: collapse; margin: 1rem 0; font-size: .75rem; }}
  th, td {{ padding: .35rem; text-align: left; border: 1px solid #dee2e6; vertical-align: top; }}
  th {{ background: #e9ecef; font-weight: 600; }}
  tr:nth-child(even) {{ background: #f8f9fa; }}
</style>
</head>
<body>
<h1>{safe(spec.title)} — 飞书人才库匹配报告</h1>
<div class="meta">入选 {len(ranked)} 人 · 生成时间 {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>
<div class="logs"><strong>执行日志：</strong><br>{logs_html}</div>

<h2>排名表</h2>
<div style="overflow-x:auto"><table>
<thead><tr>
  <th>排名</th><th>姓名</th><th>公司</th><th>岗位</th><th>年限</th><th>学校</th><th>学历</th>
  <th>得分</th><th>推荐</th><th>严格匹配</th><th>手机</th><th>邮箱</th>
  <th>恢复状态</th><th>证据</th><th>维度</th><th>本地PDF</th>
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
    parser = argparse.ArgumentParser(description="飞书 Base JD 匹配 + PDF 下载 + 手机号恢复")
    parser.add_argument("--base-token", default=os.environ.get("TTC_FEISHU_BASE_TOKEN", ""))
    parser.add_argument("--table-id", default="tblWFuBQrPmllE9W")
    parser.add_argument("--view-id", default=None)
    parser.add_argument("--output-dir", default=str(DATA_DIR / "qicheng_feishu_match"))
    parser.add_argument("--top-n", type=int, default=50)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--skip-download", action="store_true", help="跳过 PDF 下载")
    parser.add_argument("--skip-recovery", action="store_true", help="跳过手机号恢复")
    args = parser.parse_args()

    ds_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not ds_key:
        print("错误：未配置 DEEPSEEK_API_KEY", file=sys.stderr)
        return 1

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_dir = output_dir / "pdfs"
    logs: List[str] = []

    print("[1/5] 读取飞书人才库 ...")
    reader = FeishuBaseReader(args.base_token, args.table_id, args.view_id)
    try:
        records = reader.list_records(page_size=200, ignore_view=True)
    except Exception as exc:
        print(f"读取失败：{exc}", file=sys.stderr)
        return 1
    logs.append(f"飞书 Base 记录：{len(records)} 条")
    print(f"  读取 {len(records)} 条记录")

    candidates = [c for c in (build_candidate(r) for r in records) if c]
    logs.append(f"有效候选：{len(candidates)} 人")
    print(f"  有效候选 {len(candidates)} 人")

    print("[2/5] LLM 语义评分 ...")
    client = AsyncOpenAI(api_key=ds_key, base_url=DEEPSEEK_BASE_URL)
    sem = asyncio.Semaphore(args.concurrency)
    scored = await asyncio.gather(*(
        evaluate_candidate(client, c, JD_QICHENG_CONSUMER, sem) for c in candidates
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

    # 保存全量评分
    full_json_path = output_dir / "qicheng_all_scored.json"
    full_json_path.write_text(
        json.dumps({"meta": {"jd_title": JD_QICHENG_CONSUMER.title, "total": len(scored)}, "data": scored},
                   ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    if not args.skip_download:
        print("[3/5] 下载简历 PDF ...")
        download_report = download_top_attachments(top, args.base_token, args.table_id, pdf_dir)
        downloaded = sum(1 for r in download_report if r.get("file"))
        logs.append(f"PDF 下载成功：{downloaded} / {len(top)}")
        print(f"  下载成功 {downloaded} / {len(top)}")
        (output_dir / "download_report.json").write_text(
            json.dumps(download_report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
    else:
        logs.append("PDF 下载已跳过")
        print("  跳过下载")

    if not args.skip_recovery:
        print("[4/5] 手机号恢复 ...")
        # 只对无手机号的候选人执行恢复
        targets = [c for c in top if _phone_needs_recovery(c) and c.get("pdf_path")]
        if targets:
            print(f"  需要恢复：{len(targets)} 人")
            recover_phones_for_candidates(targets)
        recovered = sum(1 for c in top if c.get("phone"))
        logs.append(f"有手机号/恢复成功：{recovered} / {len(top)}")
        print(f"  有手机 {recovered} / {len(top)}")
    else:
        logs.append("手机号恢复已跳过")
        print("  跳过恢复")

    print("[5/5] 生成报告 ...")
    top_json_path = output_dir / "qicheng_top50.json"
    top_json_path.write_text(
        json.dumps({
            "meta": {
                "jd_title": JD_QICHENG_CONSUMER.title,
                "generated_at": datetime.now().isoformat(),
                "total_candidates": len(candidates),
                "strict_match_count": len(passing),
                "top_n": len(top),
            },
            "data": top,
        }, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    html_path = output_dir / "qicheng_report.html"
    render_html(top, JD_QICHENG_CONSUMER, html_path, logs)

    print(f"\n报告已保存：")
    print(f"  全量 JSON：{full_json_path}")
    print(f"  Top50 JSON：{top_json_path}")
    print(f"  HTML：{html_path}")
    if not args.skip_download:
        print(f"  PDF 目录：{pdf_dir}")
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
