#!/usr/bin/env python3
# ONE-OFF (2026-08-03)
# Input: inspect --help and the operator invocation record before running.
# Execution: do not rerun without explicit operator confirmation.

"""
对 ttc-talent-search 拉取的候选人做 JD 对齐评分，并生成 HTML/PDF 报告。
"""

import argparse
import html as html_lib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

BIG_TECH = [
    "蚂蚁集团", "阿里巴巴", "阿里", "腾讯", "字节跳动", "字节", "华为", "百度", "京东",
    "美团", "拼多多", "快手", "滴滴", "小米", "OPPO", "vivo", "Amazon", "Google",
    "微软", "Apple", "Meta", "Facebook", "Shopee", "Grab", "Uber", "Airbnb",
    "中金公司", "摩根士丹利", "高盛", "中金", "中科院", "复旦", "北大", "清华",
]


def is_big_tech(company: str) -> bool:
    return any(name in company for name in BIG_TECH)


def extract_age(education_text: str) -> int:
    """粗略推断年龄：本科 22 + 工作年限，硕士 25 + 工作年限。"""
    years = 0
    if "硕士" in education_text or "研究生" in education_text:
        years = 25
    elif "本科" in education_text:
        years = 22
    else:
        years = 22
    return years


@dataclass
class Dimension:
    name: str
    weight: float
    score: int = 0
    evidence: List[str] = field(default_factory=list)


@dataclass
class JdSpec:
    title: str
    company: str
    keywords: Dict[str, List[str]]
    weights: Dict[str, float]
    experience_range: Tuple[int, int]
    preferred_age_max: int = 100
    prefer_big_tech: bool = True
    require_ai_exp: bool = True


JD1 = JdSpec(
    title="瑞声科技-AI产品经理",
    company="瑞声科技",
    keywords={
        "AI 技术深度": ["LLM", "大模型", "多模态", "RAG", "AI Agent", "Agent", "Function Calling",
                       "工具调用", "工作流", "工具编排", "知识库", "LangChain", "业务流程自动化"],
        "B端/企业级经验": ["B端", "企业级", "ERP", "CRM", "OA", "采购", "人力", "经营管理",
                          "流程提效", "商业化", "toB", "TO B", "SaaS"],
        "工业/制造业背景": ["工业", "制造业", "制造", "工厂", "供应链", "生产", "硬件",
                            "IoT", "物联网", "智能硬件"],
        "产品交付能力": ["PRD", "原型", "流程设计", "业务规则", "验收标准", "产品规划",
                         "产品定义", "从0到1", "0-1", "0到1"],
        "跨团队协作": ["跨团队", "跨部门", "沟通", "协同", "研发", "算法", "数据", "交付",
                       "自驱", "自驱力"],
    },
    weights={
        "AI 技术深度": 0.25,
        "B端/企业级经验": 0.25,
        "工业/制造业背景": 0.15,
        "产品交付能力": 0.20,
        "跨团队协作": 0.10,
        "工作经验": 0.05,
    },
    experience_range=(3, 6),
    preferred_age_max=40,
    prefer_big_tech=True,
    require_ai_exp=True,
)

JD2 = JdSpec(
    title="荆华密算-用户产品经理",
    company="荆华密算",
    keywords={
        "C端/ToC 产品": ["C端", "ToC", "toc", "用户产品", "移动应用", "APP", "小程序",
                        "用户增长", "增长", "用户体验", "用户策略", "社区", "内容"],
        "大厂背景": [],  # 通过 is_big_tech 单独判断
        "数据与迭代": ["数据分析", "bad case", "用户反馈", "A/B测试", "AB测试", "实验",
                       "留存", "转化", "漏斗", "SQL", "Python"],
        "隐私/安全": ["隐私", "安全", "密态计算", "密码学", "数据安全", "隐私保护",
                       "可信计算", "联邦学习"],
        "产品交付能力": ["PRD", "原型", "交互方案", "产品定义", "从0到1", "0-1", "0到1"],
        "沟通协作": ["沟通", "协同", "跨团队", "跨部门", "研发", "设计", "运营"],
    },
    weights={
        "C端/ToC 产品": 0.25,
        "大厂背景": 0.20,
        "数据与迭代": 0.20,
        "隐私/安全": 0.10,
        "产品交付能力": 0.15,
        "沟通协作": 0.05,
        "工作经验": 0.05,
    },
    experience_range=(3, 10),
    preferred_age_max=32,
    prefer_big_tech=True,
    require_ai_exp=False,
)


def score_dimension(text: str, keywords: List[str], max_score: int = 100) -> Tuple[int, List[str]]:
    text_lower = text.lower()
    hits = 0
    evidence = []
    for kw in keywords:
        kl = kw.lower()
        if kl in text_lower:
            hits += text_lower.count(kl)
            # 从 raw_text 中找包含该关键词的上下文
            for line in text.splitlines():
                if kl in line.lower() and line.strip() not in evidence:
                    evidence.append(line.strip())
                    break
    # 非线性缩放，避免关键词堆砌满分
    score = min(max_score, int(30 + 25 * min(hits, 6) ** 0.7))
    return score, evidence[:3]


def score_experience(years: int, spec: JdSpec) -> Tuple[int, str]:
    lo, hi = spec.experience_range
    if lo <= years <= hi:
        return 100, f"{years} 年，符合 {lo}-{hi} 年要求"
    if years < lo:
        # 差 1 年以内可接受
        if lo - years <= 1:
            return 70, f"{years} 年，接近 {lo} 年要求"
        return max(20, 60 - (lo - years) * 15), f"{years} 年，低于 {lo} 年要求"
    # years > hi
    if years - hi <= 2:
        return 80, f"{years} 年，略超 {hi} 年要求"
    return 50, f"{years} 年，明显超过 {hi} 年要求"


def evaluate(candidate: Dict[str, Any], spec: JdSpec) -> Dict[str, Any]:
    text = "\n".join([
        candidate.get("raw_text", ""),
        candidate.get("current_role", ""),
        candidate.get("current_company", ""),
        candidate.get("education", ""),
        " ".join(candidate.get("skills", [])),
    ])

    dimensions: List[Dict[str, Any]] = []
    weighted_sum = 0.0
    total_weight = 0.0

    for dim_name, weight in spec.weights.items():
        if dim_name == "工作经验":
            years = candidate.get("years_experience") or 0
            score, evidence_text = score_experience(int(years), spec)
            evidence = [evidence_text]
        elif dim_name == "大厂背景":
            company = candidate.get("current_company", "")
            score = 100 if is_big_tech(company) else 40
            evidence = [f"当前公司：{company}"] if company else ["无公司信息"]
        else:
            kws = spec.keywords.get(dim_name, [])
            score, evidence = score_dimension(text, kws)
        dimensions.append({
            "name": dim_name,
            "weight": weight,
            "score": score,
            "evidence": evidence,
        })
        weighted_sum += score * weight
        total_weight += weight

    # 年龄惩罚/加分（仅 JD2 严格）
    age_note = ""
    if spec.preferred_age_max < 100:
        inferred_age = extract_age(candidate.get("education", "")) + int(candidate.get("years_experience") or 0)
        if inferred_age > spec.preferred_age_max:
            age_penalty = min(15, (inferred_age - spec.preferred_age_max) * 3)
            weighted_sum -= age_penalty
            age_note = f"推断年龄约 {inferred_age} 岁，超出 {spec.preferred_age_max} 岁上限，扣 {age_penalty:.1f} 分"
        else:
            age_note = f"推断年龄约 {inferred_age} 岁，符合年龄要求"

    overall = max(0.0, min(100.0, weighted_sum / total_weight if total_weight else 0))

    if overall >= 80:
        recommendation = "强推"
    elif overall >= 65:
        recommendation = "建议沟通"
    elif overall >= 50:
        recommendation = "备选"
    else:
        recommendation = "不匹配"

    return {
        "candidate_id": candidate.get("id", ""),
        "name": candidate.get("name", ""),
        "current_company": candidate.get("current_company", ""),
        "current_role": candidate.get("current_role", ""),
        "years_experience": candidate.get("years_experience", ""),
        "education": candidate.get("education", ""),
        "skills": candidate.get("skills", []),
        "raw_text": candidate.get("raw_text", ""),
        "overall": round(overall, 1),
        "recommendation": recommendation,
        "age_note": age_note,
        "dimensions": dimensions,
    }


def render_report(results: Dict[str, List[Dict[str, Any]]], candidates: List[Dict[str, Any]],
                  output: Path, title: str = "JD 对齐评分报告") -> None:
    def safe(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (list, tuple, set)):
            value = ", ".join(str(item) for item in value)
        return html_lib.escape(str(value), quote=True)

    sections = []
    for spec, scored in results.items():
        rows = []
        for rank, r in enumerate(scored, 1):
            dim_summary = "<br>".join(
                f"{d['name']} ({d['weight']:.0%}): {d['score']}"
                for d in r["dimensions"]
            )
            evidence_summary = "<br>".join(
                safe(line) for d in r["dimensions"] for line in d["evidence"][:2]
            )
            rows.append({
                "rank": rank,
                "name": r["name"],
                "company": r["current_company"],
                "role": r["current_role"],
                "exp": r["years_experience"],
                "education": r["education"],
                "skills": ", ".join(r["skills"][:6]),
                "overall": r["overall"],
                "recommendation": r["recommendation"],
                "age_note": r["age_note"],
                "dim_summary": dim_summary,
                "evidence_summary": evidence_summary,
                "raw_text": r["raw_text"].replace("\n", "<br>"),
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
                <td>{safe(r['education'])}</td>
                <td>{safe(r['skills'])}</td>
                <td><strong>{safe(r['overall'])}</strong></td>
                <td>{safe(r['recommendation'])}</td>
                <td>{r['age_note']}</td>
                <td>{r['dim_summary']}</td>
                <td>{r['evidence_summary']}</td>
                </tr>"""
            )

        detail_sections = []
        for r in rows:
            detail_sections.append(
                f"""<div class="detail">
                <h3>#{safe(r['rank'])} {safe(r['name'])} — {safe(r['company'])} — 综合得分 {safe(r['overall'])}</h3>
                <p><strong>当前职位：</strong>{safe(r['role'])} | <strong>工作年限：</strong>{safe(r['exp'])} | <strong>学历：</strong>{safe(r['education'])}</p>
                <p><strong>技能：</strong>{safe(r['skills'])}</p>
                <p><strong>推荐：</strong>{safe(r['recommendation'])} | {r['age_note']}</p>
                <p><strong>简历原文：</strong></p>
                <div class="raw">{r['raw_text']}</div>
                <h4>各维度得分</h4>
                <ul>{''.join(f"<li><strong>{safe(d['name'])}</strong> (权重 {d['weight']:.0%}): {safe(d['score'])}<br><em>{'<br>'.join(safe(line) for line in d['evidence'][:3])}</em></li>" for d in scored[r['rank']-1]['dimensions'])}</ul>
                </div>"""
            )

        sections.append(
            f"""<section>
            <h2>{safe(spec)}</h2>
            <p>共 {len(rows)} 位候选人 · 按综合得分排序</p>
            <div style="overflow-x:auto"><table>
            <thead><tr>
                <th>排名</th><th>姓名</th><th>当前公司</th><th>当前职位</th><th>年限</th><th>学历</th><th>技能</th><th>综合得分</th><th>推荐</th><th>年龄备注</th><th>维度得分</th><th>关键证据</th>
            </tr></thead>
            <tbody>{''.join(trs)}</tbody>
            </table></div>
            <h3>完整简历明细</h3>
            {''.join(detail_sections)}
            </section>"""
        )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{safe(title)}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; margin: 2rem; background: #fff; color: #212529; line-height: 1.6; }}
  h1 {{ font-size: 1.6rem; margin-bottom: .5rem; }}
  h2 {{ font-size: 1.3rem; margin-top: 2rem; border-bottom: 2px solid #dee2e6; padding-bottom: .25rem; }}
  h3 {{ font-size: 1.1rem; margin-top: 1.5rem; }}
  .meta {{ color: #6c757d; font-size: .875rem; margin-bottom: 1rem; }}
  table {{ width: 100%; border-collapse: collapse; margin: 1rem 0; font-size: .8rem; }}
  th, td {{ padding: .5rem; text-align: left; border: 1px solid #dee2e6; vertical-align: top; }}
  th {{ background: #e9ecef; font-weight: 600; }}
  tr:nth-child(even) {{ background: #f8f9fa; }}
  .detail {{ background: #f8f9fa; border: 1px solid #dee2e6; border-radius: 6px; padding: 1rem; margin: 1rem 0; }}
  .raw {{ background: #fff; border: 1px solid #dee2e6; padding: .75rem; border-radius: 4px; font-size: .85rem; white-space: pre-wrap; }}
  .warning {{ background: #fff3cd; border-left: 4px solid #ffc107; padding: .75rem; margin: 1rem 0; }}
</style>
</head>
<body>
<h1>{safe(title)}</h1>
<div class="meta">候选人总数 {len(candidates)} · 生成时间 {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>
<div class="warning">
<strong>数据说明：</strong>当前结果来自 Source MySQL 本地人才库，部分字段（如 base 地、B/C 端、行业背景）缺失，评分基于现有字段（公司、年限、技能、简历文本）进行关键词匹配，仅供参考。建议配置 TTC JWT Token 后调用 TalentStore API 获取更完整数据。
</div>
{''.join(sections)}
</body>
</html>"""
    output.write_text(html, encoding="utf-8")


def html_to_pdf(html_path: Path, pdf_path: Path) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(f"file://{html_path.resolve()}")
        page.wait_for_load_state("networkidle")
        # 设置较大页面以容纳宽表格
        page.pdf(
            path=str(pdf_path),
            format="A3",
            margin={"top": "1cm", "right": "1cm", "bottom": "1cm", "left": "1cm"},
            print_background=True,
        )
        browser.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="JD 对齐评分报告生成")
    parser.add_argument("--input", type=str, default=str(DATA_DIR / "ttc_ai_pm_shenzhen.json"), help="候选人 JSON 文件")
    parser.add_argument("--output-html", type=str, default=str(DATA_DIR / "ttc_jd_match_report.html"), help="输出 HTML 路径")
    parser.add_argument("--output-pdf", type=str, default=str(DATA_DIR / "ttc_jd_match_report.pdf"), help="输出 PDF 路径")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"错误：输入文件不存在 {input_path}", file=os.sys.stderr)
        return 1

    candidates = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(candidates, list):
        print("错误：输入 JSON 应为候选人列表", file=os.sys.stderr)
        return 1

    results: Dict[str, List[Dict[str, Any]]] = {}
    for spec in [JD1, JD2]:
        scored = [evaluate(c, spec) for c in candidates]
        scored.sort(key=lambda x: x["overall"], reverse=True)
        results[f"{spec.title}（{spec.company}）"] = scored

    # 同时保存评分 JSON
    json_path = Path(args.output_pdf).with_suffix(".json")
    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    html_path = Path(args.output_html)
    render_report(results, candidates, html_path, title="TTC AI 产品经理 JD 对齐评分报告")
    print(f"[OK] HTML 报告：{html_path}")

    pdf_path = Path(args.output_pdf)
    try:
        html_to_pdf(html_path, pdf_path)
        print(f"[OK] PDF 报告：{pdf_path}")
    except Exception as e:
        print(f"[WARN] PDF 生成失败：{e}", file=os.sys.stderr)
        print(f"[INFO] 可手动用浏览器打开 HTML 打印为 PDF", file=os.sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
