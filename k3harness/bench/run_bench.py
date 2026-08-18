"""基准跑分器：同一任务集在两条腿（claude -p / k3h）下对比。

用法：
  python bench/run_bench.py --leg k3h --tasks T1,T5 --reps 1      # 调试
  python bench/run_bench.py --leg both --reps 3                    # 正式跑分

契约：fixture -> workspace 副本 -> 逐字 prompt -> accept 脚本判定。
结果落 runs/bench/results.jsonl，每行一个 run 的完整计量。
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"
OUT_DIR = ROOT / "runs" / "bench"
RESULTS = OUT_DIR / "results.jsonl"

sys.path.insert(0, str(ROOT))


def load_tasks() -> tuple[int, list[dict]]:
    cfg = yaml.safe_load((BENCH / "tasks.yaml").read_text())
    return cfg["max_turns"], cfg["tasks"]


def prep_workspace(task: dict, leg: str, rep: int) -> Path:
    ws = OUT_DIR / task["id"] / leg / f"rep{rep}" / "workspace"
    if ws.exists():
        shutil.rmtree(ws)
    ws.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(BENCH / task["fixture"], ws)
    return ws


def run_k3h(task: dict, ws: Path, max_turns: int) -> dict:
    from k3h.agent import run_agent
    from k3h.cli import RUNS_DIR, _system
    from k3h.backends.anthropic import AnthropicBackend
    from k3h.config import load_config
    from k3h.meter import Meter
    from k3h.tools.base import ToolContext

    be = AnthropicBackend(load_config())
    ctx = ToolContext(cwd=ws, mode="apply")
    meter = Meter(RUNS_DIR, task_id=task["id"], leg="k3h")
    t0 = time.time()
    result = run_agent(be, task["prompt"], _system(), ctx, meter, max_turns=max_turns, verbose=False)
    s = result.summary
    s["wall_seconds"] = round(time.time() - t0, 1)
    return s


def run_claude(task: dict, ws: Path, max_turns: int) -> dict:
    """Claude Code 生产配置腿（含 CLAUDE.md/rtk hook 等现状）。"""
    t0 = time.time()
    r = subprocess.run(
        [
            "claude", "-p", task["prompt"],
            "--output-format", "json",
            "--dangerously-skip-permissions",
            "--max-turns", str(max_turns),
        ],
        capture_output=True, text=True, cwd=ws, timeout=1800,
    )
    wall = round(time.time() - t0, 1)
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"error": f"claude 输出非 JSON: {r.stdout[:300]} {r.stderr[:300]}", "wall_seconds": wall}
    u = data.get("usage") or {}
    return {
        "turns": data.get("num_turns", 0),
        "wall_seconds": wall,
        "input_tokens": u.get("input_tokens", 0),
        "output_tokens": u.get("output_tokens", 0),
        "cache_read_tokens": u.get("cache_read_input_tokens", 0),
        "cache_write_tokens": u.get("cache_creation_input_tokens", 0),
        "billable_tokens": u.get("input_tokens", 0) + u.get("output_tokens", 0) + u.get("cache_creation_input_tokens", 0),
        "est_cost_yuan": round((
            u.get("input_tokens", 0) * 4.0 + u.get("output_tokens", 0) * 16.0
            + u.get("cache_read_input_tokens", 0) * 1.0 + u.get("cache_creation_input_tokens", 0) * 4.0
        ) / 1_000_000, 6),
        "is_error": data.get("is_error", False),
    }


def run_accept(task: dict, ws: Path) -> bool:
    script = BENCH / task["accept"]
    r = subprocess.run([sys.executable, str(script), str(ws)], capture_output=True, text=True, timeout=120)
    return r.returncode == 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--leg", choices=["k3h", "claude", "both"], default="both")
    ap.add_argument("--tasks", default="", help="逗号分隔，默认全部")
    ap.add_argument("--reps", type=int, default=3)
    args = ap.parse_args()

    max_turns, tasks = load_tasks()
    if args.tasks:
        wanted = set(args.tasks.split(","))
        tasks = [t for t in tasks if t["id"] in wanted]
    legs = ["k3h", "claude"] if args.leg == "both" else [args.leg]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for task in tasks:
        for leg in legs:
            for rep in range(1, args.reps + 1):
                ws = prep_workspace(task, leg, rep)
                print(f"[run] {task['id']} {leg} rep{rep} ...", flush=True)
                try:
                    metrics = run_k3h(task, ws, max_turns) if leg == "k3h" else run_claude(task, ws, max_turns)
                except Exception as e:
                    metrics = {"error": f"{type(e).__name__}: {e}"}
                passed = run_accept(task, ws) if "error" not in metrics else False
                row = {"task_id": task["id"], "category": task["category"], "leg": leg, "rep": rep,
                       "passed": passed, **metrics, "ts": time.time()}
                with RESULTS.open("a") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                print(f"[done] {task['id']} {leg} rep{rep} passed={passed} "
                      f"billable={metrics.get('billable_tokens', '?')} wall={metrics.get('wall_seconds', '?')}s", flush=True)


if __name__ == "__main__":
    main()
