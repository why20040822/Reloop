"""token 计量：每次 API 调用落一行 JSONL，run 结束写 summary。"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from .backends.base import Usage

# Moonshot 公开刊例价（元/百万 tokens），仅作成本折算参考；coding 订阅按 token 量计费
PRICE_PER_MTOK = {"input": 4.0, "output": 16.0, "cache_read": 1.0, "cache_write": 4.0}


def est_cost_yuan(u: Usage) -> float:
    return (
        u.input_tokens * PRICE_PER_MTOK["input"]
        + u.output_tokens * PRICE_PER_MTOK["output"]
        + u.cache_read_tokens * PRICE_PER_MTOK["cache_read"]
        + u.cache_write_tokens * PRICE_PER_MTOK["cache_write"]
    ) / 1_000_000


class Meter:
    def __init__(self, runs_dir: Path, task_id: str = "adhoc", leg: str = "k3h", run_id: str | None = None):
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self.task_id = task_id
        self.leg = leg
        self.path = runs_dir / f"{int(time.time())}_{leg}_{task_id}_{self.run_id}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.turns: list[dict] = []
        self.t0 = time.time()

    def record(self, turn: int, model: str, usage: Usage) -> None:
        row = {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "leg": self.leg,
            "turn": turn,
            "model": model,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_read_tokens": usage.cache_read_tokens,
            "cache_write_tokens": usage.cache_write_tokens,
            "est_cost_yuan": round(est_cost_yuan(usage), 6),
            "ts": time.time(),
        }
        self.turns.append(row)
        with self.path.open("a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def summary(self) -> dict:
        agg = {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "leg": self.leg,
            "turns": len(self.turns),
            "wall_seconds": round(time.time() - self.t0, 1),
            "input_tokens": sum(t["input_tokens"] for t in self.turns),
            "output_tokens": sum(t["output_tokens"] for t in self.turns),
            "cache_read_tokens": sum(t["cache_read_tokens"] for t in self.turns),
            "cache_write_tokens": sum(t["cache_write_tokens"] for t in self.turns),
            "est_cost_yuan": round(sum(t["est_cost_yuan"] for t in self.turns), 6),
        }
        agg["billable_tokens"] = agg["input_tokens"] + agg["output_tokens"] + agg["cache_write_tokens"]
        with self.path.open("a") as f:
            f.write(json.dumps({"summary": agg}, ensure_ascii=False) + "\n")
        return agg
