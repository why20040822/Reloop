"""k3h CLI：probe / run / repl / bench。"""
from __future__ import annotations

import json
from pathlib import Path

import typer

from .agent import run_agent
from .backends.anthropic import AnthropicBackend
from .backends.openai import OpenAIBackend
from .config import load_config
from .meter import Meter
from .tools.base import ToolContext

app = typer.Typer(add_completion=False, no_args_is_help=True)

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "runs"
SYSTEM_PROMPT_PATH = ROOT / "k3h" / "prompts" / "system_zh.md"


def _system() -> str:
    return SYSTEM_PROMPT_PATH.read_text()


def _backend(name: str = "anthropic"):
    cfg = load_config()
    if not cfg.api_key:
        typer.echo("错误：找不到 API key（ANTHROPIC_AUTH_TOKEN 或 ~/.claude/settings.json）", err=True)
        raise typer.Exit(1)
    if name == "openai":
        return OpenAIBackend(cfg)
    return AnthropicBackend(cfg)


@app.command()
def probe():
    """探测 Kimi 端点能力：协议/工具调用/cache/流式，输出结论 JSON。"""
    import httpx

    cfg = load_config()
    report: dict = {"model": cfg.model, "checks": {}}

    def check(name: str, fn):
        try:
            report["checks"][name] = {"ok": True, "detail": fn()}
        except Exception as e:
            report["checks"][name] = {"ok": False, "detail": str(e)[:300]}

    be = AnthropicBackend(cfg)

    def _basic():
        r = be.complete("你是助手。", [{"role": "user", "content": "回复：ok"}], tools=[], max_tokens=16)
        return f"text={r.text!r} usage={r.usage.input_tokens}in/{r.usage.output_tokens}out stop={r.stop_reason}"

    def _tool_use():
        tool = [{"name": "get_time", "description": "获取当前时间", "input_schema": {"type": "object", "properties": {}}}]
        r = be.complete("", [{"role": "user", "content": "现在几点？用工具查。"}], tools=tool, max_tokens=512)
        if r.tool_calls:
            return f"tool_call={r.tool_calls[0].name} args={r.tool_calls[0].arguments}"
        return f"未触发工具调用，text={r.text[:100]!r}"

    def _cache_control():
        payload = {
            "model": cfg.model,
            "max_tokens": 16,
            "system": [{"type": "text", "text": "你是助手。" * 100, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": "回复：ok"}],
        }
        r = httpx.post(be.url, headers=be._headers(), json=payload, timeout=cfg.timeout_s, trust_env=False)
        if r.status_code != 200:
            raise RuntimeError(f"{r.status_code}: {r.text[:200]}")
        u = r.json().get("usage", {})
        return f"接受 cache_control；usage={u}"

    def _sse():
        payload = {"model": cfg.model, "max_tokens": 16, "stream": True,
                   "messages": [{"role": "user", "content": "回复：ok"}]}
        events = 0
        with httpx.stream("POST", be.url, headers=be._headers(), json=payload, timeout=cfg.timeout_s, trust_env=False) as r:
            if r.status_code != 200:
                raise RuntimeError(f"{r.status_code}")
            for line in r.iter_lines():
                if line.startswith("event:"):
                    events += 1
        return f"SSE 正常，收到 {events} 个事件"

    def _openai(base: str):
        def fn():
            ob = OpenAIBackend(cfg, base_url=base)
            r = ob.complete("", [{"role": "user", "content": "回复：ok"}], tools=[], max_tokens=16)
            return f"text={r.text[:50]!r} usage={r.usage.input_tokens}in/{r.usage.output_tokens}out"
        return fn

    check("anthropic_basic", _basic)
    check("anthropic_tool_use", _tool_use)
    check("anthropic_cache_control", _cache_control)
    check("anthropic_sse", _sse)
    check("openai_kimi_v1", _openai("https://api.kimi.com/v1"))
    check("openai_moonshot", _openai("https://api.moonshot.cn/v1"))

    ok = [k for k, v in report["checks"].items() if v["ok"]]
    report["recommendation"] = (
        "默认 anthropic backend"
        if report["checks"].get("anthropic_basic", {}).get("ok")
        else "anthropic 不可用，检查 key/端点"
    )
    out = RUNS_DIR / "probe_report.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
    typer.echo(f"\n已写入 {out}")


@app.command()
def run(
    task: str,
    mode: str = typer.Option("apply", help="dry-run | apply"),
    max_turns: int = typer.Option(30),
    cwd: Path = typer.Option(Path.cwd(), help="工作目录"),
    task_id: str = "adhoc",
    backend: str = "anthropic",
    quiet: bool = False,
):
    """非交互执行一个任务（基准评测唯一入口）。"""
    be = _backend(backend)
    ctx = ToolContext(cwd=cwd.resolve(), mode=mode)
    meter = Meter(RUNS_DIR, task_id=task_id, leg="k3h")
    result = run_agent(be, task, _system(), ctx, meter, max_turns=max_turns, verbose=not quiet)
    typer.echo("\n===== 最终回复 =====")
    typer.echo(result.final_text)
    typer.echo("\n===== 计量 =====")
    typer.echo(json.dumps(result.summary, ensure_ascii=False, indent=2))
    if result.compacts:
        typer.echo(f"(触发 compact {result.compacts} 次)")


@app.command()
def repl(mode: str = typer.Option("apply"), cwd: Path = typer.Option(Path.cwd())):
    """简单 REPL（同一会话多轮）。"""
    from .session import Session

    be = _backend("anthropic")
    ctx = ToolContext(cwd=cwd.resolve(), mode=mode)
    meter = Meter(RUNS_DIR, task_id="repl", leg="k3h")
    session = Session()
    system = _system()
    typer.echo(f"k3h REPL（mode={mode}, cwd={cwd}），输入 exit 退出")
    while True:
        try:
            line = input("\nk3h> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if line in ("exit", "quit", ""):
            break
        session.add_user(line)
        for turn in range(1, 31):
            session.maybe_compact(be)
            resp = be.complete(system, session.messages, __import__("k3h.tools.registry", fromlist=["TOOLS"]).TOOLS)
            meter.record(turn, be.cfg.model, resp.usage)
            session.add_assistant(resp)
            if not resp.tool_calls:
                typer.echo(resp.text)
                break
            results = []
            from .tools.registry import dispatch

            for tc in resp.tool_calls:
                out, is_err = dispatch(ctx, tc.name, tc.arguments)
                typer.echo(f"  {'✗' if is_err else '✓'} {tc.name}")
                results.append((tc, out, is_err))
            session.add_tool_results(results)
    typer.echo(json.dumps(meter.summary(), ensure_ascii=False))


if __name__ == "__main__":
    app()
