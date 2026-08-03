#!/usr/bin/env python3
"""Check an Aliyun RDS MySQL connection and print table counts.

Required env:
  TTC_MYSQL_HOST, TTC_MYSQL_USER, TTC_MYSQL_PASSWORD
Optional env:
  TTC_MYSQL_PORT=3306, TTC_MYSQL_DATABASE

The RDS instance id, such as rm-bp12ok9so2ma3i3j7, is not a network endpoint.
Use the instance connection address from Aliyun RDS console.
"""
import os
import sys
from typing import Iterable


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def main() -> int:
    host = env("TTC_MYSQL_HOST")
    user = env("TTC_MYSQL_USER")
    password = env("TTC_MYSQL_PASSWORD")
    database = env("TTC_MYSQL_DATABASE")
    port = int(env("TTC_MYSQL_PORT", "3306"))

    missing = [name for name, value in {
        "TTC_MYSQL_HOST": host,
        "TTC_MYSQL_USER": user,
        "TTC_MYSQL_PASSWORD": password,
    }.items() if not value]
    if missing:
        print("Missing env: " + ", ".join(missing), file=sys.stderr)
        print("Note: rm-bp12ok9so2ma3i3j7 is an RDS instance id, not a MySQL host.", file=sys.stderr)
        return 2

    try:
        import pymysql
    except Exception as e:
        print(f"pymysql is required: {e}", file=sys.stderr)
        return 2

    conn = pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database or None,
        connect_timeout=8,
        read_timeout=20,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT VERSION() AS version, DATABASE() AS db")
            info = cur.fetchone()
            print(f"connected version={info['version']} database={info['db']}")

            if not database:
                cur.execute("SHOW DATABASES")
                names = [row["Database"] for row in cur.fetchall()]
                print("databases=" + ", ".join(names[:30]))
                return 0

            cur.execute("SHOW TABLES")
            table_key = f"Tables_in_{database}"
            tables = [row.get(table_key) or next(iter(row.values())) for row in cur.fetchall()]
            print(f"tables={len(tables)}")
            for table in tables[:50]:
                cur.execute(f"SELECT COUNT(*) AS n FROM `{table}`")
                row = cur.fetchone()
                print(f"{table}\t{row['n']}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
