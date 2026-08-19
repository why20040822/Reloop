"""服务器端全量同步脚本: TTC -> RDS (owner = webapp 默认用户)。

注意:
  - 必须 os.chdir 到 /opt/reloop, 否则 pydantic-settings 读不到相对路径 .env
  - sync_for_user 传外部 session 时只 flush, 脚本必须自己 db.commit()
"""
import os
os.chdir('/opt/reloop')
import sys
sys.path.insert(0, '/opt/reloop')

import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')

from reloop.db.engine import SessionLocal
from reloop.modules.sync.client import talent_sync_service

OWNER = 'ou_ff894386d0ca340dcc2f7bdc53c57a81'

db = SessionLocal()
try:
    n = talent_sync_service.sync_for_user(OWNER, db=db)
    db.commit()
    print('SYNC_DONE synced=%d' % n, flush=True)
except Exception as e:  # noqa: BLE001
    db.rollback()
    print('SYNC_ERR %r' % e, flush=True)
finally:
    db.close()
