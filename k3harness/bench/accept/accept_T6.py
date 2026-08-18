#!/usr/bin/env python3
"""T6 长文归纳 验收脚本。

验收标准（全部满足才 exit 0）：
1. workspace/summary.json 存在且为合法 JSON（顶层为对象）。
2. 顶层含 decisions / action_items / key_quotes 三个键，均为非空列表。
3. action_items 每项为对象，且含 item 和 owner 两个非空字段。
4. 将 summary.json 中全部文本（键名除外）拼接后，golden 关键词命中率 >= 80%。
   golden 清单来自两份纪要的核心决策/人名/事项，每个关键词允许 1-3 个同义写法。

用法：python3 accept_T6.py <workspace>
"""
import json
import re
import sys
from pathlib import Path

# golden 关键词：每个条目是一组可接受写法（命中其一即算命中）。
GOLDEN = [
    ["姚堃", "York", "york"],                       # 核心人物 York 姚堃
    ["琳达", "Linda", "linda"],                     # 试点对象琳达
    ["简历库"],                                      # 暑期一横一纵之"横"
    ["AI原生工作流", "AI native", "AI-native", "AI原⽣"],  # AI native 工作流
    ["评分", "打分", "权重"],                        # 人岗匹配评分算法
    ["周四"],                                        # 周四 demo 评审节点
    ["demo", "Demo", "DEMO"],                        # 快速提效小 demo
    ["抓大放小", "抓⼤放⼩"],                        # 工作原则
    ["3倍", "三倍"],                                  # 3 倍效率提升目标
    ["always on", "always-on", "随时待命"],           # 工作方式要求
    ["小麦", "⼩⻨"],                                  # 核心产品小麦 agent
    ["openman", "OpenMan", "openMan"],               # 对内搜索工具 openman
]
HIT_RATE_REQUIRED = 0.8


def fail(msg: str) -> None:
    print(f"[T6 FAIL] {msg}", file=sys.stderr)
    sys.exit(1)


def collect_texts(obj, out) -> None:
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            collect_texts(v, out)
    elif isinstance(obj, list):
        for v in obj:
            collect_texts(v, out)
    elif obj is not None:
        out.append(str(obj))


def main() -> None:
    if len(sys.argv) != 2:
        fail("用法: python3 accept_T6.py <workspace>")
    ws = Path(sys.argv[1])
    path = ws / "summary.json"
    if not path.is_file():
        fail(f"summary.json 不存在于 {ws}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        fail(f"summary.json 不是合法 JSON: {e}")
    if not isinstance(data, dict):
        fail("summary.json 顶层必须是 JSON 对象")

    for key in ("decisions", "action_items", "key_quotes"):
        if key not in data:
            fail(f"缺少顶层键: {key}")
        if not isinstance(data[key], list) or not data[key]:
            fail(f"{key} 必须是非空数组")

    for i, it in enumerate(data["action_items"]):
        if not isinstance(it, dict) or "item" not in it or "owner" not in it:
            fail(f"action_items[{i}] 必须含 item 和 owner 字段")
        if not str(it["item"]).strip() or not str(it["owner"]).strip():
            fail(f"action_items[{i}] 的 item/owner 不能为空")

    texts: list[str] = []
    collect_texts(data, texts)
    blob = re.sub(r"\s+", "", "".join(texts)).lower()

    missed = []
    for variants in GOLDEN:
        if not any(re.sub(r"\s+", "", v).lower() in blob for v in variants):
            missed.append(variants[0])
    hit = len(GOLDEN) - len(missed)
    rate = hit / len(GOLDEN)
    if rate < HIT_RATE_REQUIRED:
        fail(f"golden 关键词命中率 {hit}/{len(GOLDEN)} = {rate:.0%} < {HIT_RATE_REQUIRED:.0%}，"
             f"未命中: {', '.join(missed)}")

    print(f"[T6 PASS] 关键词命中 {hit}/{len(GOLDEN)} = {rate:.0%}")
    sys.exit(0)


if __name__ == "__main__":
    main()
