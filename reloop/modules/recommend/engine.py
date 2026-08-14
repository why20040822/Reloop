"""实时触发推荐引擎: 粗筛 + 精算 -> Top3 / Top10 / TopN。

流程:
  1. 解析用户设定的当前岗位(positions 表 is_active=1)
  2. 粗筛: 标签/职位/画像文本命中岗位关键词的人才
  3. 精算五因子(活跃度/岗位匹配度/人才价值/历史关系/求职可能性), 批量归一化
  4. 加权乘法模型排序 -> 剔除噪声 -> Top3/Top10/TopN
  5. LLM 生成联系理由, 结果落库 recommendations(按 run_id 一批)
  6. 返回结构化结果(该结构即后期前端的直接数据源)
"""

import datetime as dt
import logging
import uuid
from typing import Optional

from sqlalchemy.orm import Session

from reloop.config import settings
from reloop.db.models import InteractionRecord, Position, Recommendation, TalentProfile
from reloop.modules.profile.llm import llm_service
from reloop.modules.scoring import factors
from reloop.modules.scoring.priority import FactorScores, rank_candidates

logger = logging.getLogger(__name__)

DEFAULT_TOP_SIZES = (3, 10, None)  # None -> 取 .env 的 recommend_top_n


class RecommendEngine:
    """触达优先级实时计算引擎。"""

    def compute(
        self,
        db: Session,
        owner_user_id: str,
        position_name: Optional[str] = None,
        top_sizes: tuple = DEFAULT_TOP_SIZES,
    ) -> dict:
        """为指定用户计算推荐(数据按 owner 隔离)。"""
        # ---- 1. 当前岗位 ----
        pos = self._resolve_position(db, owner_user_id, position_name)
        if pos is None:
            return {"error": "no_active_position",
                    "message": "请先设定当前岗位(POST /positions)"}

        # ---- 2. 粗筛 ----
        shortlisted = self._shortlist(db, owner_user_id, pos)

        # ---- 3. 精算五因子 ----
        ranked = self._rank(db, owner_user_id, shortlisted, pos)

        # ---- 4/5. 组装输出 + 理由 + 落库 ----
        run_id = uuid.uuid4().hex
        items = self._build_items(db, owner_user_id, pos, ranked, run_id)

        result = {
            "run_id": run_id,
            "owner_user_id": owner_user_id,
            "position": pos.position_name,
            "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
            "total_pool": db.query(TalentProfile)
            .filter(TalentProfile.owner_user_id == owner_user_id).count(),
            "shortlisted": len(shortlisted),
            "top_n_setting": settings.recommend_top_n,
        }
        for size in top_sizes:
            key = "top_n" if size is None else f"top{size}"
            result[key] = items[: size or settings.recommend_top_n]
        return result

    # ---------------- 内部方法 ----------------
    def _resolve_position(self, db: Session, owner_user_id: str,
                          position_name: Optional[str]) -> Optional[Position]:
        q = db.query(Position).filter(
            Position.owner_user_id == owner_user_id,
            Position.is_active == 1,
        )
        if position_name:
            q = q.filter(Position.position_name == position_name)
        return q.order_by(Position.created_at.desc()).first()

    def _shortlist(self, db: Session, owner: str,
                   pos: Position) -> list[TalentProfile]:
        """粗筛: 标签命中 / 职位名命中 / 画像文本含岗位关键词。"""
        kw = pos.position_name
        talents = (
            db.query(TalentProfile)
            .filter(TalentProfile.owner_user_id == owner)
            .all()
        )
        out = []
        for t in talents:
            tags = t.tags or []
            if (kw in tags) or (t.position and kw in t.position) or (
                t.resume_text and kw in t.resume_text
            ):
                out.append(t)
        return out

    def _rank(self, db: Session, owner: str,
              talents: list[TalentProfile], pos: Position):
        """精算: 五因子批量归一化 -> 加权乘法排序。"""
        now = dt.datetime.now()
        interactions_by_talent = self._load_interactions(db, owner, talents)

        # 活跃度原始分(平台活跃时间 + 站内互动, 牛顿冷却)
        act_raw = {}
        for t in talents:
            its = interactions_by_talent.get(t.id, [])
            events = factors.build_activity_events(t.last_active_at, its)
            act_raw[t.id] = factors.activity_score(events, now=now)
        act_norm = dict(
            zip(act_raw.keys(), factors.min_max_normalize(list(act_raw.values())))
        )

        # 历史关系原始分
        rel_raw = {
            t.id: factors.raw_relationship_score(interactions_by_talent.get(t.id, []))
            for t in talents
        }
        rel_norm = dict(
            zip(rel_raw.keys(), factors.min_max_normalize(list(rel_raw.values())))
        )

        # JD 向量
        jd_text = pos.jd_text or pos.position_name
        jd_emb = pos.jd_embedding or llm_service.embed(jd_text)

        candidates = []
        for t in talents:
            match = factors.match_score(jd_emb, t.resume_embedding or [])
            value = t.value_score if t.value_score is not None else factors.normalize_value(
                factors.raw_value_score()
            )
            fs = FactorScores(
                activity=act_norm.get(t.id, 0.0),
                match=match,
                value=value,
                relationship=rel_norm.get(t.id, 0.0),
                tendency=factors.tendency_score(t.tendency_score),
            )
            candidates.append((t.id, fs))
        return rank_candidates(candidates)

    @staticmethod
    def _load_interactions(db: Session, owner: str,
                           talents: list[TalentProfile]) -> dict[int, list[dict]]:
        """近 90 天互动记录, 按 talent_id 聚合。"""
        since = dt.date.today() - dt.timedelta(days=90)
        rows = (
            db.query(InteractionRecord)
            .filter(
                InteractionRecord.owner_user_id == owner,
                InteractionRecord.talent_id.in_([t.id for t in talents] or [-1]),
                InteractionRecord.occurred_at >= since,
            )
            .all()
        )
        grouped: dict[int, list[dict]] = {}
        for r in rows:
            grouped.setdefault(r.talent_id, []).append(
                {"interaction_type": r.interaction_type,
                 "count": r.count,
                 "occurred_at": r.occurred_at}
            )
        return grouped

    def _build_items(self, db: Session, owner: str, pos: Position,
                     ranked, run_id: str) -> list[dict]:
        items = []
        today = dt.date.today()
        for idx, r in enumerate(ranked, start=1):
            t = db.get(TalentProfile, r.talent_id)
            reason = llm_service.generate_contact_reason(
                talent=f"{t.name}({t.position or ''})",
                position=pos.position_name,
                jd=pos.jd_text or "",
            )
            rec = Recommendation(
                owner_user_id=owner,
                talent_id=r.talent_id,
                focus_position=pos.position_name,
                run_id=run_id,
                rank=idx,
                score=r.score,
                score_breakdown=r.breakdown.as_dict(),
                contact_reason=reason,
                recommend_date=today,
                status="pending",
            )
            db.add(rec)
            items.append(
                {
                    "rank": idx,
                    "talent_id": r.talent_id,
                    "name": t.name,
                    "company": t.company,
                    "position": t.position,
                    "base_location": t.base_location,
                    "work_years": t.work_years,
                    "education": t.education,
                    "score": round(r.score, 4),
                    "score_breakdown": r.breakdown.as_dict(),
                    "last_active_at": t.last_active_at,
                    "contact_reason": reason,
                }
            )
        db.commit()
        return items


recommend_engine = RecommendEngine()
