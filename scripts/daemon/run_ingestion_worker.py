#!/usr/bin/env python3
"""Run one bounded Reloop outbox delivery batch after package installation."""

from __future__ import annotations

import shutil
import subprocess
import sys


def main() -> int:
    executable = shutil.which("reloop-worker")
    if not executable:
        print("请先安装 Reloop：python -m pip install -e reloop", file=sys.stderr)
        return 2
    return subprocess.call([executable, *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
