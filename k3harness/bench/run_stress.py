"""大数据集压测：S1 100 份简历评分 / S3 148KB 长文归纳 / S4 仓库级扫描。

用法：python bench/run_stress.py [--tasks S1,S3,S4]
结果落 runs/stress_results.jsonl。验收逻辑内嵌（确定性）。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

STRESS = ROOT / "bench" / "stress"
OUT = ROOT / "runs" / "stress_results.jsonl"

TASKS = {
    "S1": {
        "cwd": STRESS / "s1",
        "max_turns": 40,
        "prompt": (
            "当前目录有 jd.txt（财务负责人 JD）和 resumes/ 下 100 份简历 JSON（含 raw_text 字段）。"
            "用脚本批量读取所有简历，按 JD 匹配度打分（0-100），输出 top10.json："
            "数组按分数降序，每项含 rank, file, score, reason 字段。"
        ),
    },
    "S3": {
        "cwd": STRESS / "s3",
        "max_turns": 30,
        "prompt": (
            "当前目录 big_minutes.txt 是一份 148KB 的会议纪要汇编（多份纪要拼接，含重复段落）。"
            "通读全文（文件很大，分段读），输出 summary.json："
            '{"decisions": [...], "action_items": [{"item":..., "owner":...}], "key_quotes": [...]}，'
            "去重后提取最重要的决策、待办（含负责人）和关键原话，总数不超过 15 条。"
        ),
    },
    "S4": {
        "cwd": ROOT.parent,  # 仓库根
        "max_turns": 30,
        "prompt": (
            "统计 candidate-collector 目录下所有 .py 文件的行数，"
            "把行数 Top10 写入 pylines_top10.md（markdown 表格：| 文件 | 行数 |，按行数降序）。"
        ),
    },
}


def accept(task_id: str, cwd: Path) -> tuple[bool, str]:
    if task_id == "S1":
        f = cwd / "top10.json"
        if not f.exists():
            return False, "缺 top10.json"
        try:
            data = json.loads(f.read_text())
            assert len(data) == 10 and all({"rank", "file", "score", "reason"} <= set(d) for d in data)
            scores = [d["score"] for d in data]
            assert scores == sorted(scores, reverse=True)
        except Exception as e:
            return False, f"schema: {e}"
        strong = sum(1 for d in data if d["file"].startswith("s_"))
        return (strong >= 8), f"强匹配占比 {strong}/10（要求≥8）"
    if task_id == "S3":
        f = cwd / "summary.json"
        if not f.exists():
            return False, "缺 summary.json"
        try:
            data = json.loads(f.read_text())
            assert {"decisions", "action_items", "key_quotes"} <= set(data)
        except Exception as e:
            return False, f"schema: {e}"
        text = json.dumps(data, ensure_ascii=False)
        kws = ["姚堃", "简历库", "周四", "demo", "小麦", "AI"]
        hits = sum(1 for k in kws if k in text)
        return (hits >= 5), f"关键词命中 {hits}/6（要求≥5）"
    if task_id == "S4":
        f = cwd / "pylines_top10.md"
        if not f.exists():
            return False, "缺 pylines_top10.md"
        rows = [l for l in f.read_text().splitlines() if l.startswith("|") and "---" not in l and "文件" not in l]
        if len(rows) != 10:
            return False, f"表格 {len(rows)} 行（要求 10）"
        # 事实核对：重新算 Top1
        r = subprocess.run(
            ["zsh", "-c", "find candidate-collector -name '*.py' -not -path '*/.venv/*' | xargs wc -l | grep -v ' total$' | sort -rn | head -1"],
            capture_output=True, text=True, cwd=cwd)
        top_line = r.stdout.split()[0] if r.stdout.split() else ""
        return (top_line in rows[0]), f"Top1 行数应为 {top_line}，实际首行: {rows[0][:60]}"
    return False, "未知任务"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default="S1,S3,S4")
    args = ap.parse_args()

    from k3h.agent import run_agent
    from k3h.cli import RUNS_DIR, _system
    from k3h.backends.anthropic import AnthropicBackend
    from k3h.config import load_config
    from k3h.meter import Meter
    from k3h.tools.base import ToolContext

    be = AnthropicBackend(load_config())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    for tid in args.tasks.split(","):
        t = TASKS[tid]
        ctx = ToolContext(cwd=t["cwd"], mode="apply")
        meter = Meter(RUNS_DIR, task_id=tid, leg="stress")
        t0 = time.time()
        result = run_agent(be, t["prompt"], _system(), ctx, meter, max_turns=t["max_turns"], verbose=True)
        wall = round(time.time() - t0, 1)
        passed, why = accept(tid, t["cwd"])
        row = {"task_id": tid, "passed": passed, "why": why, "wall": wall,
               **{k: result.summary[k] for k in ("billable_tokens", "input_tokens", "output_tokens", "turns")},
               "compacts": result.compacts, "crashed": result.summary.get("crashed", False),
               "hit_max_turns": result.hit_max_turns, "ts": time.time()}
        with OUT.open("a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"[{tid}] passed={passed} ({why}) billable={row['billable_tokens']} turns={row['turns']} "
              f"compacts={row['compacts']} wall={wall}s", flush=True)


if __name__ == "__main__":
    main()
