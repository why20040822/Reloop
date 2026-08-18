"""agent 主循环：complete → 执行工具 → 回填结果 → 直到无工具调用或 max_turns。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .backends.base import ChatBackend
from .meter import Meter
from .session import Session
from .tools.base import ToolContext
from .tools.registry import TOOLS, dispatch


@dataclass
class RunResult:
    final_text: str
    summary: dict
    compacts: int
    hit_max_turns: bool


def run_agent(
    backend: ChatBackend,
    task: str,
    system: str,
    ctx: ToolContext,
    meter: Meter,
    max_turns: int = 30,
    verbose: bool = True,
) -> RunResult:
    session = Session(compact_threshold=120_000)
    session.add_user(f"[模式: {ctx.mode}] [工作目录: {ctx.cwd}]\n\n{task}")

    final_text = ""
    hit_max = False
    crashed = False
    for turn in range(1, max_turns + 1):
        session.maybe_compact(backend)
        try:
            resp = backend.complete(system, session.messages, TOOLS)
        except Exception as e:
            final_text = f"(API 故障，任务中断: {type(e).__name__}: {e})"
            crashed = True
            break
        meter.record(turn, backend.cfg.model, resp.usage)
        session.add_assistant(resp)

        if not resp.tool_calls:
            final_text = resp.text
            break

        results = []
        for tc in resp.tool_calls:
            out, is_err = dispatch(ctx, tc.name, tc.arguments)
            if verbose:
                flag = "✗" if is_err else "✓"
                print(f"  [{turn}] {flag} {tc.name}({ _brief(tc.arguments)}) -> {len(out)} chars")
            results.append((tc, out, is_err))
        session.add_tool_results(results)
    else:
        hit_max = True
        final_text = "(达到 max_turns，未完成)"

    summary = meter.summary()
    if crashed:
        summary["crashed"] = True
    return RunResult(final_text=final_text, summary=summary, compacts=session.compacts, hit_max_turns=hit_max)


def _brief(args: dict) -> str:
    parts = []
    for k, v in args.items():
        s = str(v).replace("\n", "\\n")
        parts.append(f"{k}={s[:60]}")
    return ", ".join(parts)[:120]
