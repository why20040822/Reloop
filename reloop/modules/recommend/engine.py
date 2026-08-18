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
        """粗筛: 岗位名/JD 分词后 OR 命中 tags/职位/技能/画像文本, 任一命中即入围。

        改进(修复整串子串匹配漏召回): 岗位"商业分析师"时, 职位为"数据产品经理"
        "HR专员"等不同名的相关人才, 只要命中任一关键词(如"分析""数据")即可入围,
        不再因整串不匹配被丢弃。召回更全, 最终排序仍由五因子精算约束。
        """
        talents = (
            db.query(TalentProfile)
            .filter(TalentProfile.owner_user_id == owner)
            .all()
        )
        keywords = self._extract_keywords(pos)
        if not keywords:
            return talents  # 无有效关键词: 全量进精算, 靠五因子排序, 不误杀

        out = []
        for t in talents:
            haystack = " ".join(
                str(x) for x in [
                    t.position or "",
                    t.resume_text or "",
                    " ".join(t.tags or []),
                    " ".join(t.skills or []),
                ]
            )
            tags = t.tags or []
            if any(kw in tags for kw in keywords) or any(kw in haystack for kw in keywords):
                out.append(t)
        # 兜底: 若一个都没召回, 退回全量进精算, 避免空名单
        return out or talents

    @staticmethod
    def _extract_keywords(pos: Position) -> list[str]:
        """从岗位名 + JD 提取召回关键词(去重、过滤过短词)。

        分词: 按空白/常见分隔符切分, 并保留岗位名整体。无第三方分词依赖。
        """
        import re

        raw = f"{pos.position_name or ''} {pos.jd_text or ''}"
        parts = re.split(r"[\s,，、/;；|]+", raw)
        kws: list[str] = []
        if pos.position_name:
            kws.append(pos.position_name.strip())  # 岗位名整体也作为关键词
        for p in parts:
            p = p.strip()
            if len(p) >= 2:  # 过滤单字噪声
                kws.append(p)
        seen, out = set(), []
        for k in kws:
            if k and k not in seen:
                seen.add(k)
                out.append(k)
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
