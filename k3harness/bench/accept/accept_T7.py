#!/usr/bin/env python3
"""T7 入库链路改造 验收脚本。

验收标准（在 workspace 的临时副本中执行，全部满足才 exit 0）：
1. `python3 main.py --dry-run`：exit 0；stdout 含行数 "8"；
   副本中的 local.db 不存在或 candidates 表行数为 0（dry-run 不得写库）。
2. 同一副本中 `python3 main.py`：exit 0；local.db 的 candidates 表恰有 8 行。

用法：python3 accept_T7.py <workspace>
"""
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

EXPECTED_ROWS = 8


def fail(msg: str) -> None:
    print(f"[T7 FAIL] {msg}", file=sys.stderr)
    sys.exit(1)


def db_row_count(db_path: Path):
    """返回行数；db 不存在返回 None；表不存在返回 0。"""
    if not db_path.exists():
        return None
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='candidates'"
        ).fetchone()
        if not row:
            return 0
        return conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
    finally:
        conn.close()


def run(cwd: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, *args], cwd=cwd, capture_output=True, text=True, timeout=60
    )


def main() -> None:
    if len(sys.argv) != 2:
        fail("用法: python3 accept_T7.py <workspace>")
    ws = Path(sys.argv[1]).resolve()
    if not (ws / "main.py").is_file():
        fail(f"{ws} 下没有 main.py")

    with tempfile.TemporaryDirectory(prefix="t7_accept_") as tmp:
        work = Path(tmp) / "proj"
        shutil.copytree(ws, work)
        # 清掉 agent 自己跑出来的 local.db，保证验收确定性
        stale = work / "local.db"
        if stale.exists():
            stale.unlink()

        # 第①步：dry-run
        r = run(work, "main.py", "--dry-run")
        if r.returncode != 0:
            fail(f"`python3 main.py --dry-run` 退出码 {r.returncode}，stderr: {r.stderr[:300]}")
        if str(EXPECTED_ROWS) not in r.stdout:
            fail(f"dry-run 输出未包含行数 {EXPECTED_ROWS}，stdout: {r.stdout[:300]}")
        n = db_row_count(work / "local.db")
        if n not in (None, 0):
            fail(f"dry-run 不应写库，但 local.db 已有 {n} 行")

        # 第②步：真实写入
        r = run(work, "main.py")
        if r.returncode != 0:
            fail(f"`python3 main.py` 退出码 {r.returncode}，stderr: {r.stderr[:300]}")
        n = db_row_count(work / "local.db")
        if n != EXPECTED_ROWS:
            fail(f"local.db 应有 {EXPECTED_ROWS} 行，实际 {n}")

    print("[T7 PASS] dry-run 不写库且报告 8 行；正式写入 8 行")
    sys.exit(0)


if __name__ == "__main__":
    main()
