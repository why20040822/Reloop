"""推荐路由: 两阶段触发(秒回初筛/缓存命中) + 结果轮询 + 反馈。

前端交互契约:
  1. 点击岗位 -> POST /recommend/compute
     - 命中缓存(同岗位同JD同数据版本) -> {phase: "final", cached: true, top_n: [...]}
     - 未命中 -> {phase: "preview", computing: true, top_n: [...快速初筛...]}
       (精算在后台跑, 页面立即出人)
  2. 收到 preview -> 前端每 2~3s 轮询 GET /recommend/result?position_name=...
     - status=done -> {phase: "final", top_n: [...精算结果...]} 原地更新列表
     - status=running -> 继续轮询
  3. 两次切换同一岗位且任务/数据没变 -> 第 1 步直接命中缓存, 秒开不重算。
"""

import datetime as dt

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from reloop.api.deps import get_db, owner_user_id
from reloop.db.models import FeedbackLog, Recommendation, TalentProfile
from reloop.modules.recommend.engine import recommend_engine
from reloop.schemas.talent import FeedbackCreate

router = APIRouter(prefix="/recommend", tags=["推荐"])


@router.post("/compute", summary="触发推荐(秒回: 缓存命中给最终结果, 否则给快速初筛+后台精算)")
def compute(
    position_name: str | None = Query(default=None, description="岗位名, 留空取当前生效岗位"),
    db: Session = Depends(get_db),
    owner: str = Depends(owner_user_id),
):
    """输出结构: {run_id, position, phase, cached, computing, top3, top10, top_n}。

    每个条目含 talent_id/name/score/score_breakdown(五因子)/contact_reason 等。
    phase=preview 时 top_n 为快速初筛(无 LLM), 前端应轮询 /recommend/result 更新。
    """
    return recommend_engine.compute(db, owner, position_name)


@router.get("/result", summary="轮询推荐结果(后台精算完成后返回最终结果)")
def result(
    position_name: str | None = Query(default=None, description="岗位名, 留空取当前生效岗位"),
    db: Session = Depends(get_db),
    owner: str = Depends(owner_user_id),
):
    """返回 {status: done/running/failed/idle, ...}。status=done 时含完整结果。"""
    return recommend_engine.result_of(db, owner, position_name)


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
