"""人才库路由(按 owner 隔离)。"""

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from reloop.api.deps import get_db, owner_user_id
from reloop.db.models import InteractionRecord, TalentProfile
from reloop.schemas.talent import InteractionCreate, TalentOut
from reloop.utils.isolation import assert_owner

router = APIRouter(prefix="/talents", tags=["人才库"])


@router.get("", response_model=list[TalentOut], summary="列出我的人才库")
def list_talents(
    keyword: str | None = None,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_user_id),
):
    q = db.query(TalentProfile).filter(TalentProfile.owner_user_id == owner)
    if keyword:
        q = q.filter(TalentProfile.name.contains(keyword))
    return q.order_by(TalentProfile.id.desc()).all()


@router.get("/{talent_id}", response_model=TalentOut, summary="人才详情")
def get_talent(
    talent_id: int,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_user_id),
):
    t = db.get(TalentProfile, talent_id)
    if not t:
        raise HTTPException(404, "人才不存在")
    assert_owner(TalentProfile, t, owner)
    return t


@router.delete("/{talent_id}", summary="删除人才")
def delete_talent(
    talent_id: int,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_user_id),
):
    t = db.get(TalentProfile, talent_id)
    if not t:
        raise HTTPException(404, "人才不存在")
    assert_owner(TalentProfile, t, owner)
    db.delete(t)
    db.commit()
    return {"ok": True}


@router.post("/{talent_id}/interaction", summary="记录一次互动(历史关系+活跃信号)")
def add_interaction(
    talent_id: int,
    body: InteractionCreate,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_user_id),
):
    t = db.get(TalentProfile, talent_id)
    if not t:
        raise HTTPException(404, "人才不存在")
    assert_owner(TalentProfile, t, owner)
    occurred = None
    if body.occurred_at:
        try:
            occurred = dt.date.fromisoformat(body.occurred_at)
        except ValueError:
            raise HTTPException(400, "occurred_at 需为 YYYY-MM-DD")
    rec = InteractionRecord(
        owner_user_id=owner,
        talent_id=talent_id,
        interaction_type=body.interaction_type,
        count=body.count,
        summary=body.summary,
        occurred_at=occurred or dt.date.today(),
    )
    db.add(rec)
    db.commit()
    return {"ok": True}
