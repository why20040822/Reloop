"""当前招聘岗位路由(设定后实时触发推荐引擎)。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from reloop.api.deps import get_db, owner_user_id, require_authenticated_non_guest_user
from reloop.db.models import Position, User
from reloop.modules.positions.jd_parser import (
    DeepSeekJDParser,
    JDParserError,
    JDParserUnavailable,
)
from reloop.modules.profile.llm import llm_service
from reloop.schemas.jd import JDParseRequest, JDParseResponse
from reloop.schemas.talent import PositionCreate, PositionOut

router = APIRouter(prefix="/positions", tags=["岗位设定"])


def _active_identity_query(
    db: Session,
    *,
    owner: str,
    position_name: str,
    company_name: str | None,
):
    query = db.query(Position).filter(
        Position.owner_user_id == owner,
        Position.is_active == 1,
        func.trim(Position.position_name) == position_name,
    )
    if company_name is None:
        return query.filter(
            or_(Position.company_name.is_(None), func.trim(Position.company_name) == "")
        )
    return query.filter(func.trim(Position.company_name) == company_name)


@router.post("/parse-jd", response_model=JDParseResponse, summary="解析 JD（不保存岗位）")
def parse_jd(
    body: JDParseRequest,
    user: User = Depends(require_authenticated_non_guest_user),
):
    """Preview a structured JD; persistence remains the explicit POST /positions action."""
    del user  # Enforce a strict authenticated boundary without a write side effect.
    try:
        parser = DeepSeekJDParser()
        return parser.parse(body.jd_text, image_data_urls=body.images)
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
    position_name = body.jd_analysis.title if body.jd_analysis else body.position_name
    analysis_data = body.jd_analysis.model_dump(mode="json") if body.jd_analysis else None
    if analysis_data is not None:
        # 用户提交的公司身份优先于解析预览，避免解析结果意外改变岗位身份。
        analysis_data["company_name"] = body.company_name
    active_count = (
        db.query(Position)
        .filter(Position.owner_user_id == owner, Position.is_active == 1)
        .count()
    )
    replacement = None
    if body.replacement_position_id is not None:
        replacement = (
            db.query(Position)
            .filter(
                Position.id == body.replacement_position_id,
                Position.owner_user_id == owner,
                Position.is_active == 1,
            )
            .first()
        )
        if replacement is None:
            raise HTTPException(404, "被替换岗位不存在或已停用")

    identity_query = _active_identity_query(
        db,
        owner=owner,
        position_name=position_name,
        company_name=body.company_name,
    )
    existing = (
        identity_query
        .order_by(Position.created_at.desc())
        .first()
    )
    if (
        existing is not None
        and (existing.jd_text or "") == (body.jd_text or "")
        and existing.jd_analysis == analysis_data
    ):
        if replacement is not None and replacement.id != existing.id:
            replacement.is_active = 0
            db.commit()
        return existing

    if existing is None and replacement is None and active_count >= 10:
        raise HTTPException(400, "最多同时生效 10 个岗位，请先停用旧岗位")

    emb = llm_service.embed(body.jd_text or position_name)
    identity_query.update({Position.is_active: 0}, synchronize_session=False)
    if replacement is not None:
        replacement.is_active = 0
    pos = Position(
        owner_user_id=owner,
        position_name=position_name,
        company_name=body.company_name,
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
