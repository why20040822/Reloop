"""人才库路由(按 owner 隔离)。"""

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from reloop.api.deps import get_db, owner_user_id
from reloop.config import settings
from reloop.db.models import (
    FeedbackLog,
    InteractionRecord,
    Recommendation,
    TalentProfile,
)
from reloop.modules.sync.client import TTCFetchError, TTCAuthRequired
from reloop.modules.sync.company_pool import get_company_supplement as _get_company_supplement
from reloop.schemas.talent import CompanySupplementOut, InteractionCreate, TalentOut
from reloop.utils.isolation import assert_owner

router = APIRouter(prefix="/talents", tags=["人才库"])

# slim 列表模式下置空的重量级字段(详情页 /talents/{id} 不受影响)
_SLIM_HEAVY_FIELDS = ("work_history", "projects", "delivery_records",
                      "education_history", "notes", "stability", "resume_text_preview")


@router.get("", response_model=list[TalentOut], summary="列出我的人才库")
def list_talents(
    keyword: str | None = None,
    limit: int | None = None,
    offset: int = 0,
    slim: bool = False,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_user_id),
):
    """列出人才库(按 owner 隔离)。

    分页(向后兼容): 不传 limit -> 返回全部(旧行为, 前端/测试按数组消费);
    传 limit -> 返回 [offset, offset+limit) 切片, 避免大库全量返回超重响应。
    limit 上限 500, 防止一次拉过多。
    slim=true: 列表视图瘦身模式——重量级 JSON 字段(工作经历/项目/教育明细/备注等)
    置空返回, 全量 383 人载荷从 ~3MB 降到 ~300KB(gzip 后更小), 详情仍走 /talents/{id}。
    """
    q = db.query(TalentProfile).filter(TalentProfile.owner_user_id == owner)
    if keyword:
        from sqlalchemy import or_
        q = q.filter(or_(
            TalentProfile.name.contains(keyword),
            TalentProfile.company.contains(keyword),
            TalentProfile.position.contains(keyword),
        ))
    q = q.order_by(TalentProfile.id.desc())

    # 访客模式且池为空时，自动触发一次同步（异步，不阻塞返回）
    if settings.auth_allow_guest and owner == settings.guest_owner_id:
        count = q.count()
        shared_token = settings.ttc_shared_auth_token
        if count == 0 and shared_token:
            try:
                from reloop.modules.sync.client import talent_sync_service
                talent_sync_service.sync_for_user_async(
                    owner,
                    space_id=settings.ttc_talent_space_id,
                    auth_token=shared_token,
                    source="shared",
                )
            except Exception:  # noqa: BLE001
                pass

    if limit is not None:
        limit = max(1, min(int(limit), 500))
        q = q.offset(max(0, int(offset))).limit(limit)
    rows = q.all()
    if slim:
        for r in rows:
            for f in _SLIM_HEAVY_FIELDS:
                setattr(r, f, None)
    return rows


@router.get("/followed/list", summary="获取已关注人才列表")
def list_followed(
    slim: bool = False,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_user_id),
):
    """返回 tags 含 '已关注' 的人才列表。slim=true 同 /talents 瘦身模式。"""
    q = (
        db.query(TalentProfile)
        .filter(TalentProfile.owner_user_id == owner)
        .all()
    )
    followed = [t for t in q if t.tags and "已关注" in t.tags]
    if slim:
        for t in followed:
            for f in _SLIM_HEAVY_FIELDS:
                setattr(t, f, None)
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


@router.get(
    "/{talent_id}/company-supplement",
    response_model=CompanySupplementOut,
    summary="公司人才库补充信息(实时拉共享池, 只读)",
)
def get_company_supplement(
    talent_id: int,
    force: bool = False,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_user_id),
):
    """看 Reloop 人才信息时, 实时拉公司人才库上同人的最新信息(备注/状态等)作为补充。

    - 公司共享池快照带 30 分钟 TTL 缓存; force=true 强制刷新
    - found=false 时 message 说明原因(无映射/池中未找到/凭据问题)
    """
    t = db.get(TalentProfile, talent_id)
    if not t:
        raise HTTPException(404, "人才不存在")
    assert_owner(TalentProfile, t, owner)
    try:
        return _get_company_supplement(t, force=force)
    except TTCAuthRequired:
        return CompanySupplementOut(
            found=False,
            message="公司共享库凭据缺失或已失效，请检查 BRAINX_TTC_SHARED_AUTH_TOKEN 配置",
        )
    except TTCFetchError as exc:
        return CompanySupplementOut(found=False, message=f"公司人才库拉取失败：{exc}")


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
    # BUG-105(2026-08-28): 级联清理关联行, 不再留孤儿数据
    # (interaction_records / feedback_logs / recommendations)
    db.query(InteractionRecord).filter(
        InteractionRecord.owner_user_id == owner,
        InteractionRecord.talent_id == talent_id,
    ).delete(synchronize_session=False)
    db.query(FeedbackLog).filter(
        FeedbackLog.owner_user_id == owner,
        FeedbackLog.talent_id == talent_id,
    ).delete(synchronize_session=False)
    db.query(Recommendation).filter(
        Recommendation.owner_user_id == owner,
        Recommendation.talent_id == talent_id,
    ).delete(synchronize_session=False)
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
