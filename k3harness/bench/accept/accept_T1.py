#!/usr/bin/env python3
"""T1 验收：解析器修复。

用法: python accept_T1.py <workspace>

验收标准:
  对 workspace/samples/ 下 3 份样本各运行 `python3 parser.py <样本>`，
  解析其 stdout 的 JSON，三个字段必须全部等于预期值:
    sample1.txt -> name=李会   phone=15634118755 city=北京
    sample2.txt -> name=王强   phone=13811556677 city=上海
    sample3.txt -> name=陈思远 phone=13720240117 city=深圳
  任一字段不符即 exit 1，stderr 打印差异。
"""
import json
import subprocess
import sys
from pathlib import Path

EXPECTED = {
    "sample1.txt": {"name": "李会", "phone": "15634118755", "city": "北京"},
    "sample2.txt": {"name": "王强", "phone": "13811556677", "city": "上海"},
    "sample3.txt": {"name": "陈思远", "phone": "13720240117", "city": "深圳"},
}


def fail(msg: str) -> None:
    print(f"[T1 FAIL] {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    if len(sys.argv) != 2:
        fail("用法: python accept_T1.py <workspace>")
    ws = Path(sys.argv[1])
    parser = ws / "parser.py"
    if not parser.is_file():
        fail(f"缺少 {parser}")
    for sample, expected in EXPECTED.items():
        path = ws / "samples" / sample
        if not path.is_file():
            fail(f"缺少样本 {path}")
        r = subprocess.run(
            [sys.executable, str(parser), str(path)],
            capture_output=True, text=True, cwd=str(ws), timeout=30,
        )
        if r.returncode != 0:
            fail(f"parser.py 在 {sample} 上退出码 {r.returncode}: {r.stderr.strip()[:300]}")
        try:
            got = json.loads(r.stdout)
        except json.JSONDecodeError:
            fail(f"parser.py 在 {sample} 上输出非 JSON: {r.stdout.strip()[:300]}")
        for field, want in expected.items():
            if got.get(field) != want:
                fail(f"{sample} 字段 {field}: 期望 {want!r}, 实际 {got.get(field)!r}")
    print("[T1 OK] 3 份样本的 name/phone/city 全部正确")


if __name__ == "__main__":
    main()
