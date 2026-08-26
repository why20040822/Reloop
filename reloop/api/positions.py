"""当前招聘岗位路由(设定后实时触发推荐引擎)。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from reloop.api.deps import get_db, owner_user_id
from reloop.db.models import Position
from reloop.modules.positions.jd_parser import (
    DeepSeekJDParser,
    JDParserError,
    JDParserUnavailable,
)
from reloop.modules.profile.llm import llm_service
from reloop.schemas.jd import JDAnalysis, JDParseRequest
from reloop.schemas.talent import PositionCreate, PositionOut

router = APIRouter(prefix="/positions", tags=["岗位设定"])


@router.post("/parse-jd", response_model=JDAnalysis, summary="解析 JD（不保存岗位）")
def parse_jd(
    body: JDParseRequest,
    owner: str = Depends(owner_user_id),
):
    """Preview a structured JD; persistence remains the explicit POST /positions action."""
    del owner  # Enforce the same authenticated boundary as position persistence.
    try:
        return DeepSeekJDParser().parse(body.jd_text)
    except JDParserUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except JDParserError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("", response_model=PositionOut, summary="设定当前招聘岗位(如: HRBP)")
def set_position(
    body: PositionCreate,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_user_id),
):
    analysis_data = body.jd_analysis.model_dump(mode="json") if body.jd_analysis else None
    active_count = (
        db.query(Position)
        .filter(Position.owner_user_id == owner, Position.is_active == 1)
        .count()
    )
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
    if (
        existing is not None
        and (existing.jd_text or "") == (body.jd_text or "")
        and existing.jd_analysis == analysis_data
    ):
        return existing

    if existing is None and active_count >= 10:
        raise HTTPException(400, "最多同时生效 10 个岗位，请先停用旧岗位")

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
        jd_analysis=analysis_data,
        jd_analysis_version="deepseek-v1" if analysis_data else None,
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


@router.delete("/{position_id}", summary="删除/停用岗位")
def delete_position(
    position_id: int,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_user_id),
):
    pos = db.get(Position, position_id)
    if not pos or pos.owner_user_id != owner:
        raise HTTPException(404, "岗位不存在")
    db.delete(pos)
    db.commit()
    return {"ok": True}
