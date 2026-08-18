#!/usr/bin/env python3
"""T2 验收：数据回填。

用法: python accept_T2.py <workspace>

验收标准:
  1. workspace/daemon.db 的 candidates 表共 20 行，name 全部非空（非 NULL 且非空串）。
  2. 每行 name 与 workspace/profiles.json 中的映射一致。
  3. 原本就有非空 name 的 14 行（见下方快照）不得被改动。
"""
import json
import sqlite3
import sys
from pathlib import Path

# 原本非空的 14 行 name 快照（回填前）
ORIGINAL_NAMES = {
    "c001": "王建国", "c002": "李秀兰", "c004": "张志强", "c005": "刘婷婷",
    "c006": "陈国华", "c008": "杨晓燕", "c009": "赵宏伟", "c010": "孙晓东",
    "c012": "周雅静", "c013": "吴国栋", "c015": "郑丽娜", "c016": "冯建华",
    "c018": "蒋梦琪", "c019": "沈立新",
}


def fail(msg: str) -> None:
    print(f"[T2 FAIL] {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    if len(sys.argv) != 2:
        fail("用法: python accept_T2.py <workspace>")
    ws = Path(sys.argv[1])
    db_path = ws / "daemon.db"
    profiles_path = ws / "profiles.json"
    if not db_path.is_file():
        fail(f"缺少 {db_path}")
    if not profiles_path.is_file():
        fail(f"缺少 {profiles_path}")

    try:
        profiles = json.loads(profiles_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        fail(f"profiles.json 不是合法 JSON: {e}")

    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT id, name FROM candidates ORDER BY id").fetchall()
    except sqlite3.Error as e:
        con.close()
        fail(f"读取 candidates 表失败: {e}")
    con.close()

    if len(rows) != 20:
        fail(f"candidates 表应为 20 行，实际 {len(rows)} 行")

    for cid, name in rows:
        if name is None or (isinstance(name, str) and name.strip() == ""):
            fail(f"{cid} 的 name 仍为空")
        want = profiles.get(cid)
        if want is None:
            fail(f"profiles.json 中缺少 {cid} 的映射")
        if name != want:
            fail(f"{cid} 的 name 与 profiles.json 不一致: 期望 {want!r}, 实际 {name!r}")

    for cid, want in ORIGINAL_NAMES.items():
        got = dict(rows).get(cid)
        if got != want:
            fail(f"原本非空的 {cid} 被改动: 原值 {want!r}, 现值 {got!r}")

    print("[T2 OK] 20 行 name 全部回填正确，原有 14 行未被改动")


if __name__ == "__main__":
    main()
