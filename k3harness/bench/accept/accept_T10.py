#!/usr/bin/env python3
"""T10 飞书三段式 mock 验收脚本。

验收标准（针对 workspace/state.json，全部满足才 exit 0）：
1. state.json 合法 JSON，含 tables 和 log。
2. 三段式顺序：log 中每条 apply 记录，在其之前必须存在同 op、同 table 的
   dry-run 记录（create_table 与 insert 各自的 apply 都要有对应 dry-run 先行）。
3. tables 中存在「候选人」表，字段恰含 姓名/手机号/公司（顺序不限）。
4. 「候选人」表的 records 与 workspace/records.csv 的 5 条记录一致
   （逐条按字段比对，顺序一致）。

用法：python3 accept_T10.py <workspace>
"""
import csv
import json
import sys
from pathlib import Path

TABLE_NAME = "候选人"
REQUIRED_FIELDS = {"姓名", "手机号", "公司"}
EXPECTED_ROWS = 5


def fail(msg: str) -> None:
    print(f"[T10 FAIL] {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    if len(sys.argv) != 2:
        fail("用法: python3 accept_T10.py <workspace>")
    ws = Path(sys.argv[1])

    state_path = ws / "state.json"
    if not state_path.is_file():
        fail("state.json 不存在")
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        fail(f"state.json 不是合法 JSON: {e}")
    if not isinstance(state.get("tables"), dict) or not isinstance(state.get("log"), list):
        fail("state.json 必须含 tables（对象）和 log（数组）")

    # 三段式顺序校验
    log = state["log"]
    for i, entry in enumerate(log):
        if entry.get("phase") != "apply":
            continue
        op, table = entry.get("op"), entry.get("table")
        matched = any(
            e.get("phase") == "dry-run" and e.get("op") == op and e.get("table") == table
            for e in log[:i]
        )
        if not matched:
            fail(f"log[{i}] 是 apply（op={op}, table={table}），"
                 f"但此前没有对应的 dry-run 记录——违反三段式")

    # 表结构校验
    tables = state["tables"]
    if TABLE_NAME not in tables:
        fail(f"tables 中没有「{TABLE_NAME}」表（现有: {list(tables) or '无'}）")
    table = tables[TABLE_NAME]
    fields = set(table.get("fields") or [])
    if not REQUIRED_FIELDS.issubset(fields):
        fail(f"「{TABLE_NAME}」表字段 {sorted(fields)} 缺少必需字段 {sorted(REQUIRED_FIELDS)}")

    # 记录比对
    csv_path = ws / "records.csv"
    if not csv_path.is_file():
        fail("records.csv 不存在，无法比对")
    with csv_path.open(encoding="utf-8", newline="") as f:
        expected = [row for row in csv.DictReader(f)]
    if len(expected) != EXPECTED_ROWS:
        fail(f"records.csv 应为 {EXPECTED_ROWS} 条，实际 {len(expected)}（fixture 损坏）")

    records = table.get("records") or []
    if len(records) != EXPECTED_ROWS:
        fail(f"「{TABLE_NAME}」表应有 {EXPECTED_ROWS} 条记录，实际 {len(records)}")
    for i, (got, want) in enumerate(zip(records, expected)):
        for field in REQUIRED_FIELDS:
            if str(got.get(field, "")).strip() != str(want.get(field, "")).strip():
                fail(f"第 {i + 1} 条记录字段「{field}」不一致: "
                     f"库中 {got.get(field)!r} != csv {want.get(field)!r}")

    print(f"[T10 PASS] 三段式顺序合规，「{TABLE_NAME}」表 {EXPECTED_ROWS} 条记录与 records.csv 一致")
    sys.exit(0)


if __name__ == "__main__":
    main()
