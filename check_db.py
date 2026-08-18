"""RDS MySQL 连通性自检 (本地运行, 不碰任何云 OpenAPI / AccessKey)。

用途:
  在【你本地机器】上验证 .env 里的 BRAINX_MYSQL_* 能否连上真库。
  沙箱/CI 通常连不上阿里云 RDS(白名单只放通你本机公网 IP), 所以这个脚本
  设计成在本地跑: python check_db.py

它复用项目自己的配置 (reloop.config.settings), 不重复写任何凭据。
连库只需要 BRAINX_MYSQL_*, 不需要阿里云 AccessKey —— AccessKey 是账号级主密钥,
只在调用阿里云 OpenAPI 时才用, 本项目不涉及, 请勿写进 .env 或代码。

依赖: pymysql + cryptography (requirements.txt 已含), 无需额外安装。
"""

import socket
import sys
import time

from reloop.config import settings


def _mask(pwd: str) -> str:
    if not pwd:
        return "(空)"
    return pwd[0] + "*" * max(1, len(pwd) - 2) + pwd[-1]


def main() -> int:
    host = settings.mysql_host
    port = settings.mysql_port
    user = settings.mysql_user
    db = settings.mysql_database

    print("=" * 60)
    print("Reloop RDS MySQL 连通性自检")
    print("=" * 60)
    if settings.database_url:
        print(f"[提示] BRAINX_DATABASE_URL 已设置为 {settings.database_url!r},")
        print("       后端实际会用它 (通常是本地 SQLite), 而不是下面的 MySQL。")
        print("       如需测真库, 请把 BRAINX_DATABASE_URL 留空。\n")
    print(f"目标: host={host} port={port} user={user} db={db} pwd={_mask(settings.mysql_password)}")
    print("-" * 60)

    # ---- 1. DNS 解析 ----
    try:
        ip = socket.gethostbyname(host)
        print(f"[1/3] DNS 解析      : OK  -> {ip}")
    except Exception as e:  # noqa: BLE001
        print(f"[1/3] DNS 解析      : 失败 -> {type(e).__name__}: {e}")
        if "xxxxx" in host or host.startswith("rm-xxxxx"):
            print("      ↳ host 还是占位符。请到阿里云控制台『数据库连接』复制真实【外网地址】"
                  "(形如 rm-bp1xxxxxxxx.mysql.rds.aliyuncs.com) 填进 .env 的 BRAINX_MYSQL_HOST。")
        else:
            print("      ↳ 域名无法解析: 检查地址是否写错, 或该地址是否为『内网地址』(内网地址本地连不上, 需申请外网地址)。")
        return 1

    # ---- 2. TCP 端口连通 ----
    t0 = time.time()
    sk = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sk.settimeout(6)
    try:
        sk.connect((host, port))
        print(f"[2/3] TCP {port} 端口 : 可达 ({(time.time() - t0) * 1000:.0f}ms)")
    except Exception as e:  # noqa: BLE001
        print(f"[2/3] TCP {port} 端口 : 不可达 -> {type(e).__name__}: {e}")
        print("      ↳ 域名能解析但端口连不上, 最常见原因: RDS 白名单没放通你当前机器的公网 IP。")
        print("        到 RDS 控制台『白名单设置』把本机公网 IP 加进去 (可搜索 '我的公网IP' 查到)。")
        return 2
    finally:
        sk.close()

    # ---- 3. MySQL 握手 + 建表状态 ----
    try:
        import pymysql
    except ImportError:
        print("[3/3] MySQL 握手    : 跳过 -> 未安装 pymysql, 请先 pip install -r requirements.txt")
        return 3

    try:
        conn = pymysql.connect(
            host=host, port=port, user=user, password=settings.mysql_password,
            database=db, charset=settings.mysql_charset, connect_timeout=8,
        )
    except Exception as e:  # noqa: BLE001
        print(f"[3/3] MySQL 握手    : 失败 -> {type(e).__name__}: {e}")
        print("      ↳ 网络已通但登录/选库失败, 检查: 账号密码是否正确、库名 reloop 是否存在、该账号是否有权限。")
        return 4

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT VERSION()")
            ver = cur.fetchone()[0]
            expect = ("users", "talent_profiles", "positions",
                      "interaction_records", "recommendations", "feedback_logs")
            cur.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema=%s",
                (db,),
            )
            present = {r[0] for r in cur.fetchall()}
        print(f"[3/3] MySQL 握手    : 连上了! MySQL {ver}")
        missing = [t for t in expect if t not in present]
        print(f"      库内表数        : {len(present)}")
        if missing:
            print(f"      缺失业务表      : {missing}")
            print("      ↳ 启动一次 API 会自动建表 (uvicorn reloop.main:app), 或执行 sql/schema.sql。")
        else:
            print("      6 张业务表      : 全部就绪 ✓")
            # 附带各表行数, 方便确认数据是否真的在库里
            with conn.cursor() as cur:
                for tb in expect:
                    cur.execute(f"SELECT COUNT(*) FROM `{tb}`")  # noqa: S608 (表名来自固定白名单)
                    print(f"        {tb:<22} {cur.fetchone()[0]} 行")
        print("\n结论: ✅ 真库连接成功。")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
