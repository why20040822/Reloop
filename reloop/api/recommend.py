"""推荐路由: 两阶段触发(秒回初筛/缓存命中) + 结果轮询 + 反馈。

前端交互契约:
  1. 点击岗位 -> POST /recommend/compute?sort_by=activity|match|custom&w_activity=0.5&w_match=0.5
     - 命中缓存(同岗位同JD同数据版本+同排序+同权重) -> {phase: "final", cached: true, top_n: [...]}
     - 未命中 -> {phase: "preview", computing: true, top_n: [...快速初筛...]}
       (精算在后台跑, 页面立即出人)
  2. 收到 preview -> 前端每 2~3s 轮询 GET /recommend/result?position_name=...&sort_by=...&w_activity=...&w_match=...
     - status=done -> {phase: "final", top_n: [...精算结果...]} 原地更新列表
     - status=running -> 继续轮询
  3. 两次切换同一岗位且任务/数据没变 -> 第 1 步直接命中缓存, 秒开不重算。
  4. 排序切换: 切换 sort_by 会重建缓存键, 触发新计算(或命中另一排序的缓存)。
"""

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from reloop.api.deps import get_db, owner_user_id
from reloop.db.models import FeedbackLog, Position, Recommendation, RecommendRun, TalentProfile
from reloop.modules.recommend.engine import recommend_engine
from reloop.schemas.talent import FeedbackCreate

router = APIRouter(prefix="/recommend", tags=["推荐"])


def _require_active_owned_position(db: Session, owner: str, position_id: int) -> None:
    position = db.query(Position).filter(
        Position.id == position_id,
        Position.owner_user_id == owner,
        Position.is_active == 1,
    ).first()
    if position is None:
        raise HTTPException(status_code=404, detail="岗位不存在")


@router.post("/compute", summary="触发推荐(秒回: 缓存命中给最终结果, 否则给快速初筛+后台精算)")
def compute(
    position_name: str | None = Query(default=None, description="岗位名, 留空取当前生效岗位"),
    position_id: int | None = Query(default=None, description="岗位 ID，优先于岗位名"),
    sort_by: str = Query(default="match", description="排序指标: activity | match | custom"),
    w_activity: float | None = Query(default=None, description="自定义排序: 活跃度权重(0~1, 与 w_match 和为 1)"),
    w_match: float | None = Query(default=None, description="自定义排序: 匹配度权重(0~1, 与 w_activity 和为 1)"),
    force: bool = Query(default=False, description="强制重算(忽略缓存)"),
    db: Session = Depends(get_db),
    owner: str = Depends(owner_user_id),
):
    """输出结构: {run_id, position, phase, cached, computing, sort_by, top3, top10, top_n}。

    每个条目含 talent_id/name/score/score_breakdown(activity+match)/contact_reason 等。
    phase=preview 时 top_n 为快速初筛(无 LLM 匹配), 前端应轮询 /recommend/result 更新。
    """
    if position_id is not None:
        _require_active_owned_position(db, owner, position_id)
    return recommend_engine.compute(
        db, owner, position_name, position_id=position_id, sort_by=sort_by,
        w_activity=w_activity, w_match=w_match, force=force,
    )


@router.get("/result", summary="轮询推荐结果(后台精算完成后返回最终结果)")
def result(
    position_name: str | None = Query(default=None, description="岗位名, 留空取当前生效岗位"),
    position_id: int | None = Query(default=None, description="岗位 ID，优先于岗位名"),
    sort_by: str = Query(default="match", description="排序指标: activity | match | custom"),
    w_activity: float | None = Query(default=None, description="自定义排序: 活跃度权重"),
    w_match: float | None = Query(default=None, description="自定义排序: 匹配度权重"),
    db: Session = Depends(get_db),
    owner: str = Depends(owner_user_id),
):
    """返回 {status: done|running|failed|idle, sort_by, ...结果字段}。status=done 时含完整结果。"""
    if position_id is not None:
        _require_active_owned_position(db, owner, position_id)
    return recommend_engine.result_of(
        db, owner, position_name, position_id=position_id, sort_by=sort_by,
        w_activity=w_activity, w_match=w_match,
    )


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
    if body.action in ("confirm", "reject"):
        db.query(Recommendation).filter(
            Recommendation.owner_user_id == owner,
            Recommendation.talent_id == body.talent_id,
            Recommendation.recommend_date == dt.date.today(),
        ).update({Recommendation.status: "confirmed" if body.action == "confirm" else "rejected"})
    if body.action == "correct" and body.corrected_tag:
        t = db.get(TalentProfile, body.talent_id)
        if t and t.owner_user_id == owner:
            tags = t.tags or []
            if body.corrected_tag not in tags:
                tags.append(body.corrected_tag)
                t.tags = tags
    if body.action == "fav":
        t = db.get(TalentProfile, body.talent_id)
        if t and t.owner_user_id == owner:
            tags = t.tags or []
            if "已关注" not in tags:
                tags.append("已关注")
                t.tags = tags
    if body.action == "unfav":
        t = db.get(TalentProfile, body.talent_id)
        if t and t.owner_user_id == owner:
            tags = t.tags or []
            if "已关注" in tags:
                tags = [x for x in tags if x != "已关注"]
                t.tags = tags
    db.commit()
    return {"ok": True}
