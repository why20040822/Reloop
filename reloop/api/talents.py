"""人才库路由(按 owner 隔离)。"""

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from reloop.api.deps import get_db, owner_user_id
from reloop.config import settings
from reloop.db.models import InteractionRecord, TalentProfile
from reloop.schemas.talent import InteractionCreate, TalentOut
from reloop.utils.isolation import assert_owner

router = APIRouter(prefix="/talents", tags=["人才库"])


@router.get("", response_model=list[TalentOut], summary="列出我的人才库")
def list_talents(
    keyword: str | None = None,
    limit: int | None = None,
    offset: int = 0,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_user_id),
):
    """列出人才库(按 owner 隔离)。

    分页(向后兼容): 不传 limit -> 返回全部(旧行为, 前端/测试按数组消费);
    传 limit -> 返回 [offset, offset+limit) 切片, 避免大库全量返回超重响应。
    limit 上限 500, 防止一次拉过多。
    """
    q = db.query(TalentProfile).filter(TalentProfile.owner_user_id == owner)
    if keyword:
        q = q.filter(TalentProfile.name.contains(keyword))
    q = q.order_by(TalentProfile.id.desc())

    # 访客模式且池为空时，自动触发一次同步（异步，不阻塞返回）
    if settings.auth_allow_guest and owner == settings.guest_owner_id:
        count = q.count()
        if count == 0:
            try:
                from reloop.modules.sync.client import talent_sync_service
                from reloop.config import settings as _s
                talent_sync_service.sync_for_user_async(
                    owner,
                    space_id=_s.ttc_talent_space_id,
                    auth_token=_s.ttc_talent_auth_token,
                )
            except Exception:  # noqa: BLE001
                pass

    if limit is not None:
        limit = max(1, min(int(limit), 500))
        q = q.offset(max(0, int(offset))).limit(limit)
    return q.all()


@router.get("/followed/list", summary="获取已关注人才列表")
def list_followed(
    db: Session = Depends(get_db),
    owner: str = Depends(owner_user_id),
):
    """返回 tags 含 '已关注' 的人才列表。"""
    q = (
        db.query(TalentProfile)
        .filter(TalentProfile.owner_user_id == owner)
        .all()
    )
    followed = [t for t in q if t.tags and "已关注" in t.tags]
    return followed


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


@router.get("/{talent_id}/interactions", summary="查看人才互动记录")
def list_interactions(
    talent_id: int,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_user_id),
):
    t = db.get(TalentProfile, talent_id)
    if not t:
        raise HTTPException(404, "人才不存在")
    assert_owner(TalentProfile, t, owner)
    rows = (
        db.query(InteractionRecord)
        .filter(
            InteractionRecord.owner_user_id == owner,
            InteractionRecord.talent_id == talent_id,
        )
        .order_by(InteractionRecord.occurred_at.desc())
        .all()
    )
    return [
        {
            "id": r.id,
            "interaction_type": r.interaction_type,
            "count": r.count,
            "summary": r.summary,
            "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
        }
        for r in rows
    ]


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


@router.post("/{talent_id}/follow", summary="关注/取消关注人才")
def toggle_follow(
    talent_id: int,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_user_id),
):
    t = db.get(TalentProfile, talent_id)
    if not t:
        raise HTTPException(404, "人才不存在")
    assert_owner(TalentProfile, t, owner)
    tags = list(t.tags or [])
    if "已关注" in tags:
        tags = [x for x in tags if x != "已关注"]
        followed = False
    else:
        tags.append("已关注")
        followed = True
    t.tags = tags
    db.commit()
    return {"ok": True, "followed": followed}


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
