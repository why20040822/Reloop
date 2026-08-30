"""notes 字段回填: source_payload 里有 dynamic.macro.concern_reason 但 notes 为空的记录,
重新过 normalizer 把 notes 写回(只动 notes 字段, 不调 API/LLM)。"""
import os, sys
os.chdir('/opt/reloop')
sys.path.insert(0, '/opt/reloop')

from reloop.db.engine import SessionLocal
from reloop.db.models import TalentProfile
from reloop.modules.sync.normalizer import normalize_batch

db = SessionLocal()
owners = [r[0] for r in db.query(TalentProfile.owner_user_id).distinct().all()]
grand = 0
for owner in owners:
    rows = db.query(TalentProfile).filter(
        TalentProfile.owner_user_id == owner,
        TalentProfile.source_payload.isnot(None),
    ).all()
    need = [t for t in rows if not (t.notes or '').strip()
            and ((t.source_payload or {}).get('dynamic') or {}).get('macro')]
    if not need:
        continue
    normalized = normalize_batch([t.source_payload for t in need])
    filled = 0
    for t, n in zip(need, normalized):
        notes = (n or {}).get('notes')
        if notes:
            t.notes = notes
            filled += 1
    db.commit()
    grand += filled
    if filled:
        print(f'{owner[:44]:44s} 回填 {filled}/{len(need)}')
print('总回填:', grand)
