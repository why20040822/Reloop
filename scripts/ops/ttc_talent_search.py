#!/usr/bin/env python3
"""
TTC TalentSearch 数据拉取与比赛结果展示脚本

用法示例：
    # 1. 只查 Source MySQL 本地人才库
    source ~/.ttc/mysql.env
    python scripts/ops/ttc_talent_search.py --source-only --keyword "AI产品经理" --limit 20

    # 2. 调用 TTC TalentStore API（需要提供 JWT）
    export TTC_JWT_TOKEN=eyJhbGciOiJIUzI1Ni...
    python scripts/ops/ttc_talent_search.py --keyword "AI产品经理 北京" --limit 20 --output data/ttc_search_results.html

    # 3. 同时拉取水下信息并生成 HTML
    python scripts/ops/ttc_talent_search.py --keyword "后端" --limit 10 --profiles --output data/ttc_search_results.html
"""

import argparse
import html as html_lib
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

TTC_API_BASE = "https://api.ttcadvisory.com"
TTC_WEB_BASE = "https://app.ttcadvisory.com"


def _parse_env_file(path: Path) -> Dict[str, str]:
    """解析 export KEY=VALUE 或 KEY=VALUE 格式的 env 文件（不处理转义）。"""
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
    """加载 repo .env 与 ~/.ttc/mysql.env 到 os.environ（不覆盖已存在变量）。"""
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


def query_source_db(keyword: str, limit: int = 20) -> List[Dict[str, Any]]:
    """从 Source MySQL 人才库按关键词模糊查询。"""
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


def search_ttc_talent(keyword: str, token: str, limit: int = 20) -> List[Dict[str, Any]]:
    """调用 TTC TalentStore /api/talent_store/v1/search。"""
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
    """获取人才水下信息（profile_summary）。"""
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


def render_html(items: List[Dict[str, Any]], output: Path, title: str = "TTC 人才搜索比赛结果") -> None:
    def safe(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (list, tuple, set)):
            value = ", ".join(str(item) for item in value)
        return html_lib.escape(str(value), quote=True)

    rows = []
    for idx, item in enumerate(items, 1):
        if item.get("source_type") == "source_mysql":
            rows.append({
                "rank": idx,
                "source": "Source MySQL",
                "name": item.get("name", ""),
                "age": "-",
                "title": item.get("current_role", ""),
                "company": item.get("current_company", ""),
                "location": "-",
                "degree": item.get("education", ""),
                "skills": ", ".join(item.get("skills", [])[:5]),
                "experience": item.get("years_experience", ""),
                "updated": str(item.get("updated_at", "")),
                "link": item.get("link", ""),
                "summary": (item.get("raw_text") or "")[:120],
            })
        else:
            work = item.get("work_information") or []
            latest_work = work[0] if work else {}
            rows.append({
                "rank": idx,
                "source": "TTC TalentStore",
                "name": item.get("cn_name", item.get("name", "")),
                "age": item.get("age", "-"),
                "title": item.get("job_title", latest_work.get("job_title", "")),
                "company": latest_work.get("company", "") or latest_work.get("formatted_company", ""),
                "location": item.get("locations_display", item.get("locations", "")),
                "degree": item.get("degree", ""),
                "skills": ", ".join((item.get("tags") or [])[:5]),
                "experience": "-",
                "updated": "-",
                "link": item.get("link", ""),
                "summary": "",
            })

    thead = "".join(f"<th>{h}</th>" for h in ["排名", "数据源", "姓名", "年龄", "职位", "公司", "地点", "学历", "标签/技能", "经验", "更新时间", "详情链接"])
    trs = []
    for r in rows:
        link_cell = f'<a href="{safe(r["link"])}" target="_blank" rel="noopener noreferrer">打开</a>' if r["link"] else "-"
        trs.append(
            f"<tr><td>{safe(r['rank'])}</td><td>{safe(r['source'])}</td><td>{safe(r['name'])}</td><td>{safe(r['age'])}</td><td>{safe(r['title'])}</td>"
            f"<td>{safe(r['company'])}</td><td>{safe(r['location'])}</td><td>{safe(r['degree'])}</td>"
            f"<td>{safe(r['skills'])}</td><td>{safe(r['experience'])}</td><td>{safe(r['updated'])}</td><td>{link_cell}</td></tr>"
        )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{safe(title)}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; margin: 2rem; background: #f8f9fa; color: #212529; }}
  h1 {{ font-size: 1.5rem; margin-bottom: .5rem; }}
  .meta {{ color: #6c757d; font-size: .875rem; margin-bottom: 1rem; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,.1); }}
  th, td {{ padding: .75rem; text-align: left; border-bottom: 1px solid #dee2e6; font-size: .875rem; }}
  th {{ background: #e9ecef; font-weight: 600; }}
  tr:hover {{ background: #f1f3f5; }}
  a {{ color: #0d6efd; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
<h1>{safe(title)}</h1>
<div class="meta">共 {len(rows)} 条结果 · 生成时间 {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>
<div style="overflow-x:auto"><table>
<thead><tr>{thead}</tr></thead>
<tbody>{''.join(trs)}</tbody>
</table></div>
</body>
</html>"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser(description="TTC 人才搜索与比赛结果展示")
    parser.add_argument("--keyword", required=True, help="搜索关键词")
    parser.add_argument("--limit", type=int, default=20, help="返回数量")
    parser.add_argument("--output", type=str, default=str(DATA_DIR / "ttc_search_results.html"), help="输出 HTML 路径")
    parser.add_argument("--json-output", type=str, default="", help="同时输出 JSON 路径")
    parser.add_argument("--profiles", action="store_true", help="同时拉取 TTC 水下信息")
    parser.add_argument("--source-only", action="store_true", help="仅查询 Source MySQL，不调用 TTC API")
    parser.add_argument("--jwt", type=str, default="", help="TTC JWT Token（推荐改用 TTC_JWT_TOKEN 环境变量）")
    args = parser.parse_args()

    if not 1 <= args.limit <= 100:
        parser.error("--limit 必须在 1 到 100 之间")
    token = args.jwt or os.getenv("TTC_JWT_TOKEN", "")

    items: List[Dict[str, Any]] = []
    if args.source_only:
        print(f"[Source MySQL] 查询关键词：{args.keyword}")
        items = query_source_db(args.keyword, args.limit)
    else:
        if not token:
            print("错误：调用 TTC API 需要提供 JWT Token。", file=sys.stderr)
            print("请登录 TTC 后将 JWT 写入 ~/.ttc/ttc_jwt.env，或设置环境变量 TTC_JWT_TOKEN。", file=sys.stderr)
            return 1
        print(f"[TTC API] 查询关键词：{args.keyword}")
        items = search_ttc_talent(args.keyword, token, args.limit)
        if args.profiles:
            for item in items:
                pid = item.get("person_leads_id")
                if pid:
                    item["profile_summary"] = get_profile_summary(pid, token)

    out_path = Path(args.output)
    render_html(items, out_path, title=f"TTC 人才搜索：{args.keyword}")
    print(f"[OK] HTML 结果已保存：{out_path}")

    if args.json_output:
        json_path = Path(args.json_output)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(items, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"[OK] JSON 结果已保存：{json_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
