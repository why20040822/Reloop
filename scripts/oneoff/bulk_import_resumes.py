#!/usr/bin/env python3
# ONE-OFF (2026-08-03)
# Input: inspect --help and the operator invocation record before running.
# Execution: do not rerun without explicit operator confirmation.

"""
批量导入脚本：从已接入的人才库 API / Source MySQL 拉取大量简历并写入本地 candidates 表。

支持的数据源
--------------
- source_mysql : 本地 Source MySQL 人才库（关键词模糊查询，分页）
- ttc_api      : TTC TalentStore API（关键词搜索 + 翻页 + 并发拉 profile_summary）

特性
----
- 分页/翻页拉取，可设置总目标数量
- 并发拉取 TTC profile_summary
- 写入本地 SQLite candidates 表
- 基于 phone / email / name+company / person_leads_id 去重
- 断点续传（进度文件 data/bulk_import_progress.json）
- 聚合报告与原始响应 JSON 备份

用法示例
--------
    # 1. 从 Source MySQL 批量导入 500 条
    python scripts/bulk_import_resumes.py --source mysql --keyword "AI" --max-resumes 500

    # 2. 从 TTC API 批量导入 1000 条（含 profile_summary）
    export TTC_JWT_TOKEN=eyJ...
    python scripts/bulk_import_resumes.py --source ttc --keyword "AI产品经理" --max-resumes 1000 --profiles --workers 8

    # 3. 空跑查看会导入多少条
    python scripts/bulk_import_resumes.py --source mysql --keyword "后端" --max-resumes 200 --dry-run
"""

import argparse
import json
import math
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
DEFAULT_OUTPUT_DIR = DATA_DIR / "bulk_import_resumes"
PROGRESS_FILE = DATA_DIR / "bulk_import_progress.json"

TTC_API_BASE = "https://api.ttcadvisory.com"
TTC_WEB_BASE = "https://app.ttcadvisory.com"

# 让脚本能导入 ttc_daemon 的本地 db 模块
from ttc_daemon import db as local_db  # noqa: E402


# ---------------------------------------------------------------------------
# Env / MySQL / TTC helpers（与 fetch_ttc_resumes.py 保持一致，独立可运行）
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
        read_timeout=60,
    )


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


# ---------------------------------------------------------------------------
# Source MySQL 拉取（分页）
# ---------------------------------------------------------------------------


def fetch_mysql_page(
    keyword: str,
    offset: int,
    batch_size: int,
) -> Tuple[List[Dict[str, Any]], int]:
    """从 Source MySQL 按关键词分页查询，返回 (本页记录, 总数)。"""
    terms = [term for term in re.split(r"\s+", keyword.strip()) if term]
    if not terms:
        raise ValueError("搜索关键词不能为空")

    term_clause = """
        (name LIKE %s OR raw_text LIKE %s OR current_role LIKE %s
         OR current_company LIKE %s OR JSON_SEARCH(skills, 'one', %s) IS NOT NULL)
    """
    where_sql = f"WHERE {' AND '.join(term_clause for _ in terms)}"

    count_sql = f"SELECT COUNT(*) AS total FROM candidates {where_sql}"
    select_sql = f"""
        SELECT id, name, raw_text, skills, years_experience, education,
               current_role, current_company, source, updated_at
        FROM candidates
        {where_sql}
        ORDER BY updated_at DESC
        LIMIT %s OFFSET %s
    """

    params: List[Any] = []
    for term in terms:
        like = f"%{term}%"
        params.extend([like, like, like, like, like])

    conn = get_mysql_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(count_sql, params)
            total = cur.fetchone()["total"]
            cur.execute(select_sql, params + [batch_size, offset])
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
    return rows, total


# ---------------------------------------------------------------------------
# TTC API 拉取（翻页 + 并发 profile_summary）
# ---------------------------------------------------------------------------


def search_ttc_talent_page(
    keyword: str,
    token: str,
    page: int,
    page_size: int,
) -> Tuple[List[Dict[str, Any]], int]:
    """调用 TTC TalentStore search 接口，返回 (本页 items, 总条数估计)。"""
    url = f"{TTC_API_BASE}/api/talent_store/v1/search"
    payload = {
        "keyword": keyword,
        "page_size": page_size,
        "current_page": page,
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
    if not isinstance(data, dict):
        return [], 0

    inner = data.get("data", {}) or {}
    total = inner.get("total") or inner.get("total_count") or inner.get("totalNum") or 0
    items = inner.get("person_leads_items", []) or []
    for item in items:
        item["source_type"] = "ttc_api"
        item["link"] = f"{TTC_WEB_BASE}/app/talent/{item.get('person_leads_id', '')}"
    return items, total


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


def fetch_ttc_profiles(items: List[Dict[str, Any]], token: str, workers: int) -> None:
    """并发为 items 拉取 profile_summary 并原地附加。"""
    if not items or not token:
        return

    def fetch_one(item: Dict[str, Any]) -> None:
        pid = item.get("person_leads_id")
        if not pid:
            return
        try:
            item["profile_summary"] = get_profile_summary(pid, token)
        except Exception as exc:
            item["profile_summary_error"] = str(exc)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(fetch_one, items))


# ---------------------------------------------------------------------------
# 标准化与去重
# ---------------------------------------------------------------------------


def _extract_phone(text: str) -> str:
    if not text:
        return ""
    m = re.search(r"1[3-9]\d{9}", str(text).replace(" ", "").replace("-", ""))
    return m.group(0) if m else ""


def _extract_email(text: str) -> str:
    if not text:
        return ""
    m = re.search(r"[\w.-]+@[\w.-]+\.\w+", str(text))
    return m.group(0) if m else ""


def _candidate_keys(candidate: Dict[str, Any]) -> Set[str]:
    """生成去重键集合。"""
    keys: Set[str] = set()

    # TTC API 唯一 ID
    pid = candidate.get("person_leads_id")
    if pid:
        keys.add(f"pid:{pid}")

    raw = candidate.get("raw_profile") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = {}

    # Source MySQL 原表 id
    sid = candidate.get("id") or raw.get("id")
    if sid:
        keys.add(f"sid:{sid}")

    name = (candidate.get("name") or "").strip()
    company = (candidate.get("current_company") or candidate.get("latest_company") or "").strip()
    if name:
        keys.add(f"name:{name.lower()}")
    if name and company:
        keys.add(f"name_company:{name.lower()}|{company.lower()}")

    # 联系方式
    phones = {candidate.get("phone", "").strip()}
    emails = {candidate.get("email", "").strip()}
    for text in [candidate.get("raw_text", ""), json.dumps(raw, ensure_ascii=False, default=str)]:
        phones.add(_extract_phone(text))
        emails.add(_extract_email(text))
    for p in phones:
        if p:
            keys.add(f"phone:{p}")
    for e in emails:
        if e:
            keys.add(f"email:{e.lower()}")

    return keys


def _serialize_value(value: Any) -> Any:
    """把不可 JSON 序列化的类型（如 datetime/date）转成字符串，便于写入 SQLite。"""
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_serialize_value(v) for v in value]
    return value


def build_local_candidate(source_record: Dict[str, Any]) -> Dict[str, Any]:
    """把 Source MySQL 或 TTC API 记录转换为本地 candidates 表结构。"""
    source_record = _serialize_value(source_record)
    source_type = source_record.get("source_type", "unknown")

    if source_type == "source_mysql":
        name = source_record.get("name", "")
        current_role = source_record.get("current_role", "")
        current_company = source_record.get("current_company", "")
        raw_text = source_record.get("raw_text", "")
        enriched = {
            "name": name,
            "current_role": current_role,
            "current_company": current_company,
            "years_experience": source_record.get("years_experience", ""),
            "education": source_record.get("education", ""),
            "skills": source_record.get("skills", []),
            "location": "",
            "source": source_record.get("source", ""),
            "updated_at": str(source_record.get("updated_at", "")),
        }
        return {
            "name": name,
            "phone": _extract_phone(raw_text),
            "email": _extract_email(raw_text),
            "source_types": ["source_mysql"],
            "raw_profile": source_record,
            "enriched_profile": enriched,
            "jd_alignment_score": 0.0,
            "gold_score": 0.0,
            "risk_flags": [],
            "overall_score": 0.0,
        }

    # TTC API
    cn_name = source_record.get("cn_name") or source_record.get("name", "")
    work = source_record.get("work_information") or []
    latest_work = work[0] if work else {}
    company = latest_work.get("company") or latest_work.get("formatted_company", "")
    title = source_record.get("job_title") or latest_work.get("job_title", "")
    raw_text = ""
    ps = source_record.get("profile_summary") or {}
    if isinstance(ps, dict):
        raw_text = ps.get("raw_resume_text") or ps.get("resume_text") or ""

    enriched = {
        "name": cn_name,
        "current_role": title,
        "current_company": company,
        "years_experience": "",
        "education": source_record.get("degree", ""),
        "skills": source_record.get("tags") or [],
        "location": source_record.get("locations_display") or source_record.get("locations", ""),
        "age": source_record.get("age", ""),
        "link": source_record.get("link", ""),
    }
    return {
        "name": cn_name,
        "phone": _extract_phone(raw_text),
        "email": _extract_email(raw_text),
        "source_types": ["ttc_api"],
        "raw_profile": source_record,
        "enriched_profile": enriched,
        "jd_alignment_score": 0.0,
        "gold_score": 0.0,
        "risk_flags": [],
        "overall_score": 0.0,
    }


def load_existing_keys() -> Set[str]:
    """加载本地 candidates 表已有记录的去重键。"""
    keys: Set[str] = set()
    local_db.init_db()
    with local_db.get_conn() as conn:
        rows = conn.execute("SELECT id, name, raw_profile FROM candidates").fetchall()
    for row in rows:
        cand = {
            "id": row["id"],
            "name": row["name"] or "",
            "raw_profile": row["raw_profile"] or {},
        }
        keys.update(_candidate_keys(cand))
    return keys


# ---------------------------------------------------------------------------
# 进度与报告
# ---------------------------------------------------------------------------


def load_progress() -> Dict[str, Any]:
    if not PROGRESS_FILE.exists():
        return {}
    try:
        return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_progress(progress: Dict[str, Any]) -> None:
    PROGRESS_FILE.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")


def _stable_id_for(source_record: Dict[str, Any]) -> str:
    """为 source_record 生成稳定 ID，用于断点续传跳过已处理项。"""
    source_type = source_record.get("source_type", "")
    if source_type == "ttc_api":
        pid = source_record.get("person_leads_id", "")
        return f"ttc:{pid}"
    sid = source_record.get("id", "")
    name = source_record.get("name", "")
    return f"mysql:{sid}:{name}"


def _write_report(
    output_dir: Path,
    keyword: str,
    source: str,
    total_fetched: int,
    imported: int,
    skipped: int,
    failed: int,
    elapsed: float,
    sample: List[Dict[str, Any]],
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    report = {
        "meta": {
            "keyword": keyword,
            "source": source,
            "generated_at": datetime.now().isoformat(),
            "elapsed_seconds": round(elapsed, 2),
            "total_fetched": total_fetched,
            "imported": imported,
            "skipped_duplicate": skipped,
            "failed": failed,
        },
        "sample": sample,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return report_path


# ---------------------------------------------------------------------------
# 批量导入主流程
# ---------------------------------------------------------------------------


def bulk_import_mysql(
    keyword: str,
    max_resumes: int,
    batch_size: int,
    existing_keys: Set[str],
    progress: Dict[str, Any],
    dry_run: bool,
) -> Tuple[int, int, int, int, List[Dict[str, Any]]]:
    """返回 (total_fetched, imported, skipped, failed, imported_records)。"""
    processed_ids: Set[str] = set(progress.get("processed_ids", []))
    imported_records: List[Dict[str, Any]] = []
    total_fetched = imported = skipped = failed = 0
    offset = progress.get("mysql_offset", 0)

    while total_fetched < max_resumes:
        current_batch = min(batch_size, max_resumes - total_fetched)
        try:
            rows, db_total = fetch_mysql_page(keyword, offset, current_batch)
        except Exception as exc:
            print(f"[ERROR] MySQL 查询失败 @ offset={offset}: {exc}")
            failed += 1
            break

        if not rows:
            print(f"[INFO] MySQL 无更多数据，offset={offset}，停止拉取")
            break

        print(f"[MySQL] offset={offset}, 本页 {len(rows)} 条，库中总数约 {db_total}")

        for row in rows:
            total_fetched += 1
            sid = _stable_id_for(row)
            if sid in processed_ids:
                skipped += 1
                continue

            local_cand = build_local_candidate(row)
            keys = _candidate_keys(local_cand)
            if keys & existing_keys:
                skipped += 1
                processed_ids.add(sid)
                continue

            if not dry_run:
                try:
                    local_db.insert_candidate(local_cand)
                    existing_keys.update(keys)
                    imported += 1
                    imported_records.append(local_cand)
                except Exception as exc:
                    print(f"[ERROR] 写入 candidates 失败: {exc}")
                    failed += 1
                    continue
            else:
                imported += 1
                imported_records.append(local_cand)

            processed_ids.add(sid)

        offset += len(rows)
        progress["mysql_offset"] = offset
        progress["processed_ids"] = sorted(processed_ids)
        save_progress(progress)

    return total_fetched, imported, skipped, failed, imported_records


def bulk_import_ttc(
    keyword: str,
    max_resumes: int,
    batch_size: int,
    workers: int,
    fetch_profiles: bool,
    token: str,
    existing_keys: Set[str],
    progress: Dict[str, Any],
    dry_run: bool,
) -> Tuple[int, int, int, int, List[Dict[str, Any]]]:
    imported_records: List[Dict[str, Any]] = []
    processed_ids: Set[str] = set(progress.get("processed_ids", []))
    total_fetched = imported = skipped = failed = 0
    page = progress.get("ttc_page", 1)

    while total_fetched < max_resumes:
        current_batch = min(batch_size, max_resumes - total_fetched)
        try:
            items, db_total = search_ttc_talent_page(keyword, token, page, current_batch)
        except Exception as exc:
            print(f"[ERROR] TTC API 搜索失败 @ page={page}: {exc}")
            failed += 1
            break

        if not items:
            print(f"[INFO] TTC API 无更多数据，page={page}，停止拉取")
            break

        print(f"[TTC] page={page}, 本页 {len(items)} 条，接口总条数约 {db_total}")

        if fetch_profiles:
            print(f"[TTC] 并发拉取 {len(items)} 条 profile_summary (workers={workers})...")
            fetch_ttc_profiles(items, token, workers)

        for item in items:
            total_fetched += 1
            sid = _stable_id_for(item)
            if sid in processed_ids:
                skipped += 1
                continue

            local_cand = build_local_candidate(item)
            keys = _candidate_keys(local_cand)
            if keys & existing_keys:
                skipped += 1
                processed_ids.add(sid)
                continue

            if not dry_run:
                try:
                    local_db.insert_candidate(local_cand)
                    existing_keys.update(keys)
                    imported += 1
                    imported_records.append(local_cand)
                except Exception as exc:
                    print(f"[ERROR] 写入 candidates 失败: {exc}")
                    failed += 1
                    continue
            else:
                imported += 1
                imported_records.append(local_cand)

            processed_ids.add(sid)

        page += 1
        progress["ttc_page"] = page
        progress["processed_ids"] = sorted(processed_ids)
        save_progress(progress)

    return total_fetched, imported, skipped, failed, imported_records


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    load_env()
    local_db.init_db()

    parser = argparse.ArgumentParser(description="批量导入人才库简历到本地 candidates 表")
    parser.add_argument("--source", choices=["mysql", "ttc", "all"], default="mysql",
                        help="数据源：mysql=Source MySQL, ttc=TTC TalentStore API, all=两者都跑")
    parser.add_argument("--keyword", default="AI产品经理", help="搜索关键词")
    parser.add_argument("--max-resumes", type=int, default=500, help="目标导入总数")
    parser.add_argument("--batch-size", type=int, default=100, help="每页条数（TTC 接口最大 100）")
    parser.add_argument("--workers", type=int, default=4, help="拉 TTC profile_summary 并发数")
    parser.add_argument("--profiles", action="store_true", help="同时拉取 TTC profile_summary")
    parser.add_argument("--dry-run", action="store_true", help="空跑，不写入数据库")
    parser.add_argument("--reset-progress", action="store_true", help="重置断点续传进度")
    parser.add_argument("--output-dir", type=str, default=str(DEFAULT_OUTPUT_DIR), help="报告与备份目录")
    parser.add_argument("--jwt", type=str, default="", help="TTC JWT Token（推荐环境变量 TTC_JWT_TOKEN）")
    args = parser.parse_args()

    if args.max_resumes < 1:
        parser.error("--max-resumes 必须 >= 1")
    if not 1 <= args.batch_size <= 100:
        parser.error("--batch-size 必须在 1 到 100 之间")

    token = args.jwt or os.getenv("TTC_JWT_TOKEN", "")

    progress: Dict[str, Any] = {}
    if args.reset_progress:
        save_progress({})
        print("[INFO] 已重置进度文件")
    else:
        progress = load_progress()

    # 若切换关键词/源，自动重置子进度，但保留全局去重记忆
    cache_key = f"{args.source}:{args.keyword}"
    if progress.get("cache_key") != cache_key:
        progress = {"processed_ids": progress.get("processed_ids", [])}
        progress["cache_key"] = cache_key
        save_progress(progress)

    print(f"[INFO] 数据源: {args.source}, 关键词: {args.keyword}, 目标: {args.max_resumes}, dry_run={args.dry_run}")
    start = time.time()

    existing_keys = load_existing_keys()
    print(f"[INFO] 本地 candidates 表已有 {len(existing_keys)} 个去重键")

    total_fetched = imported = skipped = failed = 0
    all_imported: List[Dict[str, Any]] = []

    sources = []
    if args.source in ("mysql", "all"):
        sources.append("mysql")
    if args.source in ("ttc", "all"):
        if not token:
            print("[ERROR] 调用 TTC API 需要 TTC_JWT_TOKEN，跳过 ttc 数据源")
        else:
            sources.append("ttc")

    per_source = math.ceil(args.max_resumes / len(sources)) if sources else args.max_resumes
    for src in sources:
        if total_fetched >= args.max_resumes:
            break
        remaining = min(per_source, args.max_resumes - total_fetched)
        if src == "mysql":
            tf, im, sk, fl, recs = bulk_import_mysql(
                args.keyword, remaining, args.batch_size, existing_keys, progress, args.dry_run
            )
        else:
            tf, im, sk, fl, recs = bulk_import_ttc(
                args.keyword, remaining, args.batch_size, args.workers,
                args.profiles, token, existing_keys, progress, args.dry_run
            )
        total_fetched += tf
        imported += im
        skipped += sk
        failed += fl
        all_imported.extend(recs)

    elapsed = time.time() - start
    sample = all_imported[:5]

    output_dir = Path(args.output_dir)
    report_path = _write_report(
        output_dir, args.keyword, args.source,
        total_fetched, imported, skipped, failed, elapsed, sample
    )

    # 备份本次导入的原始记录（仅真实导入时）
    if all_imported and not args.dry_run:
        backup_path = output_dir / f"imported_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path.write_text(
            json.dumps(all_imported, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"[OK] 原始记录备份: {backup_path}")

    print("\n" + "=" * 60)
    print(f"批量导入完成（dry_run={args.dry_run}）")
    print(f"  拉取总数: {total_fetched}")
    print(f"  成功导入: {imported}")
    print(f"  去重跳过: {skipped}")
    print(f"  失败:     {failed}")
    print(f"  耗时:     {elapsed:.2f}s")
    print(f"  报告:     {report_path}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
