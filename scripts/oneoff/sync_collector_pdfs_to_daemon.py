#!/usr/bin/env python3
# ONE-OFF (2026-08-03)
# Input: inspect --help and the operator invocation record before running.
# Execution: do not rerun without explicit operator confirmation.

"""
把 reloop 中已保存的 PDF 附件路径同步到 ttc_daemon.db。

reloop 在 /api/import-file 入口会把上传的 PDF 持久化到
`reloop/data/attachments/`，并把路径存在自己的 `candidates.attachment_path`。

本脚本读取该表，按 phone / email / name+company / name 匹配 ttc_daemon 的 candidates，
并把 PDF 路径写到 `ttc_daemon.db.candidates.original_attachment_path`。

用法
----
    python scripts/sync_collector_pdfs_to_daemon.py --dry-run
    python scripts/sync_collector_pdfs_to_daemon.py --write

可选：扫描本地附件目录直接匹配（不依赖 reloop.db）
    python scripts/sync_collector_pdfs_to_daemon.py --scan-dir reloop/data/attachments --write
"""

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]

from ttc_daemon import db as local_db

COLLECTOR_DB = REPO_ROOT / "reloop" / "data" / "candidates.db"
COLLECTOR_ATTACHMENTS = REPO_ROOT / "reloop" / "data" / "attachments"
GMAIL_ATTACHMENTS = REPO_ROOT / "reloop" / "data" / "gmail-attachments"


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


_NAME_STOP_WORDS = {"北京", "上海", "深圳", "广州", "杭州", "成都", "苏州", "南京",
                    "简历", "个人", "在线", "最新", "版本", "最终", "正式", "工作",
                    "经验", "年限", "附件", "未命名"}


def _extract_name_from_filename(filename: str) -> str:
    """从文件名猜测姓名，例如 20260712163004_张三.pdf。"""
    base = Path(filename).stem
    # 去掉常见时间戳前缀
    base = re.sub(r"^\d{14,}_", "", base)
    base = re.sub(r"^\d{8}_", "", base)
    # 如果去掉时间戳后整个就是姓名
    if re.fullmatch(r"[一-鿿·]{2,6}", base) and base not in _NAME_STOP_WORDS:
        return base
    # 尝试 【岗位_地点_薪资】姓名_年限.pdf 或 简历_姓名.pdf
    for pattern in [
        r"[】\]]\s*([一-鿿·]{2,6})(?:\s*[-_ ]?\s*\d+年)?$",
        r"简历[_\-]?([一-鿿·]{2,6})$",
        r"^([一-鿿·]{2,6})[-_](?:个人简历|简历)$",
        r"[-_]([一-鿿·]{2,6})$",
    ]:
        m = re.search(pattern, base, re.I)
        if m:
            name = m.group(1)
            if name not in _NAME_STOP_WORDS:
                return name
    return ""


def _extract_pdf_text(path: Path) -> str:
    """从 PDF 提取文本，失败返回空字符串。"""
    try:
        import fitz
        doc = fitz.open(path)
        parts = []
        for page in doc:
            text = page.get_text("text").strip()
            if text:
                parts.append(text)
        doc.close()
        return "\n".join(parts)
    except Exception:
        return ""


def _guess_name_from_text(text: str) -> str:
    """从简历文本顶部猜测姓名。"""
    stop = {"在线简历", "个人简历", "简历", "基本信息", "工作经历", "教育经历",
            "项目经历", "求职意向", "个人优势"}
    for line in text.splitlines()[:30]:
        line = line.strip()
        if line in stop:
            continue
        if re.fullmatch(r"[一-鿿·]{2,4}", line):
            if line not in _NAME_STOP_WORDS:
                return line
        m = re.match(r"([一-鿿·]{2,4})\s*[男女]?\s*\d{1,2}", line)
        if m and not re.search(r"(职位|公司|学校|专业|经验|北京|上海|深圳|广州)", line):
            return m.group(1)
    return ""


def _match_by_keys(
    daemon_index: Dict[str, List[str]],
    name: str,
    phone: str,
    email: str,
    company: str,
) -> Optional[str]:
    """按优先级在索引中匹配 candidate_id，返回唯一最佳匹配。"""
    candidates: List[str] = []
    if phone:
        candidates = daemon_index.get(("phone", phone), [])
    if not candidates and email:
        candidates = daemon_index.get(("email", email), [])
    if not candidates and name and company:
        candidates = daemon_index.get(("name_company", (name.lower(), company.lower())), [])
    if not candidates and name:
        candidates = daemon_index.get(("name", name.lower()), [])
    if not candidates:
        return None
    return candidates[0]


def load_collector_candidates(db_path: Path) -> List[Dict[str, Any]]:
    """从 reloop.db 读取带 attachment_path 的记录。"""
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, fingerprint, name, phone, email, current_company, current_role,
                   raw_text, attachment_path
            FROM candidates
            WHERE attachment_path IS NOT NULL AND attachment_path != ''
            """
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def scan_attachment_dirs(*dirs: Path) -> List[Path]:
    """扫描附件目录返回 PDF/DOC 文件列表。"""
    files: List[Path] = []
    for d in dirs:
        if not d.exists():
            continue
        for ext in ("*.pdf", "*.PDF", "*.doc", "*.DOC", "*.docx", "*.DOCX"):
            files.extend(d.glob(ext))
    return files


def _candidate_keys(name: str, phone: str, email: str, company: str) -> set:
    keys = set()
    n = (name or "").strip()
    p = (phone or "").strip()
    e = (email or "").strip().lower()
    c = (company or "").strip()
    if n:
        keys.add(("name", n.lower()))
    if n and c:
        keys.add(("name_company", (n.lower(), c.lower())))
    if p:
        keys.add(("phone", p))
    if e:
        keys.add(("email", e))
    return keys


def build_daemon_index() -> Tuple[Dict[str, List[str]], Dict[str, Dict[str, Any]]]:
    """
    为 ttc_daemon candidates 建立去重索引。
    返回 (key -> candidate_ids, candidate_id -> record)
    """
    local_db.init_db()
    index: Dict[str, List[str]] = {}
    records: Dict[str, Dict[str, Any]] = {}

    with local_db.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name, phone, email, raw_profile, enriched_profile, original_attachment_path FROM candidates"
        ).fetchall()

    for row in rows:
        cid = row["id"]
        records[cid] = dict(row)

        raw = row["raw_profile"] or "{}"
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = {}
        enriched = row["enriched_profile"] or "{}"
        if isinstance(enriched, str):
            try:
                enriched = json.loads(enriched)
            except Exception:
                enriched = {}

        company = (
            raw.get("current_company")
            or enriched.get("current_company")
            or ""
        )
        phone = row["phone"] or _extract_phone(raw.get("raw_text", ""))
        email = row["email"] or _extract_email(raw.get("raw_text", ""))

        for key in _candidate_keys(row["name"] or "", phone, email, company):
            index.setdefault(key, []).append(cid)
    return index, records


def match_collector_to_daemon(
    collector: Dict[str, Any],
    daemon_index: Dict[str, List[str]],
    daemon_records: Dict[str, Dict[str, Any]],
) -> Optional[str]:
    """返回最佳匹配的 ttc_daemon candidate_id，无匹配返回 None。"""
    name = (collector.get("name") or "").strip()
    phone = (collector.get("phone") or "").strip()
    email = (collector.get("email") or "").strip().lower()
    company = (collector.get("current_company") or "").strip()
    raw_text = collector.get("raw_text") or ""

    if not phone:
        phone = _extract_phone(raw_text)
    if not email:
        email = _extract_email(raw_text)

    # 优先级：phone > email > name+company > name
    candidates: List[str] = []
    if phone:
        candidates = daemon_index.get(("phone", phone), [])
    if not candidates and email:
        candidates = daemon_index.get(("email", email), [])
    if not candidates and name and company:
        candidates = daemon_index.get(("name_company", (name.lower(), company.lower())), [])
    if not candidates and name:
        candidates = daemon_index.get(("name", name.lower()), [])

    if not candidates:
        return None

    # 如果多条，优先选没有 attachment_path 的；再选最新的
    best = None
    for cid in candidates:
        rec = daemon_records[cid]
        if not rec.get("original_attachment_path"):
            best = cid
            break
    if best is None:
        best = candidates[0]
    return best


def main() -> int:
    parser = argparse.ArgumentParser(description="同步 reloop PDF 到 ttc_daemon")
    parser.add_argument("--write", action="store_true", help="真正写入数据库（默认 dry-run）")
    parser.add_argument("--scan-dir", action="append", type=str, default=[], help="额外扫描的附件目录")
    parser.add_argument("--limit", type=int, default=0, help="最多处理条数，0 表示不限")
    args = parser.parse_args()

    local_db.init_db()
    daemon_index, daemon_records = build_daemon_index()
    print(f"[INFO] ttc_daemon candidates 索引完成：{len(daemon_records)} 条")

    collector_rows = load_collector_candidates(COLLECTOR_DB)
    print(f"[INFO] reloop 带附件记录：{len(collector_rows)} 条")

    matched = updated = skipped_no_file = already_has = no_match = 0
    total = 0

    for row in collector_rows:
        if args.limit and total >= args.limit:
            break
        total += 1

        attachment_path = Path(row["attachment_path"])
        if not attachment_path.is_absolute():
            attachment_path = REPO_ROOT / "reloop" / attachment_path
        if not attachment_path.exists():
            skipped_no_file += 1
            continue

        cid = match_collector_to_daemon(row, daemon_index, daemon_records)
        if not cid:
            no_match += 1
            print(f"[NO_MATCH] {attachment_path.name} (name={row.get('name')})")
            continue

        matched += 1
        existing = daemon_records[cid].get("original_attachment_path") or ""
        if existing:
            already_has += 1
            print(f"[HAS_ATTACHMENT] {cid} 已有 {existing}")
            continue

        mime = "application/pdf" if attachment_path.suffix.lower() == ".pdf" else "application/octet-stream"
        if args.write:
            local_db.update_candidate_attachment(
                cid,
                original_attachment_path=str(attachment_path),
                attachment_mime_type=mime,
            )
            daemon_records[cid]["original_attachment_path"] = str(attachment_path)
            updated += 1
            print(f"[UPDATED] {cid} <- {attachment_path}")
        else:
            updated += 1
            print(f"[DRY_RUN] {cid} <- {attachment_path}")

    # 额外扫描目录（仅按文件名简单提示，不做自动匹配，避免误关联）
    # 处理 orphan PDF：attachments/ 目录有文件但 collector.db 无记录
    orphan_files = scan_attachment_dirs(COLLECTOR_ATTACHMENTS, GMAIL_ATTACHMENTS)
    orphan_files = [f for f in orphan_files if f not in {Path(r.get("attachment_path") or "") for r in collector_rows}]
    if orphan_files:
        print(f"\n[INFO] 扫描到 {len(orphan_files)} 个 orphan 附件，尝试按文件名/内容匹配...")
        for f in orphan_files:
            if args.limit and total >= args.limit:
                break
            total += 1

            name = _extract_name_from_filename(f.name)
            text = _extract_pdf_text(f)
            phone = _extract_phone(text)
            email = _extract_email(text)
            if not name and text:
                name = _guess_name_from_text(text)

            cid = _match_by_keys(daemon_index, name, phone, email, "")
            if not cid:
                no_match += 1
                print(f"[NO_MATCH] {f.name} (guessed_name={name})")
                continue

            matched += 1
            existing = daemon_records[cid].get("original_attachment_path") or ""
            if existing:
                already_has += 1
                print(f"[HAS_ATTACHMENT] {cid} 已有 {existing}")
                continue

            mime = "application/pdf" if f.suffix.lower() == ".pdf" else "application/octet-stream"
            if args.write:
                local_db.update_candidate_attachment(
                    cid,
                    original_attachment_path=str(f),
                    attachment_mime_type=mime,
                )
                daemon_records[cid]["original_attachment_path"] = str(f)
                updated += 1
                print(f"[UPDATED] {cid} <- {f}")
            else:
                updated += 1
                print(f"[DRY_RUN] {cid} <- {f}")

    extra_dirs = [Path(d) for d in args.scan_dir]
    extra_files = scan_attachment_dirs(*extra_dirs)
    if extra_files:
        print(f"\n[INFO] 额外扫描到 {len(extra_files)} 个附件文件（未自动匹配，请检查）：")
        for f in extra_files[:20]:
            print(f"  - {f}")

    print("\n" + "=" * 60)
    print(f"同步完成（write={args.write}）")
    print(f"  处理 collector 记录: {total}")
    print(f"  文件不存在跳过:     {skipped_no_file}")
    print(f"  成功匹配:           {matched}")
    print(f"  已存在附件:         {already_has}")
    print(f"  无匹配:             {no_match}")
    print(f"  本次更新:           {updated}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
