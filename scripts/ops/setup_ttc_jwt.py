#!/usr/bin/env python3
"""
安全写入 TTC JWT Token 到 ~/.ttc/ttc_jwt.env。

运行后终端会提示粘贴 JWT Token，输入不可见，写入后文件权限设为 600。
"""

import getpass
import os
from pathlib import Path


def main() -> int:
    ttc_dir = Path.home() / ".ttc"
    ttc_dir.mkdir(parents=True, exist_ok=True)
    env_path = ttc_dir / "ttc_jwt.env"

    print("请输入 TTC JWT Token（从浏览器开发者工具复制，粘贴时不显示）:")
    token = getpass.getpass("TTC_JWT_TOKEN=").strip()

    if not token:
        print("错误：Token 不能为空。")
        return 1

    # 简单校验格式：通常是 eyJ... 开头的 JWT
    if not token.startswith("eyJ"):
        print("警告：输入内容不以 eyJ 开头，可能不是标准 JWT，请确认是否正确。")
        confirm = input("仍要写入吗？(y/N): ").strip().lower()
        if confirm not in ("y", "yes"):
            print("已取消写入。")
            return 1

    content = f"TTC_JWT_TOKEN={token}\n"
    env_path.write_text(content, encoding="utf-8")
    os.chmod(env_path, 0o600)

    print(f"[OK] JWT Token 已安全写入：{env_path}")
    print(f"[OK] 文件权限：{oct(os.stat(env_path).st_mode)[-3:]}")
    print("现在可以运行：python3 scripts/ops/full_pipeline_report.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
