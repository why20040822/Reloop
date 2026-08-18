#!/usr/bin/env python3
"""T9 文档撰写 验收脚本。

验收标准（针对 workspace/api_doc.md，全部满足才 exit 0）：
1. 存在含"候选人入库"或"ingest"（大小写不敏感）的小节标题（# 开头的行）。
2. 文中出现 `POST /api/ingest`。
3. 存在 markdown 表格（连续 | 开头的行块），其文本同时含 name、phone、fingerprint。
4. 文中出现错误码 DUPLICATE 和 INVALID_PHONE。
5. 存在 ```json 代码块（新增内容中应有响应示例）。
6. 原有小节（候选人检索/候选人详情/统计概览）仍保留——不得推倒重写丢内容。

用法：python3 accept_T9.py <workspace>
"""
import re
import sys
from pathlib import Path


def fail(msg: str) -> None:
    print(f"[T9 FAIL] {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    if len(sys.argv) != 2:
        fail("用法: python3 accept_T9.py <workspace>")
    ws = Path(sys.argv[1])
    path = ws / "api_doc.md"
    if not path.is_file():
        fail(f"{path} 不存在")
    text = path.read_text(encoding="utf-8")

    # 1. 新增小节标题
    headings = [l for l in text.splitlines() if l.lstrip().startswith("#")]
    if not any(("候选人入库" in h) or ("ingest" in h.lower()) for h in headings):
        fail("未找到含「候选人入库」或「ingest」的小节标题")

    # 2. 接口路径
    if not re.search(r"POST\s+/api/ingest", text):
        fail("未找到 `POST /api/ingest`")

    # 3. 字段表：找含 name/phone/fingerprint 的表格块
    table_blocks = []
    cur = []
    for line in text.splitlines() + [""]:
        if line.strip().startswith("|"):
            cur.append(line)
        else:
            if cur:
                table_blocks.append("\n".join(cur))
                cur = []
    ok_table = any(
        all(k in block for k in ("name", "phone", "fingerprint"))
        for block in table_blocks
    )
    if not ok_table:
        fail("未找到同时包含 name / phone / fingerprint 的 markdown 字段表")

    # 4. 错误码
    for code in ("DUPLICATE", "INVALID_PHONE"):
        if code not in text:
            fail(f"未找到错误码 {code}")

    # 5. json 响应示例代码块
    if "```json" not in text:
        fail("未找到 ```json 响应示例代码块")

    # 6. 原有小节不得丢失
    for old in ("候选人检索", "候选人详情", "统计概览"):
        if old not in text:
            fail(f"原有小节「{old}」被删除或改写丢失")

    print("[T9 PASS] api_doc.md 新增「候选人入库」小节要素齐全，原有内容保留")
    sys.exit(0)


if __name__ == "__main__":
    main()
