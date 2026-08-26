"""补齐 contact_status 默认值 + 全量校验。"""
import logging
import os
import sys

os.chdir("F:/ttc/Reloop")
sys.path.insert(0, "F:/ttc/Reloop")
logging.basicConfig(level=logging.WARNING)

from sqlalchemy import text as sa_text
from reloop.db.engine import SessionLocal

OWNER = "guest_shared"
db = SessionLocal()
try:
    c = db.execute(sa_text(
        "UPDATE talent_profiles SET contact_status=:d "
        "WHERE owner_user_id=:o AND (contact_status IS NULL OR contact_status='')"
    ), {"d": "未联系", "o": OWNER})
    db.commit()
    print(f"contact_status 补默认值: {c.rowcount} 行")

    rows = db.execute(sa_text(
        "SELECT COUNT(*) AS n FROM talent_profiles WHERE owner_user_id=:o"
    ), {"o": OWNER}).fetchone()
    print("talent_profiles 总数:", rows["n"] if hasattr(rows, 'keys') else rows[0])
finally:
    db.close()
