"""推荐路由: 实时触发引擎 + 结果查询 + 反馈(后期前端的三个入口)。"""

import datetime as dt

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from reloop.api.deps import get_db, owner_user_id
from reloop.db.models import FeedbackLog, Recommendation, TalentProfile
from reloop.modules.recommend.engine import recommend_engine
from reloop.schemas.talent import FeedbackCreate

router = APIRouter(prefix="/recommend", tags=["推荐"])


@router.post("/compute", summary="触发触达优先级实时计算(Top3/Top10/TopN)")
def compute(
    position_name: str | None = None,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_user_id),
):
    """输出结构: {run_id, position, top3: [...], top10: [...], top_n: [...]}。

    每个条目含 talent_id/name/score/score_breakdown(五因子)/contact_reason 等,
    即后期前端推荐列表页的直接数据源。
    """
    return recommend_engine.compute(db, owner, position_name)


@router.get("/latest", summary="查看最近一次运行的推荐结果")
def latest(
    limit: int = 10,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_user_id),
):
    latest_run = (
        db.query(Recommendation)
        .filter(Recommendation.owner_user_id == owner)
        .order_by(Recommendation.id.desc())
        .first()
    )
    if not latest_run:
        return {"run_id": None, "items": []}
    rows = (
        db.query(Recommendation)
        .filter(
            Recommendation.owner_user_id == owner,
            Recommendation.run_id == latest_run.run_id,
        )
        .order_by(Recommendation.rank.asc())
        .limit(limit)
        .all()
    )
    items = []
    for r in rows:
        t = db.get(TalentProfile, r.talent_id)
        items.append(
            {
                "rank": r.rank,
                "talent_id": r.talent_id,
                "name": t.name if t else None,
                "company": t.company if t else None,
                "position": t.position if t else None,
                "base_location": t.base_location if t else None,
                "score": r.score,
                "score_breakdown": r.score_breakdown,
                "contact_reason": r.contact_reason,
                "status": r.status,
            }
        )
    return {"run_id": latest_run.run_id, "position": latest_run.focus_position,
            "items": items}


@router.post("/feedback", summary="用户反馈(确认/拒绝/修正, 供模型调优)")
def feedback(
    body: FeedbackCreate,
    db: Session = Depends(get_db),
    owner: str = Depends(owner_user_id),
):
    log = FeedbackLog(
        owner_user_id=owner,
        talent_id=body.talent_id,
        action=body.action,
        corrected_tag=body.corrected_tag,
        note=body.note,
    )
    db.add(log)
    # 反馈同步更新推荐条目状态
    if body.action in ("confirm", "reject"):
        db.query(Recommendation).filter(
            Recommendation.owner_user_id == owner,
            Recommendation.talent_id == body.talent_id,
            Recommendation.recommend_date == dt.date.today(),
        ).update({Recommendation.status: "confirmed" if body.action == "confirm" else "rejected"})
    # 若修正标签, 更新人才 tags
    if body.action == "correct" and body.corrected_tag:
        t = db.get(TalentProfile, body.talent_id)
        if t and t.owner_user_id == owner:
            tags = t.tags or []
            if body.corrected_tag not in tags:
                tags.append(body.corrected_tag)
                t.tags = tags
    db.commit()
    return {"ok": True}
