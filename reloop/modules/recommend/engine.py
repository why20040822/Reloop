"""两阶段推荐引擎: 秒回初筛 + 后台 LLM 精算 + 持久化结果缓存。

流程(每次点一个岗位):
  1. 解析用户设定的当前岗位(positions 表 is_active=1, 岗位名 + JD)
  2. **缓存命中检查**(recommend_runs 表): 同一 (owner + 岗位名 + JD + 池版本)
     且已算完 -> 直接返回最终结果, 秒开、零 LLM 调用。
     ("两次切换同一个岗位, 任务没变不重算"的缓存栈)
  3. 未命中 -> 立即返回**快速初筛结果**(纯本地计算: 关键词粗筛 + 五因子,
     不调 LLM——职位相似度走字面兜底、JD 向量用已存向量、理由用模板),
     同时把完整精算(批量 LLM 职位语义相似度 + 逐人联系理由)丢给后台线程。
  4. 前端轮询 GET /recommend/result: 后台算完返回最终结果, 前端原地更新。
  5. 人才库同步/互动记录变化 -> 池版本号变化 -> 缓存自动失效重算。

精算仍完全复用 v2/v3 算法(factors.py + priority.py + LLM title_similarity),
兼顾速度与准确率: 初筛保证"先看到人", 最终排序由 LLM 语义精算保证。
"""

import datetime as dt
import hashlib
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from sqlalchemy.orm import Session

from reloop.config import settings
from reloop.db.engine import SessionLocal
from reloop.db.models import (
    InteractionRecord,
    Position,
    RecommendRun,
    Recommendation,
    TalentProfile,
)
from reloop.modules.profile.llm import _fallback_embed, llm_service
from reloop.modules.scoring import factors
from reloop.modules.scoring.priority import FactorScores, rank_candidates

logger = logging.getLogger(__name__)

DEFAULT_TOP_SIZES = (3, 10, None)  # None -> 取 .env 的 recommend_top_n

# 后台精算线程池(独立 DB 会话, 结果落 recommend_runs 供轮询)
_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="reloop-reco")
# 防止同 key 并发重复提交
_SUBMIT_LOCK = threading.Lock()
_RUNNING_KEYS: set[str] = set()

# 进程内初筛结果小缓存(60s): 同 key 的"精算中"轮询请求不重复算初筛
_PREVIEW_CACHE_TTL = 60.0
_PREVIEW_CACHE: dict[str, tuple[float, dict]] = {}


def _iso(v) -> Optional[str]:
    """datetime -> ISO 字符串(结果要存 JSON 列/直接回 JSON 响应)。"""
    if v is None:
        return None
    return v.isoformat() if hasattr(v, "isoformat") else v


def _utcnow() -> dt.datetime:
    # UTC naive, 与 models._now 同基准(避免与本地时区差导致 TTL/僵死误判)
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


class RecommendEngine:
    """触达优先级两阶段计算引擎。"""

    # ================= 对外入口 =================

    def compute(
        self,
        db: Session,
        owner_user_id: str,
        position_name: Optional[str] = None,
        top_sizes: tuple = DEFAULT_TOP_SIZES,
        wait: bool = False,
    ) -> dict:
        """为指定用户计算推荐(数据按 owner 隔离)。

        返回结构在旧版 {run_id, position, top3, top10, top_n, ...} 基础上新增:
          phase: "final" | "preview"   最终结果(缓存/精算完成) | 快速初筛
          computing: bool             后台精算是否仍在进行
          cached: bool                是否命中持久缓存(未重算)
        """
        # ---- 1. 当前岗位 ----
        pos = self._resolve_position(db, owner_user_id, position_name)
        if pos is None:
            return {"error": "no_active_position",
                    "message": "请先设定当前岗位(POST /positions)"}

        # ---- 2. 缓存键(岗位名 + JD + 池版本) ----
        pool_version = self._pool_version(db, owner_user_id)
        cache_key = self._cache_key(owner_user_id, pos, pool_version)

        # ---- 3. 命中已算完的缓存 -> 直接返回最终结果 ----
        hit = self._load_final(db, owner_user_id, cache_key)
        if hit is not None:
            result = dict(hit.result or {})
            result.setdefault("run_id", f"cache-{cache_key[:12]}")
            result["phase"] = "final"
            result["cached"] = True
            result["computing"] = False
            logger.info("[recommend] cache hit key=%s pos=%s", cache_key[:12], pos.position_name)
            return result

        # ---- 4. 已在后台精算中 -> 直接返回初筛(60s 内复用上次初筛结果) ----
        if self._is_running(db, owner_user_id, cache_key):
            preview = self._get_preview(db, owner_user_id, pos, pool_version, cache_key)
            preview["computing"] = True
            return preview

        # ---- 5. 无缓存: 创建 run, 提交后台精算, 立即返回初筛 ----
        run = RecommendRun(
            owner_user_id=owner_user_id,
            cache_key=cache_key,
            position_name=pos.position_name,
            jd_text=pos.jd_text,
            status="running",
            pool_version=pool_version,
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        if wait:
            # 同步模式(测试/离线管线): 直接算完返回最终结果
            self._run_full(run.id, owner_user_id, pos.id)
            db.expire_all()
            final = self._load_final(db, owner_user_id, cache_key)
            if final is not None:
                result = dict(final.result or {})
                result["phase"] = "final"
                result["cached"] = False
                result["computing"] = False
                return result
            return {"error": "compute_failed", "message": "精算失败, 请查看服务端日志"}

        with _SUBMIT_LOCK:
            already = cache_key in _RUNNING_KEYS
            if not already:
                _RUNNING_KEYS.add(cache_key)
        if not already:
            _EXECUTOR.submit(self._bg_task, run.id, owner_user_id, pos.id, cache_key)
        else:
            # 极小概率并发: 别的请求刚提交了同 key 任务, 本 run 标记合并由先者负责
            run.status = "failed"
            run.error = "deduplicated: same cache_key already computing"
            db.commit()

        preview = self._get_preview(db, owner_user_id, pos, pool_version, cache_key)
        preview["computing"] = True
        preview["run_id"] = f"run-{run.id}"
        return preview

    def result_of(
        self,
        db: Session,
        owner_user_id: str,
        position_name: Optional[str] = None,
    ) -> dict:
        """查询某岗位的最新计算状态(前端轮询入口)。

        返回 {status: done|running|failed|idle, ...结果字段}。
        """
        pos = self._resolve_position(db, owner_user_id, position_name)
        if pos is None:
            return {"error": "no_active_position",
                    "message": "请先设定当前岗位(POST /positions)"}
        pool_version = self._pool_version(db, owner_user_id)
        cache_key = self._cache_key(owner_user_id, pos, pool_version)

        run = (
            db.query(RecommendRun)
            .filter(
                RecommendRun.owner_user_id == owner_user_id,
                RecommendRun.cache_key == cache_key,
            )
            .order_by(RecommendRun.id.desc())
            .first()
        )
        if run is None:
            return {"status": "idle", "phase": "none", "computing": False,
                    "message": "尚无计算记录, 请先 POST /recommend/compute"}

        if run.status == "done" and run.result:
            result = dict(run.result)
            result.setdefault("run_id", f"cache-{cache_key[:12]}")
            result["status"] = "done"
            result["phase"] = "final"
            result["cached"] = True
            result["computing"] = False
            return result

        if run.status == "running":
            if self._run_is_stale(run):
                run.status = "failed"
                run.error = "stale running task (worker restart?)"
                db.commit()
            else:
                preview = self._get_preview(db, owner_user_id, pos, pool_version, cache_key)
                preview["status"] = "running"
                preview["computing"] = True
                return preview

        return {"status": run.status or "failed", "phase": "none",
                "computing": False, "message": run.error or "计算失败"}

    # ================= 后台精算 =================

    def _bg_task(self, run_id: int, owner_user_id: str, position_id: int, cache_key: str):
        try:
            self._run_full(run_id, owner_user_id, position_id)
        except Exception as e:  # noqa: BLE001
            logger.exception("[recommend] background compute failed run=%s", run_id)
            try:
                db = SessionLocal()
                try:
                    run = db.get(RecommendRun, run_id)
                    if run and run.status == "running":
                        run.status = "failed"
                        run.error = str(e)[:2000]
                        db.commit()
                finally:
                    db.close()
            except Exception:  # noqa: BLE001
                logger.exception("[recommend] mark failed error run=%s", run_id)
        finally:
            with _SUBMIT_LOCK:
                _RUNNING_KEYS.discard(cache_key)

    def _run_full(self, run_id: int, owner_user_id: str, position_id: int):
        """完整精算(独立 DB 会话, 线程安全): 五因子 + LLM 相似度 + 理由 + 落库。"""
        db = SessionLocal()
        try:
            pos = db.get(Position, position_id)
            run = db.get(RecommendRun, run_id)
            if pos is None or run is None:
                logger.warning("[recommend] run=%s missing pos/run", run_id)
                return

            shortlisted = self._shortlist(db, owner_user_id, pos)
            ranked = self._rank(db, owner_user_id, shortlisted, pos, use_llm=True)

            run_id_hex = uuid.uuid4().hex
            items = self._build_items(db, owner_user_id, pos, ranked, run_id_hex)

            result = {
                "run_id": run_id_hex,
                "owner_user_id": owner_user_id,
                "position": pos.position_name,
                "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
                "total_pool": db.query(TalentProfile)
                .filter(TalentProfile.owner_user_id == owner_user_id).count(),
                "shortlisted": len(shortlisted),
                "top_n_setting": settings.recommend_top_n,
            }
            for size in DEFAULT_TOP_SIZES:
                key = "top_n" if size is None else f"top{size}"
                result[key] = items[: size or settings.recommend_top_n]

            run.status = "done"
            run.result = result
            db.commit()
            logger.info("[recommend] full compute done run=%s pos=%s items=%d",
                        run_id, pos.position_name, len(items))
        finally:
            db.close()

    # ================= 快速初筛(无 LLM, 秒回) =================

    def _get_preview(self, db: Session, owner: str, pos: Position,
                     pool_version: str, cache_key: str) -> dict:
        cached = _PREVIEW_CACHE.get(cache_key)
        if cached is not None and (time.time() - cached[0]) < _PREVIEW_CACHE_TTL:
            return cached[1]
        result = self._compute_preview(db, owner, pos)
        _PREVIEW_CACHE[cache_key] = (time.time(), result)
        if len(_PREVIEW_CACHE) > 64:  # 简单防膨胀
            _PREVIEW_CACHE.clear()
        return result

    def _compute_preview(self, db: Session, owner: str, pos: Position) -> dict:
        """纯本地快速初筛: 同一套五因子, 但不调任何 LLM。

        - 职位相似度: 传 None -> match_score_v2 内部降级字面相似度
        - JD 向量: 用设岗时已存的 jd_embedding; 缺失用本地哈希向量
        - 联系理由: 模板文案(最终结果里会被 LLM 精算理由替换)
        """
        shortlisted = self._shortlist(db, owner, pos)
        ranked = self._rank(db, owner, shortlisted, pos, use_llm=False)

        items = []
        top_n = settings.recommend_top_n
        for idx, r in enumerate(ranked[:top_n], start=1):
            t = db.get(TalentProfile, r.talent_id)
            if t is None:
                continue
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
                    "last_active_at": _iso(t.last_active_at),
                    "contact_reason": f"快速初筛: 近期活跃且与{pos.position_name}岗位相关, 精算理由生成中。",
                }
            )
        return {
            "run_id": "preview",
            "owner_user_id": owner,
            "position": pos.position_name,
            "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
            "total_pool": db.query(TalentProfile)
            .filter(TalentProfile.owner_user_id == owner).count(),
            "shortlisted": len(shortlisted),
            "top_n_setting": top_n,
            "phase": "preview",
            "cached": False,
            "top3": items[:3],
            "top10": items[:10],
            "top_n": items[:top_n],
        }

    # ================= 缓存辅助 =================

    @staticmethod
    def _cache_key(owner: str, pos: Position, pool_version: str) -> str:
        raw = "|".join([
            owner,
            (pos.position_name or "").strip(),
            (pos.jd_text or "").strip(),
            pool_version,
        ])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _pool_version(self, db: Session, owner: str) -> str:
        """数据池版本: 人才数量/最新更新时间/近期互动数/最新互动日期。

        任一变化 -> 版本变化 -> 缓存失效 -> 自动重算。
        """
        pool = db.query(TalentProfile).filter(TalentProfile.owner_user_id == owner)
        count = pool.count()
        last_talent = (
            db.query(TalentProfile.updated_at)
            .filter(TalentProfile.owner_user_id == owner)
            .order_by(TalentProfile.updated_at.desc())
            .first()
        )
        since = dt.date.today() - dt.timedelta(days=90)
        inter_q = db.query(InteractionRecord).filter(
            InteractionRecord.owner_user_id == owner,
            InteractionRecord.occurred_at >= since,
        )
        inter_count = inter_q.count()
        last_inter = (
            db.query(InteractionRecord.occurred_at)
            .filter(
                InteractionRecord.owner_user_id == owner,
                InteractionRecord.occurred_at >= since,
            )
            .order_by(InteractionRecord.occurred_at.desc())
            .first()
        )
        return "t{0}:{1}|i{2}:{3}".format(
            count,
            last_talent[0].isoformat() if last_talent and last_talent[0] else "-",
            inter_count,
            last_inter[0].isoformat() if last_inter and last_inter[0] else "-",
        )

    def _load_final(self, db: Session, owner: str, cache_key: str) -> Optional[RecommendRun]:
        """取 TTL 内已算完的缓存 run。"""
        ttl_seconds = settings.recommend_cache_ttl
        since = _utcnow() - dt.timedelta(seconds=ttl_seconds)
        run = (
            db.query(RecommendRun)
            .filter(
                RecommendRun.owner_user_id == owner,
                RecommendRun.cache_key == cache_key,
                RecommendRun.status == "done",
            )
            .order_by(RecommendRun.id.desc())
            .first()
        )
        if run is None or not run.result:
            return None
        if run.created_at and run.created_at < since:
            return None  # 过期: 重新精算
        return run

    def _is_running(self, db: Session, owner: str, cache_key: str) -> bool:
        run = (
            db.query(RecommendRun)
            .filter(
                RecommendRun.owner_user_id == owner,
                RecommendRun.cache_key == cache_key,
                RecommendRun.status == "running",
            )
            .order_by(RecommendRun.id.desc())
            .first()
        )
        if run is None:
            return False
        if self._run_is_stale(run):
            run.status = "failed"
            run.error = "stale running task (worker restart?)"
            db.commit()
            return False
        return True

    @staticmethod
    def _run_is_stale(run: RecommendRun) -> bool:
        updated = run.updated_at or run.created_at
        if not updated:
            return False
        age = (_utcnow() - updated).total_seconds()
        return age > settings.recommend_run_stale_seconds

    # ================= 岗位 / 粗筛 / 精算(原逻辑) =================

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
              talents: list[TalentProfile], pos: Position, use_llm: bool = True):
        """精算: 五因子批量归一化 -> 加权乘法排序。

        v2: 活跃度走分事件半衰期+绝对/相对混合归一化;
            匹配度走结构化多维(职位/技能/年限/学历)+语义余弦融合。
        use_llm=False(快速初筛): 跳过 LLM 职位相似度与 embedding 调用。
        """
        now = dt.datetime.now()
        interactions_by_talent = self._load_interactions(db, owner, talents)

        # 活跃度 v2: 冷却原始分 + 最近事件新近度, 混合归一化
        act_raw: dict[int, float] = {}
        act_latest: dict[int, Optional[float]] = {}
        for t in talents:
            its = interactions_by_talent.get(t.id, [])
            events = factors.build_activity_events(t.last_active_at, its)
            act_raw[t.id] = factors.activity_score(events, now=now)
            act_latest[t.id] = factors.days_since_latest_event(events, now=now)
        act_norm = dict(
            zip(act_raw.keys(), factors.hybrid_activity_normalize(
                list(act_raw.values()), list(act_latest.values())))
        )

        # 历史关系原始分
        rel_raw = {
            t.id: factors.raw_relationship_score(interactions_by_talent.get(t.id, []))
            for t in talents
        }
        rel_norm = dict(
            zip(rel_raw.keys(), factors.min_max_normalize(list(rel_raw.values())))
        )

        # JD 向量(语义维度) + 召回关键词(结构化维度)
        jd_text = pos.jd_text or pos.position_name
        if use_llm:
            jd_emb = pos.jd_embedding or llm_service.embed(jd_text)
        else:
            # 初筛: 已存向量(设岗时算好) > 本地哈希向量, 不调 API
            jd_emb = pos.jd_embedding or _fallback_embed(jd_text)
        jd_kws = self._extract_keywords(pos)

        # LLM 职位语义相似度: 去重后批量推理(带进程内缓存),
        # 解决"AI研发工程师"匹配不到"算法工程师"的字面失灵问题
        title_sim_map: dict[str, float] = {}
        if use_llm and pos.position_name:
            uniq_positions = [p for p in {t.position for t in talents if t.position}]
            title_sim_map = llm_service.title_similarity(
                pos.position_name, uniq_positions)

        candidates = []
        for t in talents:
            match = factors.match_score_v2(
                position_name=pos.position_name,
                jd_text=pos.jd_text,
                jd_keywords=jd_kws,
                talent_position=t.position,
                talent_skills=t.skills or [],
                talent_tags=t.tags or [],
                talent_work_years=t.work_years,
                talent_education=t.education,
                jd_embedding=jd_emb,
                resume_embedding=t.resume_embedding or [],
                title_semantic=(
                    title_sim_map.get(t.position)
                    if t.position in title_sim_map else None
                ),
            )
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
        import concurrent.futures as cf

        items = []
        today = dt.date.today()
        # 性能关键修复: 只对 TopN 生成 LLM 联系理由(原来对全部 ranked 逐个调
        # LLM, 上百人时是 2 分钟等待的主要来源), 并发拉满。
        top_n = settings.recommend_top_n
        ranked_top = ranked[:top_n]
        talents = [db.get(TalentProfile, r.talent_id) for r in ranked_top]
        reasons: list[str] = [""] * len(ranked_top)
        if ranked_top:
            with cf.ThreadPoolExecutor(max_workers=min(8, len(ranked_top))) as ex:
                futs = {
                    ex.submit(
                        llm_service.generate_contact_reason,
                        talent=f"{t.name}({t.position or ''})",
                        position=pos.position_name,
                        jd=pos.jd_text or "",
                    ): i
                    for i, t in enumerate(talents) if t is not None
                }
                for fut in cf.as_completed(futs):
                    reasons[futs[fut]] = fut.result()
        for idx, (r, t, reason) in enumerate(zip(ranked_top, talents, reasons), start=1):
            if t is None:
                continue
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
                    "last_active_at": _iso(t.last_active_at),
                    "contact_reason": reason,
                }
            )
        db.commit()
        return items


recommend_engine = RecommendEngine()
