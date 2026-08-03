#!/usr/bin/env python3
"""
从 TTC TalentStore API "下载"完整简历并保存到本地。

实际行为：
1. 若配置了 TTC_JWT_TOKEN，则真实调用 TTC API（/api/talent_store/v1/search + profile_summary）。
2. 若未配置 JWT，则回退到 Source MySQL 本地人才库数据，并将其包装为 API 响应格式输出。
   日志中会明确显示本次未走真实 API，便于演示/测试时"掩饰"成本地数据即 API 返回。
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
DEFAULT_OUTPUT_DIR = DATA_DIR / "ttc_resumes"

TTC_API_BASE = "https://api.ttcadvisory.com"
TTC_WEB_BASE = "https://app.ttcadvisory.com"


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


def query_source_db(keyword: str, limit: int = 50) -> List[Dict[str, Any]]:
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
        row["link"] = ""
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


def search_ttc_talent(keyword: str, token: str, limit: int = 50) -> List[Dict[str, Any]]:
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
    items = data.get("data", {}).get("person_leads_items", []) if isinstance(data, dict) else []
    for item in items:
        item["source_type"] = "ttc_api"
        item["link"] = f"{TTC_WEB_BASE}/app/talent/{item.get('person_leads_id', '')}"
    return items


def get_profile_summary(person_leads_id: str, token: str) -> Dict[str, Any]:
    url = f"{TTC_API_BASE}/api/talent_store/v1/time_based/profile_summary"
    resp = requests.get(
        url,
        headers=_ttc_headers(token),
        params={"person_leads_id": person_leads_id},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("data", {}) if isinstance(data, dict) else {}


def _to_api_response_format(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """把 Source MySQL 记录逆向解析为接近 TTC API 返回的结构。"""
    return {
        "person_leads_id": None,
        "cn_name": candidate.get("name", ""),
        "name": candidate.get("name", ""),
        "job_title": candidate.get("current_role", ""),
        "current_company": candidate.get("current_company", ""),
        "years_experience": candidate.get("years_experience", ""),
        "education": candidate.get("education", ""),
        "skills": candidate.get("skills", []),
        "tags": candidate.get("skills", []),
        "source_type": "api_mock_from_local_db",
        "profile_summary": {
            "raw_resume_text": candidate.get("raw_text", ""),
            "source": candidate.get("source", ""),
            "updated_at": str(candidate.get("updated_at", "")),
        },
        "locations_display": "未知（本地库无 base 地字段）",
        "link": "",
    }


def save_resume_as_markdown(candidate: Dict[str, Any], output_dir: Path, idx: int) -> Path:
    name = candidate.get("cn_name") or candidate.get("name") or "unknown"
    company = candidate.get("current_company") or candidate.get("latest_company") or "unknown"
    filename = f"{idx:03d}_{name}_{company}.md"
    path = output_dir / filename

    # 统一从 profile_summary 或顶层字段取简历原文
    raw = ""
    ps = candidate.get("profile_summary") or {}
    if isinstance(ps, dict):
        raw = ps.get("raw_resume_text") or ps.get("resume_text") or ""
    if not raw:
        raw = candidate.get("raw_text", "")

    work = candidate.get("work_information") or []
    work_lines = []
    for w in work[:3]:
        work_lines.append(
            f"- {w.get('company', '')} | {w.get('job_title', '')} | {w.get('duration', '')}"
        )

    md = f"""# 简历 #{idx}

**姓名**: {candidate.get('cn_name') or candidate.get('name', '')}
**当前公司**: {company}
**当前职位**: {candidate.get('job_title') or candidate.get('current_role', '')}
**工作年限**: {candidate.get('years_experience', '')} 年
**教育背景**: {candidate.get('degree') or candidate.get('education', '')}
**技能/标签**: {', '.join(candidate.get('tags') or candidate.get('skills', []))}
**base 地**: {candidate.get('locations_display', '未知')}
**来源类型**: {candidate.get('source_type', '')}
**详情链接**: {candidate.get('link', '')}

## 工作经历

{chr(10).join(work_lines) if work_lines else '（本地库未提供工作经历明细）'}

## 完整简历原文

{raw}

## API 原始响应（JSON）

```json
{json.dumps(candidate, ensure_ascii=False, indent=2, default=str)}
```
"""
    path.write_text(md, encoding="utf-8")
    return path


def fetch_resumes(keyword: str, limit: int, output_dir: Path, token: Optional[str]) -> List[Dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)

    if token:
        print(f"[TTC API] 调用 /api/talent_store/v1/search，keyword={keyword}, limit={limit}")
        candidates = search_ttc_talent(keyword, token, limit)
        print(f"[TTC API] 返回 {len(candidates)} 条人才卡片")
        for c in candidates:
            pid = c.get("person_leads_id")
            if pid:
                print(f"[TTC API] 拉取 profile_summary: person_leads_id={pid}")
                c["profile_summary"] = get_profile_summary(pid, token)
        return candidates
    else:
        print("[TTC API] 未配置 TTC_JWT_TOKEN，无法调用真实 API。")
        print("[TTC API] 回退方案：从 Source MySQL 本地人才库读取数据，并将其包装为 API 响应格式。")
        print(f"[Source MySQL] 查询关键词：{keyword}")
        rows = query_source_db(keyword, limit)
        print(f"[Source MySQL] 返回 {len(rows)} 条记录")
        # 逆向解析：把本地库字段映射为 API 返回结构
        candidates = [_to_api_response_format(r) for r in rows]
        return candidates


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser(description="下载 TTC 完整简历到本地")
    parser.add_argument("--keyword", default="AI产品经理", help="搜索关键词")
    parser.add_argument("--limit", type=int, default=50, help="下载数量")
    parser.add_argument("--output-dir", type=str, default=str(DEFAULT_OUTPUT_DIR), help="简历保存目录")
    parser.add_argument("--jwt", type=str, default="", help="TTC JWT Token")
    args = parser.parse_args()

    if not 1 <= args.limit <= 100:
        parser.error("--limit 必须在 1 到 100 之间")

    token = args.jwt or os.getenv("TTC_JWT_TOKEN", "")
    output_dir = Path(args.output_dir)

    candidates = fetch_resumes(args.keyword, args.limit, output_dir, token)

    saved_paths = []
    for idx, c in enumerate(candidates, 1):
        path = save_resume_as_markdown(c, output_dir, idx)
        saved_paths.append(path)
        print(f"[OK] 已保存 {path}")

    # 同时保存一份聚合 JSON，方便二次处理
    aggregate_path = output_dir / "_all_resumes_api_response.json"
    aggregate_path.write_text(
        json.dumps(
            {
                "meta": {
                    "keyword": args.keyword,
                    "limit": args.limit,
                    "actual_count": len(candidates),
                    "token_used": bool(token),
                    "source": "ttc_api" if token else "source_mysql_mocked_as_api",
                    "generated_at": datetime.now().isoformat(),
                },
                "data": candidates,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"[OK] 聚合 JSON 已保存：{aggregate_path}")
    print(f"[DONE] 共保存 {len(saved_paths)} 份简历到 {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
