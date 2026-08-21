#!/usr/bin/env python3
"""生产数据归属迁移(Linda): 把孤儿 TTC open_id 的存量数据改挂到 Linda 的飞书 fs_ 登录身份。

⚠️ 生产写操作。默认 dry-run(只打印将影响的行数, 不改库)。
    真正执行需显式传 --confirm, 且必须提供 --target=<Linda 的 fs_ open_id>。

用法:
  python _migrate_linda.py --dry-run                 # 仅核对孤儿数据行数
  python _migrate_linda.py --target=fs_xxxx --confirm # 真执行迁移(先自动备份 users 表)
"""
import argparse
import pymysql
from reloop.config import settings

ORPHAN = "ou_ff894386d0ca340dcc2f7bdc53c57a81"
TABLES = ["talent_profiles", "recommendations", "positions", "feedback_logs", "interaction_records"]


def dsn_parts():
    dsn = settings.sync_dsn
    rest = dsn.split("://", 1)[1]
    auth, host_db = rest.split("@", 1)
    user, pwd = auth.split(":", 1)
    host_port, db = host_db.split("/", 1)
    if "?" in db:
        db = db.split("?", 1)[0]
    host, port = host_port.split(":") if ":" in host_port else (host_port, "3306")
    return dict(host=host, port=int(port), user=user, password=pwd, database=db)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="")
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.dry_run and not args.confirm:
        print("未指定 --confirm, 进入 dry-run 仅核对行数。")
    if not args.confirm and not args.target:
        args.dry_run = True
    if args.confirm and not args.target:
        raise SystemExit("错误: --confirm 时必须提供 --target=<Linda 的 fs_ open_id>")

    p = dsn_parts()
    conn = pymysql.connect(charset=settings.mysql_charset, connect_timeout=8,
                           read_timeout=30, cursorclass=pymysql.cursors.DictCursor, **p)
    print(f"connected -> {p['host']}:{p['port']}/{p['database']}")

    with conn.cursor() as c:
        print(f"\n=== 孤儿 owner '{ORPHAN}' 当前各表行数 ===")
        total = 0
        for tbl in TABLES:
            try:
                c.execute(f"SELECT COUNT(*) AS n FROM {tbl} WHERE owner_user_id=%s", (ORPHAN,))
                n = c.fetchone()["n"]
            except Exception as e:  # noqa: BLE001
                n = f"ERR:{e}"
            print(f"  {tbl}: {n}")
            if isinstance(n, int):
                total += n
        print(f"  合计待迁移行数: {total}")

        if args.confirm:
            print(f"\n[confirm] 备份 users 表 -> users_bak_{ORPHAN[:8]}")
            c.execute(f"DROP TABLE IF EXISTS users_bak_{ORPHAN[:8]}")
            c.execute(f"CREATE TABLE users_bak_{ORPHAN[:8]} LIKE users")
            c.execute(f"INSERT INTO users_bak_{ORPHAN[:8]} SELECT * FROM users")
            conn.commit()
            print("  users 备份完成。")

            moved = 0
            for tbl in TABLES:
                c.execute(f"UPDATE {tbl} SET owner_user_id=%s WHERE owner_user_id=%s", (args.target, ORPHAN))
                affected = c.rowcount
                print(f"  UPDATE {tbl}: {affected} 行")
                moved += affected
            conn.commit()
            print(f"\n[confirm] 共迁移 {moved} 行 -> {args.target}")
            c.execute("SELECT COUNT(*) AS n FROM talent_profiles WHERE owner_user_id=%s", (args.target,))
            print(f"  校验: {args.target} 现 talent_profiles={c.fetchone()['n']}")
    conn.close()


if __name__ == "__main__":
    main()
