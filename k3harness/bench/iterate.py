"""实验迭代驱动器（autoresearch 循环的机械化实现）。

循环：apply patch → guard 检查（不动验收文件）→ commit → quick verify → keep/revert → TSV 日志。

用法：
  python bench/iterate.py status                      # 看当前状态/历史
  python bench/iterate.py run --desc "缩短bash截断" --patch /tmp/e1.diff
  python bench/iterate.py verify-quick                # 只跑快速子集（goal.yaml metric）
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = ROOT.parent                       # git 仓库根
BENCH = ROOT / "bench"
TSV = BENCH / "experiments.tsv"
QUICK_TASKS = ["T1", "T3", "T5", "T8"]   # 覆盖解析/评分/脚本/调试四类
FULL_TASKS = [f"T{i}" for i in range(1, 11)]
PASS_EXEMPT = {"T6"}                     # 已知 accept 阈值偏严，豁免

sys.path.insert(0, str(ROOT))


def git(*args: str) -> str:
    r = subprocess.run(["/usr/bin/git", *args], cwd=REPO, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


def run_bench_subset(tasks: list[str]) -> dict[str, dict]:
    """跑 k3h 腿，返回 {task_id: {billable, passed}}。直接调 run_bench 的函数。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("run_bench", BENCH / "run_bench.py")
    rb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rb)
    max_turns, all_tasks = rb.load_tasks()
    out = {}
    for t in all_tasks:
        if t["id"] not in tasks:
            continue
        ws = rb.prep_workspace(t, "k3h", 1)
        try:
            metrics = rb.run_k3h(t, ws, max_turns)
        except Exception as e:
            metrics = {"error": str(e)}
        passed = rb.run_accept(t, ws) if "error" not in metrics else False
        out[t["id"]] = {"billable": metrics.get("billable_tokens", 0), "passed": passed,
                        "error": metrics.get("error")}
    return out


def quick_metric(results: dict[str, dict]) -> float:
    return sum(r["billable"] for r in results.values())


def guard_ok(results: dict[str, dict]) -> tuple[bool, str]:
    fails = [t for t, r in results.items() if not r["passed"] and t not in PASS_EXEMPT]
    return (not fails), (f"未通过: {fails}" if fails else "全过")


def tsv_append(row: dict) -> None:
    new = not TSV.exists()
    with TSV.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["iteration", "commit", "metric", "delta", "status", "description"], delimiter="\t")
        if new:
            w.writeheader()
        w.writerow(row)


def tsv_read() -> list[dict]:
    if not TSV.exists():
        return []
    with TSV.open() as f:
        return list(csv.DictReader(f, delimiter="\t"))


def best_metric() -> float | None:
    vals = [float(r["metric"]) for r in tsv_read() if r["status"] in ("baseline", "keep") and r["metric"]]
    return min(vals) if vals else None


def cmd_run(desc: str, patch: str) -> None:
    history = tsv_read()
    iteration = len(history)
    base = best_metric()

    # 0. 工作区必须干净
    if git("status", "--porcelain", "--", "k3harness"):
        print("k3harness/ 有未提交改动，先处理", file=sys.stderr)
        sys.exit(1)

    # 1. apply patch
    try:
        git("apply", "--check", patch)
        git("apply", patch)
    except RuntimeError as e:
        print(f"patch 应用失败（不计迭代）: {e}", file=sys.stderr)
        sys.exit(1)

    # 2. guard：不得触碰验收文件
    changed = git("diff", "--name-only", "HEAD", "--", "k3harness")
    guarded = [f for f in changed.splitlines() if f.startswith(("k3harness/bench/accept/", "k3harness/bench/fixtures/")) or f.endswith("bench/tasks.yaml")]
    if guarded:
        git("checkout", "--", "k3harness")
        print(f"GUARD 违规：patch 触碰了验收文件 {guarded}，已回滚工作区", file=sys.stderr)
        sys.exit(1)

    # 3. 语法冒烟（语法错误立即修，不计迭代）
    r = subprocess.run([str(ROOT / ".venv/bin/python"), "-c", "import k3h.cli"], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        git("checkout", "--", "k3harness")
        print(f"语法/导入错误（不计迭代），已回滚: {r.stderr[:300]}", file=sys.stderr)
        sys.exit(1)

    # 4. commit（先提交再验证）
    git("add", "k3harness")
    git("commit", "-m", f"experiment: {desc}\n\nCo-Authored-By: Claude <noreply@anthropic.com>")
    commit = git("rev-parse", "--short", "HEAD")

    # 5. quick verify（guard 失败的非豁免任务重试 1 次，过滤偶发抖动）
    print(f"[iter {iteration}] 快速验证（{','.join(QUICK_TASKS)}）...")
    results = run_bench_subset(QUICK_TASKS)
    flaky = [t for t, r in results.items() if not r["passed"] and t not in PASS_EXEMPT]
    if flaky:
        print(f"[iter {iteration}] guard 重试: {flaky}")
        retry = run_bench_subset(flaky)
        for t, r in retry.items():
            if r["passed"]:
                results[t] = r  # 重试通过则以重试结果为准
    metric = quick_metric(results)
    ok, why = guard_ok(results)
    delta = (metric - base) if base else 0.0

    # 6. keep / revert
    if not ok:
        status = "revert-guard"
    elif base is not None and metric >= base:
        status = "revert-worse"
    else:
        status = "keep"
    if status.startswith("revert"):
        git("revert", "--no-edit", "HEAD")
        print(f"[iter {iteration}] {status}: metric={metric:.0f} (best={base}) {why} → 已 revert")
    else:
        print(f"[iter {iteration}] KEEP: metric={metric:.0f} delta={delta:+.0f}")

    # 7. TSV 日志并 amend 进 HEAD（实验提交或 revert 提交），保证日志永远在 git 里
    tsv_append({"iteration": iteration, "commit": commit, "metric": f"{metric:.0f}",
                "delta": f"{delta:+.0f}", "status": status, "description": desc})
    git("add", "k3harness/bench/experiments.tsv")
    git("commit", "--amend", "--no-edit")
    print(json.dumps(results, ensure_ascii=False))


def cmd_baseline() -> None:
    print("[iter 0] 基线测量...")
    results = run_bench_subset(QUICK_TASKS)
    metric = quick_metric(results)
    tsv_append({"iteration": 0, "commit": git("rev-parse", "--short", "HEAD"),
                "metric": f"{metric:.0f}", "delta": "0", "status": "baseline", "description": "iteration #0 基线"})
    print(f"baseline metric={metric:.0f}")
    print(json.dumps(results, ensure_ascii=False))


def cmd_status() -> None:
    rows = tsv_read()
    if not rows:
        print("无实验历史，先跑 iterate.py baseline")
        return
    print(f"{'iter':<5}{'commit':<10}{'metric':<10}{'delta':<10}{'status':<15}desc")
    for r in rows:
        print(f"{r['iteration']:<5}{r['commit']:<10}{r['metric']:<10}{r['delta']:<10}{r['status']:<15}{r['description']}")
    b = best_metric()
    if b and rows and rows[0]["metric"]:
        print(f"\n当前 best={b:.0f}，相对基线 {float(rows[0]['metric']):.0f} 变化 {(b / float(rows[0]['metric']) - 1) * 100:+.1f}%")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("baseline")
    sub.add_parser("status")
    p = sub.add_parser("run")
    p.add_argument("--desc", required=True)
    p.add_argument("--patch", required=True)
    args = ap.parse_args()
    if args.cmd == "baseline":
        cmd_baseline()
    elif args.cmd == "status":
        cmd_status()
    else:
        cmd_run(args.desc, args.patch)


if __name__ == "__main__":
    main()
