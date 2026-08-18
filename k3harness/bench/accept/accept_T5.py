#!/usr/bin/env python3
"""T5 验收：日志统计。

用法: python accept_T5.py <workspace>

验收标准:
  workspace/report.md 必须包含一个 markdown 表格，每行一个日志文件，形如:
    | 文件 | ERROR 数 |
    | cron.log | 105 |
    ...
  1. 表格必须覆盖 logs/ 下全部 5 个 .log 文件，ERROR 数与预埋真值精确一致:
     cron.log=105, api.log=58, app.log=37, sync.log=12, worker.log=0
  2. 表格行按 ERROR 数降序排列（允许并列）。
  3. 真值会与 logs/ 实际内容（含 "ERROR" 字样的行数）交叉核对。
"""
import re
import sys
from pathlib import Path

EXPECTED = {
    "cron.log": 105,
    "api.log": 58,
    "app.log": 37,
    "sync.log": 12,
    "worker.log": 0,
}


def fail(msg: str) -> None:
    print(f"[T5 FAIL] {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    if len(sys.argv) != 2:
        fail("用法: python accept_T5.py <workspace>")
    ws = Path(sys.argv[1])

    # 交叉核对：logs/ 实际 ERROR 行数必须等于预埋真值
    log_dir = ws / "logs"
    if not log_dir.is_dir():
        fail(f"缺少目录 {log_dir}")
    for fname, want in EXPECTED.items():
        p = log_dir / fname
        if not p.is_file():
            fail(f"缺少日志文件 {p}")
        actual = sum(1 for ln in p.read_text(encoding="utf-8").splitlines() if "ERROR" in ln)
        if actual != want:
            fail(f"日志文件 {fname} 被改动: 实际 ERROR 行数 {actual}, 预埋真值 {want}")

    report = ws / "report.md"
    if not report.is_file():
        fail(f"缺少 {report}")
    text = report.read_text(encoding="utf-8")

    # 解析 markdown 表格行
    rows = []  # (文件名, ERROR 数)
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        first, second = cells[0], cells[1]
        # 跳过表头与分隔行
        if set(first) <= set("-: ") or set(second) <= set("-: "):
            continue
        if "文件" in first or "ERROR" in second.upper():
            continue
        m = re.search(r"([\w.\-]+\.log)", first)
        if not m:
            continue
        m_num = re.search(r"\d+", second)
        if not m_num:
            fail(f"表格行 {line!r} 的第二列解析不出数字")
        rows.append((m.group(1), int(m_num.group(0))))

    if not rows:
        fail("report.md 中没有解析到任何日志统计表格行")

    got = dict(rows)
    if len(got) != len(rows):
        fail("表格中存在重复的文件行")
    missing = set(EXPECTED) - set(got)
    if missing:
        fail(f"表格缺少文件: {sorted(missing)}")
    extra = set(got) - set(EXPECTED)
    if extra:
        fail(f"表格中出现非 logs/ 下的文件: {sorted(extra)}")

    for fname, want in EXPECTED.items():
        if got[fname] != want:
            fail(f"{fname} 的 ERROR 数错误: 期望 {want}, 表格中 {got[fname]}")

    counts = [c for _, c in rows]
    if counts != sorted(counts, reverse=True):
        fail(f"表格未按 ERROR 数降序排列: {counts}")

    print("[T5 OK] report.md 表格 5 个文件 ERROR 数精确且按降序")


if __name__ == "__main__":
    main()
