"""当前招聘岗位路由(设定后实时触发推荐引擎)。"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from reloop.api.deps import get_db, owner_user_id
from reloop.db.models import Position
from reloop.modules.profile.llm import llm_service
from reloop.schemas.talent import PositionCreate, PositionOut

router = APIRouter(prefix="/positions", tags=["岗位设定"])


@router.post("", response_model=PositionOut, summary="设定当前招聘岗位(如: HRBP)")
def set_position(
    body: PositionCreate,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_user_id),
):
    # 幂等: 同名且 JD 未变的生效岗位直接复用(不动 jd_embedding, 稳定缓存键,
    # 避免每次重设岗位都触发全量重算)
    existing = (
        db.query(Position)
        .filter(
            Position.owner_user_id == owner,
            Position.is_active == 1,
            Position.position_name == body.position_name,
        )
        .order_by(Position.created_at.desc())
        .first()
    )
    if existing is not None and (existing.jd_text or "") == (body.jd_text or ""):
        return existing

    # 同名旧岗位(或 JD 已变化的)置为失效
    db.query(Position).filter(
        Position.owner_user_id == owner,
        Position.is_active == 1,
        Position.position_name == body.position_name,
    ).update({Position.is_active: 0})
    emb = llm_service.embed(body.jd_text or body.position_name)
    pos = Position(
        owner_user_id=owner,
        position_name=body.position_name,
        jd_text=body.jd_text,
        jd_embedding=emb,
        is_active=1,
    )
    db.add(pos)
    db.commit()
    db.refresh(pos)
    return pos


@router.get("", response_model=list[PositionOut], summary="列出我的生效岗位")
def list_positions(
    db: Session = Depends(get_db),
    owner: str = Depends(owner_user_id),
):
    return (
        db.query(Position)
        .filter(Position.owner_user_id == owner, Position.is_active == 1)
        .order_by(Position.created_at.desc())
        .all()
    )
