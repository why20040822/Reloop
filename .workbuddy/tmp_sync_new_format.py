#!/usr/bin/env python3
"""本地同步脚本: TTC 人才库 -> 新格式 -> RDS(reloop_app)。

流程:
  1. init_db() 幂等补列(contact_phone/seek_status/education_history 等新列)
  2. 清理目标 owner 旧格式 talent_profiles + 全部推荐缓存(recommend_runs/recommendations)
  3. 全量拉取 TTC 378 条 -> 新 normalizer -> 写入 guest_shared 隔离键
  4. 校验: 行数 / 新字段覆盖率 / 样本

用法(conda reloop 环境):
  D:/enviroment/anaconda/envs/reloop/python.exe .workbuddy/tmp_sync_new_format.py
"""
import logging
import os
import sys

os.chdir("F:/ttc/Reloop")
sys.path.insert(0, "F:/ttc/Reloop")
logging.basicConfig(level=logging.WARNING)  # 抑制 LLM 404 噪音
logging.getLogger("reloop").setLevel(logging.ERROR)

from sqlalchemy import text as sa_text

from reloop.db.engine import SessionLocal, init_db
from reloop.db.models import TalentProfile
from reloop.modules.sync.client import talent_sync_service

OWNER = "guest_shared"  # 本地前端未登录默认隔离键
CLEAR_OTHER_OWNERS = False  # 只清理本次同步目标, 不误删其他用户数据


def main():
    print("[1/4] init_db 补列 ...")
    init_db()

    db = SessionLocal()
    try:
        # ---- 清理旧格式数据(目标 owner, 注意外键顺序: 先删子表) ----
        print("[2/4] 清理旧格式缓存 ...")
        for tbl in ("recommendations", "recommend_runs", "feedback_logs", "interaction_records"):
            try:
                c = db.execute(sa_text(f"DELETE FROM {tbl} WHERE owner_user_id=:o"), {"o": OWNER})
                print(f"  {tbl}(owner={OWNER}) 删除 {c.rowcount} 行")
            except Exception as e:  # noqa: BLE001
                print(f"  {tbl} 清理跳过: {e}")
        n = (
            db.query(TalentProfile)
            .filter(TalentProfile.owner_user_id == OWNER)
            .delete(synchronize_session=False)
        )
        print(f"  talent_profiles(owner={OWNER}) 删除 {n} 行")
        db.commit()

        # ---- 全量同步 ----
        print("[3/4] 从 TTC 拉取并同步(新格式) ...")
        count = talent_sync_service.sync_for_user(OWNER, db=db)
        db.commit()
        print(f"  同步完成: {count} 人")

        # ---- 校验 ----
        print("[4/4] 校验 ...")
        rows = (
            db.query(TalentProfile)
            .filter(TalentProfile.owner_user_id == OWNER)
            .all()
        )
        print(f"  talent_profiles 总行数: {len(rows)}")
        if rows:
            import json

            def cov(field):
                return sum(1 for r in rows if getattr(r, field))

            for f in ("work_history", "projects", "education_history", "notes",
                      "seek_status", "contact_phone", "contact_email",
                      "target_positions", "contact_status", "last_active_at"):
                print(f"  {f}: {cov(f)} / {len(rows)}")
            r = rows[0]
            print(f"  样本: {r.name} | {r.company} | {r.position}")
            print(f"    phone={r.contact_phone} email={r.contact_email}")
            print(f"    seek={r.seek_status} salary={r.current_salary}/{r.expected_salary}")
            print(f"    work_history[0]={json.dumps(r.work_history[0] if r.work_history else None, ensure_ascii=False)[:200]}")
            print(f"    notes={str(r.notes)[:150]}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
