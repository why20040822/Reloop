"""F2 去重迁移脚本(2026-08-28): 清理 (owner_user_id, source_id) 重复行并建唯一索引。

用法(项目根目录, venv 内):
    python scripts/dedup_talents.py            # 只扫描, 打印重复报告(不改数据)
    python scripts/dedup_talents.py --apply    # 备份 -> 去重 -> 清孤儿 -> 建唯一索引

行为:
  1. 扫描重复: 同 (owner_user_id, source_id) 多行; source_id 为空的单独统计。
  2. --apply 时先备份整表 -> talent_profiles_bak_<时间戳>(可随时回滚)。
  3. 每个 (owner, source_id) 组保留 id 最大的一行(最新一次导入), 删其余。
  4. 清理孤儿: interaction_records / feedback_logs / recommendations 中
     引用已删 talent_id 的行(与 BUG-105 级联逻辑一致)。
  5. 建唯一索引 uq_talent_owner_source(MySQL ADD UNIQUE KEY / SQLite UNIQUE INDEX)。

安全: 默认 dry-run, 不加 --apply 绝不动数据; 删除前必须成功建备份。
"""

import sys
import datetime as dt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, inspect, text

from reloop.config import settings


def main() -> int:
    apply = "--apply" in sys.argv
    engine = create_engine(settings.sync_dsn, future=True)
    insp = inspect(engine)
    if not insp.has_table("talent_profiles"):
        print("[!] talent_profiles 表不存在, 无需迁移")
        return 0

    with engine.begin() as conn:
        # ---- 1. 扫描重复 ----
        dups = conn.execute(text(
            "SELECT owner_user_id, source_id, COUNT(*) c, "
            "GROUP_CONCAT(id ORDER BY id) ids "
            "FROM talent_profiles WHERE source_id IS NOT NULL AND source_id <> '' "
            "GROUP BY owner_user_id, source_id HAVING c > 1"
        )).fetchall()
        empty = conn.execute(text(
            "SELECT COUNT(*) FROM talent_profiles "
            "WHERE source_id IS NULL OR source_id = ''"
        )).scalar()

        print(f"== 扫描结果 ==")
        print(f"重复 (owner, source_id) 组数: {len(dups)}")
        for r in dups[:20]:
            print(f"  owner={r[0]} source_id={r[1]} count={r[2]} ids=[{r[3]}]")
        if len(dups) > 20:
            print(f"  ... 其余 {len(dups) - 20} 组略")
        print(f"source_id 为空的行数: {empty}")

        if not apply:
            print("\n[dry-run] 未做任何修改。确认后加 --apply 执行 备份->去重->建索引。")
            return 0

        if not dups:
            print("\n无重复数据, 直接建唯一索引。")
        else:
            # ---- 2. 备份 ----
            bak = f"talent_profiles_bak_{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}"
            conn.execute(text(f"CREATE TABLE {bak} AS SELECT * FROM talent_profiles"))
            print(f"\n[backup] 已备份整表 -> {bak}")

            # ---- 3. 去重(每组保留 id 最大) + 4. 清孤儿 ----
            total_deleted = 0
            orphan_reco = orphan_inter = orphan_fb = 0
            for r in dups:
                ids = [int(x) for x in str(r[3]).split(",")]
                keep = max(ids)
                del_ids = [i for i in ids if i != keep]
                conn.execute(text(
                    "DELETE FROM talent_profiles WHERE id IN "
                    f"({','.join(str(i) for i in del_ids)})"
                ))
                total_deleted += len(del_ids)
                orphan_reco += conn.execute(text(
                    f"DELETE FROM recommendations WHERE talent_id IN "
                    f"({','.join(str(i) for i in del_ids)})"
                ).rowcount or 0)
                orphan_inter += conn.execute(text(
                    f"DELETE FROM interaction_records WHERE talent_id IN "
                    f"({','.join(str(i) for i in del_ids)})"
                ).rowcount or 0)
                orphan_fb += conn.execute(text(
                    f"DELETE FROM feedback_logs WHERE talent_id IN "
                    f"({','.join(str(i) for i in del_ids)})"
                ).rowcount or 0)
            print(f"[dedup] 删除重复人才行: {total_deleted}")
            print(f"[orphan] 清理孤儿: recommendations={orphan_reco} "
                  f"interaction_records={orphan_inter} feedback_logs={orphan_fb}")

        # ---- 5. 建唯一索引 ----
        dialect = engine.dialect.name
        if dialect == "mysql":
            has = conn.execute(text(
                "SELECT COUNT(*) FROM information_schema.statistics "
                "WHERE table_schema = DATABASE() AND table_name = 'talent_profiles' "
                "AND index_name = 'uq_talent_owner_source'"
            )).scalar()
            if not has:
                conn.execute(text(
                    "ALTER TABLE talent_profiles "
                    "ADD UNIQUE KEY uq_talent_owner_source (owner_user_id, source_id)"
                ))
                print("[index] MySQL 唯一键 uq_talent_owner_source 已创建")
            else:
                print("[index] 唯一键已存在, 跳过")
        else:
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_talent_owner_source "
                "ON talent_profiles (owner_user_id, source_id)"
            ))
            print("[index] SQLite 唯一索引已创建/已存在")

        print("\n[done] 去重迁移完成。之后重启服务(init_db 会自动校验索引)。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
