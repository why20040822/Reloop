#!/usr/bin/env python3
"""T3 验收：JD 评分。

用法: python accept_T3.py <workspace>

验收标准:
  workspace/top10.json 必须满足:
  1. 是一个 JSON 数组，长度恰为 10。
  2. 每项为对象，含 rank(int)、file(str)、score(数值)、reason(非空中文字符串) 四个字段。
  3. rank 从 1 到 10 顺序排列，score 按降序（允许并列）。
  4. 每个 file 必须是 resumes/ 目录下真实存在的 .json 文件名，且不重复。
  5. 前 5 名的 file 与 golden（5 份强匹配简历）重合数 >= 4。
"""
import json
import sys
from pathlib import Path

GOLDEN = {"resume_03.json", "resume_07.json", "resume_11.json", "resume_14.json", "resume_18.json"}


def fail(msg: str) -> None:
    print(f"[T3 FAIL] {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    if len(sys.argv) != 2:
        fail("用法: python accept_T3.py <workspace>")
    ws = Path(sys.argv[1])
    top_path = ws / "top10.json"
    if not top_path.is_file():
        fail(f"缺少 {top_path}")

    try:
        data = json.loads(top_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        fail(f"top10.json 不是合法 JSON: {e}")

    if not isinstance(data, list):
        fail("top10.json 顶层必须是数组")
    if len(data) != 10:
        fail(f"数组长度应为 10，实际 {len(data)}")

    resume_dir = ws / "resumes"
    valid_files = {p.name for p in resume_dir.glob("*.json")} if resume_dir.is_dir() else set()
    if len(valid_files) != 20:
        fail(f"resumes/ 下应有 20 个 JSON，实际 {len(valid_files)}")

    seen_files = set()
    prev_score = None
    for i, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            fail(f"第 {i} 项不是对象")
        for field in ("rank", "file", "score", "reason"):
            if field not in item:
                fail(f"第 {i} 项缺少字段 {field}")
        if not isinstance(item["rank"], int) or isinstance(item["rank"], bool):
            fail(f"第 {i} 项 rank 不是整数")
        if item["rank"] != i:
            fail(f"第 {i} 项 rank 应为 {i}，实际 {item['rank']}")
        if not isinstance(item["file"], str):
            fail(f"第 {i} 项 file 不是字符串")
        fname = Path(item["file"]).name
        if fname not in valid_files:
            fail(f"第 {i} 项 file={item['file']!r} 不在 resumes/ 目录中")
        if fname in seen_files:
            fail(f"第 {i} 项 file={fname!r} 重复出现")
        seen_files.add(fname)
        if not isinstance(item["score"], (int, float)) or isinstance(item["score"], bool):
            fail(f"第 {i} 项 score 不是数值")
        if not 0 <= item["score"] <= 100:
            fail(f"第 {i} 项 score={item['score']} 超出 0-100")
        if prev_score is not None and item["score"] > prev_score:
            fail(f"第 {i} 项 score={item['score']} 高于前一项 {prev_score}，未按降序")
        prev_score = item["score"]
        if not isinstance(item["reason"], str) or not item["reason"].strip():
            fail(f"第 {i} 项 reason 为空")

    top5 = {Path(item["file"]).name for item in data[:5]}
    overlap = len(top5 & GOLDEN)
    if overlap < 4:
        fail(f"前 5 名与 golden 重合 {overlap}/5（要求 >=4）。top5={sorted(top5)}")

    print(f"[T3 OK] top10.json 结构合法，前 5 名命中 golden {overlap}/5")


if __name__ == "__main__":
    main()
