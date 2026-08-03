#!/usr/bin/env python3
# ONE-OFF (2026-08-03)
# Input: inspect --help and the operator invocation record before running.
# Execution: do not rerun without explicit operator confirmation.

"""
把 jd_match_feishu_base.py 的 Top50 结果写回飞书候选人主表。

会创建/复用以下字段：
- 启承匹配分（number）
- 启承匹配结论（text，含推荐等级、证据、维度分、PDF路径、手机号恢复状态）

用法：
    reloop/.venv/bin/python scripts/sync_feishu_qicheng_top50.py \
        --input data/qicheng_feishu_match/qicheng_top50.json \
        --base-token DIIdbR2c8ax8bTsZoNKcnX6enSe \
        --table-id tblWFuBQrPmllE9W
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]

SCORE_FIELD = "启承匹配分"
CONCLUSION_FIELD = "启承匹配结论"


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


def ensure_field(base_token: str, table_id: str, name: str, field_type: str, properties: Optional[Dict[str, Any]] = None) -> str:
    """如果字段不存在则创建，返回 field_id。"""
    resp = _run_cli("+field-list", "--base-token", base_token, "--table-id", table_id)
    fields = resp.get("data", {}).get("fields", []) if isinstance(resp, dict) else []
    for f in fields:
        if f.get("name") == name:
            print(f"  字段已存在：{name} ({f['id']})")
            return f["id"]

    payload: Dict[str, Any] = {"name": name, "type": field_type}
    if properties:
        payload.update(properties)

    print(f"  创建字段：{name} ({field_type})")
    resp = _run_cli(
        "+field-create",
        "--base-token", base_token,
        "--table-id", table_id,
        "--json", json.dumps(payload, ensure_ascii=False),
    )
    if not resp.get("ok"):
        raise RuntimeError(f"创建字段失败：{resp}")
    field_id = resp.get("data", {}).get("field", {}).get("id")
    if not field_id:
        raise RuntimeError(f"创建字段未返回 field_id：{resp}")
    print(f"  创建成功：{name} ({field_id})")
    return field_id


def build_conclusion(candidate: Dict[str, Any]) -> str:
    lines = [
        f"岗位：{candidate.get('jd_title', '')}",
        f"得分：{candidate.get('overall', 0)}",
        f"推荐：{candidate.get('recommendation', '')}",
        f"严格匹配：{'是' if candidate.get('strict_match') else '否'}",
    ]
    if candidate.get("hard_fail_reason"):
        lines.append(f"硬条件不符原因：{candidate['hard_fail_reason']}")

    dims = candidate.get("dimension_scores", {})
    if dims:
        lines.append("维度分：" + " | ".join(f"{k}={v}" for k, v in dims.items()))

    quotes = candidate.get("evidence_quotes", [])
    if quotes:
        lines.append("证据：")
        for q in quotes[:5]:
            lines.append(f"  • {q}")

    if candidate.get("pdf_path"):
        lines.append(f"本地PDF：{candidate['pdf_path']}")
    else:
        lines.append("本地PDF：未下载")

    recovery = candidate.get("phone_recovery", {})
    if recovery:
        lines.append(
            f"手机号：{candidate.get('phone') or '无'} （{recovery.get('status')}）"
        )
    else:
        lines.append(f"手机号：{candidate.get('phone') or '无'}")

    if candidate.get("risks"):
        lines.append("风险：" + "；".join(candidate["risks"][:3]))

    return "\n".join(lines)


def update_record(
    base_token: str,
    table_id: str,
    record_id: str,
    score_field_id: str,
    conclusion_field_id: str,
    candidate: Dict[str, Any],
) -> Dict[str, Any]:
    payload = {
        score_field_id: float(candidate.get("overall", 0)),
        conclusion_field_id: build_conclusion(candidate),
    }
    resp = _run_cli(
        "+record-upsert",
        "--base-token", base_token,
        "--table-id", table_id,
        "--record-id", record_id,
        "--json", json.dumps(payload, ensure_ascii=False),
    )
    return resp


def main() -> int:
    parser = argparse.ArgumentParser(description="同步启承资本 Top50 匹配结果回飞书")
    parser.add_argument("--input", default=str(REPO_ROOT / "data" / "qicheng_feishu_match" / "qicheng_top50.json"))
    parser.add_argument("--base-token", default="DIIdbR2c8ax8bTsZoNKcnX6enSe")
    parser.add_argument("--table-id", default="tblWFuBQrPmllE9W")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不写入")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.is_file():
        print(f"输入文件不存在：{input_path}", file=sys.stderr)
        return 1

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    candidates = data.get("data", [])
    print(f"读取 Top {len(candidates)} 候选人")

    print("检查/创建字段 ...")
    score_field_id = ensure_field(args.base_token, args.table_id, SCORE_FIELD, "number")
    conclusion_field_id = ensure_field(args.base_token, args.table_id, CONCLUSION_FIELD, "text")

    if args.dry_run:
        print("\n--dry-run 模式，仅预览前 3 条：")
        for c in candidates[:3]:
            print(f"\n{c.get('name')} ({c.get('record_id')}):")
            print(f"  {SCORE_FIELD}: {c.get('overall')}")
            print(f"  {CONCLUSION_FIELD}:\n{build_conclusion(c)}")
        return 0

    print(f"\n开始同步 {len(candidates)} 条记录 ...")
    success = 0
    failed = 0
    for i, c in enumerate(candidates, 1):
        record_id = c.get("record_id")
        if not record_id:
            print(f"[{i}/{len(candidates)}] {c.get('name')} 无 record_id，跳过")
            failed += 1
            continue

        print(f"[{i}/{len(candidates)}] {c.get('name')} ...", end=" ", flush=True)
        try:
            resp = update_record(
                args.base_token, args.table_id, record_id,
                score_field_id, conclusion_field_id, c,
            )
            if resp.get("ok"):
                print("OK")
                success += 1
            else:
                print(f"FAIL {resp.get('error', resp)}")
                failed += 1
        except Exception as exc:
            print(f"ERROR {exc}")
            failed += 1
        time.sleep(0.3)  # 轻量限流

    print(f"\n同步完成：成功 {success} / 失败 {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
