"""实验趋势分析（autoresearch evals 范式）：平台期检测 + 继续/停止建议。"""
from __future__ import annotations

import csv
from pathlib import Path

TSV = Path(__file__).parent / "experiments.tsv"
PLATEAU_WINDOW = 3  # 连续 N 次无改进 = 平台期


def main() -> None:
    if not TSV.exists():
        print("无实验历史")
        return
    rows = list(csv.DictReader(TSV.open(), delimiter="\t"))
    keeps = [r for r in rows if r["status"] in ("baseline", "keep")]
    print(f"总迭代 {len(rows)}，keep {len(keeps) - 1}，revert {sum(1 for r in rows if r['status'].startswith('revert'))}")
    if len(keeps) >= 2:
        first, last = float(keeps[0]["metric"]), float(keeps[-1]["metric"])
        print(f"基线 {first:.0f} → 当前 best {last:.0f}（{(last / first - 1) * 100:+.1f}%）")
    # 平台期：最近 N 次实验全部 revert
    recent = rows[-PLATEAU_WINDOW:]
    if len(recent) == PLATEAU_WINDOW and all(r["status"].startswith("revert") for r in recent):
        print(f"\n⚠️ 平台期：最近 {PLATEAU_WINDOW} 次实验均无改进。建议：换策略（改 compact/prompt 结构而非截断参数），或停止——边际收益已尽。")
    else:
        print("\n未达平台期，继续迭代仍有空间。")


if __name__ == "__main__":
    main()
