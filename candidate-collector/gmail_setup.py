from __future__ import annotations

import getpass
import imaplib
import re
import subprocess
import sys

from gmail_sync import (
    EMAIL_SERVICE,
    KEYCHAIN_ACCOUNT,
    PASSWORD_SERVICE,
)


def save_secret(service: str, value: str) -> None:
    subprocess.run(
        [
            "security", "add-generic-password",
            "-a", KEYCHAIN_ACCOUNT,
            "-s", service,
            "-w", value,
            "-U",
        ],
        check=True,
        capture_output=True,
    )


def main() -> int:
    print("TTC Gmail 只读同步设置")
    print("凭证只保存到当前 Mac 的钥匙串，不会写入项目文件。")
    address = input("个人 Gmail 地址：").strip()
    if not re.fullmatch(r"[^@\s]+@gmail\.com", address, re.I):
        print("请输入有效的个人 @gmail.com 地址。", file=sys.stderr)
        return 2
    app_password = getpass.getpass("Google 16位应用专用密码：").replace(" ", "").strip()
    if len(app_password) != 16:
        print("应用专用密码应为16位；不要输入日常 Gmail 登录密码。", file=sys.stderr)
        return 2
    print("正在验证 Gmail 只读连接...")
    connection = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    try:
        connection.login(address, app_password)
        result, _ = connection.select("INBOX", readonly=True)
        if result != "OK":
            raise RuntimeError("无法打开收件箱")
    except Exception as exc:
        print("连接失败：" + str(exc), file=sys.stderr)
        return 1
    finally:
        try:
            connection.logout()
        except Exception:
            pass
    save_secret(EMAIL_SERVICE, address)
    save_secret(PASSWORD_SERVICE, app_password)
    print("设置成功。现在可以运行：python3 gmail_sync.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
