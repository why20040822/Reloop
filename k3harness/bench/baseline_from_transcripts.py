"""从历史 Claude Code 转录（jsonl）提取 token 基线。

按"用户新发起一段请求"切任务段，聚合每段 usage，按关键词粗分画像类别，
产出 baseline_report.md（参考基线；主基线用 claude -p 重放）。
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

TRANSCRIPT_DIR = Path.home() / ".claude" / "projects" / "-Users-ashley-Downloads-ttc-----"
OUT = Path(__file__).parent.parent / "runs" / "baseline_report.md"

CATEGORIES = {
    "数据修复/回填": r"回填|修复.*数据|去重|重导|repair|backfill",
    "JD匹配/评分": r"JD|jd|打分|评分|匹配|Top\s?\d|jd_match",
    "飞书集成": r"飞书|feishu|lark|多维表格|Base",
    "解析器修复": r"解析|parser|误识别|姓名|手机号",
    "入库链路": r"入库|pipeline|ingest|幂等|outbox|投递",
    "插件调试": r"插件|extension|DOM|选择器|userscript",
    "长文归纳": r"纪要|逐字稿|总结.*会议|妙记",
    "文档撰写": r"文档|设计|方案|plan|design",
    "运维脚本": r"cron|同步|脚本|白名单|deploy|运维",
}


def iter_rows(path: Path):
    for line in path.read_text(errors="replace").splitlines():
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def user_text(row: dict) -> str:
    msg = row.get("message") or {}
    if row.get("type") != "user":
        return ""
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def classify(text: str) -> str:
    for cat, pat in CATEGORIES.items():
        if re.search(pat, text, re.IGNORECASE):
            return cat
    return "其他"


def main() -> None:
    files = sorted(TRANSCRIPT_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    segments = []  # (file, cat, first_text, usage dict, turns)
    for fp in files:
        cur = None
        for row in iter_rows(fp):
            t = row.get("type")
            if t == "user":
                text = user_text(row)
                # 新任务段：真实用户输入（非 tool_result、非系统提醒）
                if text and not text.startswith("<system-reminder") and "tool_result" not in json.dumps(row.get("message", {}).get("content", ""))[:200]:
                    if cur and cur["turns"]:
                        segments.append(cur)
                    cur = {"file": fp.name, "text": text[:200], "cat": classify(text),
                           "input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "turns": 0}
            elif t == "assistant" and cur is not None:
                u = (row.get("message") or {}).get("usage") or {}
                cur["input"] += u.get("input_tokens", 0)
                cur["output"] += u.get("output_tokens", 0)
                cur["cache_read"] += u.get("cache_read_input_tokens", 0)
                cur["cache_write"] += u.get("cache_creation_input_tokens", 0)
                cur["turns"] += 1
        if cur and cur["turns"]:
            segments.append(cur)

    by_cat = defaultdict(list)
    for s in segments:
        s["billable"] = s["input"] + s["output"] + s["cache_write"]
        by_cat[s["cat"]].append(s)

    def pct(vals, p):
        if not vals:
            return 0
        vals = sorted(vals)
        return vals[min(len(vals) - 1, int(len(vals) * p))]

    lines = ["# 历史转录 token 基线（参考基线）", "",
             f"转录文件 {len(files)} 个，切出任务段 {len(segments)} 个。", "",
             "| 画像类别 | 段数 | 中位 billable tokens | P90 | 中位轮数 | 中位 cache_read |",
             "|---|---|---|---|---|---|"]
    for cat, segs in sorted(by_cat.items(), key=lambda kv: -sum(s["billable"] for s in kv[1])):
        lines.append(
            f"| {cat} | {len(segs)} | {pct([s['billable'] for s in segs], 0.5):,} "
            f"| {pct([s['billable'] for s in segs], 0.9):,} | {pct([s['turns'] for s in segs], 0.5)} "
            f"| {pct([s['cache_read'] for s in segs], 0.5):,} |"
        )
    total_billable = sum(s["billable"] for s in segments)
    total_cache_read = sum(s["cache_read"] for s in segments)
    lines += ["",
              f"**总计**：billable {total_billable:,} tokens（input+output+cache_write），"
              f"cache_read {total_cache_read:,}（缓存命中部分单列）。", "",
              "注：cache_read 命中提示 Kimi 端点 prompt caching 生效；主对比以 claude -p 重放腿为准。"]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines))
    print(f"segments={len(segments)} total_billable={total_billable:,} -> {OUT}")


if __name__ == "__main__":
    sys.exit(main())
