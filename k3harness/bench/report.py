"""基准报告生成：读 runs/bench/results.jsonl + runs/baseline_report.md，产出 bench_report.md。

主指标：billable tokens（input + output + cache_write），cache_read 单列。
成功标准：全任务集总 tokens 下降 ≥20%，通过率不低于 claude 腿 -1。
"""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "runs" / "bench" / "results.jsonl"
OUT = ROOT / "runs" / "bench_report.md"


def median(xs):
    return statistics.median(xs) if xs else 0


def main() -> None:
    rows = [json.loads(l) for l in RESULTS.read_text().splitlines() if l.strip()]
    by_task_leg = defaultdict(list)
    for r in rows:
        by_task_leg[(r["task_id"], r["leg"])].append(r)

    tasks = sorted({r["task_id"] for r in rows})
    cats = {r["task_id"]: r["category"] for r in rows}

    lines = ["# K3 harness 基准对比报告", ""]
    lines.append("| 任务 | 类别 | k3h 中位 billable | claude 中位 billable | 降幅 | k3h 通过率 | claude 通过率 | k3h 中位轮数 | claude 中位轮数 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")

    tot = {"k3h": 0, "claude": 0}
    pass_cnt = {"k3h": 0, "claude": 0}
    for t in tasks:
        agg = {}
        for leg in ("k3h", "claude"):
            rs = [r for r in by_task_leg.get((t, leg), []) if "error" not in r]
            agg[leg] = {
                "billable": median([r.get("billable_tokens", 0) for r in rs]),
                "pass_rate": sum(r["passed"] for r in rs) / len(rs) if rs else 0,
                "turns": median([r.get("turns", 0) for r in rs]),
                "n": len(rs),
            }
            tot[leg] += agg[leg]["billable"]
            pass_cnt[leg] += sum(r["passed"] for r in by_task_leg.get((t, leg), []) if "error" not in r)
        k, c = agg["k3h"], agg["claude"]
        drop = (1 - k["billable"] / c["billable"]) * 100 if c["billable"] else 0
        lines.append(
            f"| {t} | {cats[t]} | {k['billable']:,.0f} | {c['billable']:,.0f} | {drop:.1f}% "
            f"| {k['pass_rate']:.0%} ({k['n']}次) | {c['pass_rate']:.0%} ({c['n']}次) | {k['turns']:.0f} | {c['turns']:.0f} |"
        )

    total_drop = (1 - tot["k3h"] / tot["claude"]) * 100 if tot["claude"] else 0
    lines += ["", "## 总结", "",
              f"- 全任务集中位 billable 合计：k3h {tot['k3h']:,.0f} vs claude {tot['claude']:,.0f}，**总降幅 {total_drop:.1f}%**（目标 ≥20%）",
              f"- 通过任务数：k3h {pass_cnt['k3h']} vs claude {pass_cnt['claude']}（成功标准：不低于 claude 腿 -1）",
              f"- 结论判定：**{'达标' if total_drop >= 20 and pass_cnt['k3h'] >= pass_cnt['claude'] - 1 else '未达标'}**", "",
              "注：billable = input + output + cache_write；cache_read（缓存命中）单列于 results.jsonl。",
              "claude 腿为生产现状配置（含 CLAUDE.md 注入、rtk hook、47 skills 描述）；k3h 腿为自研轻量 harness。"]
    OUT.write_text("\n".join(lines))
    print(f"-> {OUT}")
    print(f"total_drop={total_drop:.1f}% k3h_pass={pass_cnt['k3h']} claude_pass={pass_cnt['claude']}")


if __name__ == "__main__":
    main()
