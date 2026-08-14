"""Cloud-backed candidate reads and LLM JD matching (demo).

Cloud is the source of truth: when RDS is configured these handlers serve
``reloop.cloud_candidates``; without configuration they fall back to the
legacy local SQLite handlers so a developer machine still works.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from reloop.api import legacy
from reloop.domain.jd_match import llm_available, rank_candidates
from reloop.sinks.rds.client import (
    RdsConfigurationError,
    fetch_match_pool,
    get_candidate_by_id,
    list_candidates,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class JdMatchRequest(BaseModel):
    jd_text: str = Field(min_length=5, max_length=20000)
    limit: int = Field(default=5, ge=1, le=20)
    pool_size: int = Field(default=100, ge=1, le=500)
    llm_pool_size: int = Field(default=20, ge=1, le=50)


@router.get("/api/candidates")
def candidates(
    q: str = Query(default="", max_length=100),
    limit: int = Query(default=500, ge=1, le=500),
) -> list[dict]:
    try:
        return list_candidates(q=q, limit=limit)
    except RdsConfigurationError:
        logger.info("RDS not configured; falling back to local candidates")
        return legacy.candidates(q)


@router.get("/api/candidates/{candidate_id}")
def candidate_detail(candidate_id: int) -> dict:
    try:
        row = get_candidate_by_id(candidate_id)
    except RdsConfigurationError:
        logger.info("RDS not configured; falling back to local candidate detail")
        return legacy.candidate_detail(candidate_id)
    if row is None:
        raise HTTPException(404, "候选人不存在")
    return row


@router.post("/api/jd-match")
def jd_match(payload: JdMatchRequest) -> dict:
    """Demo 入口：JD 文本 → 云端粗筛 → 大模型精算 → Top N（5 因子占位）。

    LLM 未配置时自动降级为关键词粗排并在 mode 中如实标记。
    """

    mode = "llm" if llm_available() else "keyword_fallback"
    try:
        pool = fetch_match_pool(payload.pool_size)
    except RdsConfigurationError as exc:
        raise HTTPException(502, f"云端人才库未配置：{exc}") from exc
    results = rank_candidates(
        payload.jd_text,
        pool,
        limit=payload.limit,
        llm_pool_size=payload.llm_pool_size,
    )
    return {
        "ok": True,
        "mode": mode,
        "pool_size": len(pool),
        "scored": len(results),
        "results": [
            {
                "candidate_id": r.candidate_id,
                "name": r.name,
                "score": r.score,
                "match_score": r.match_score,
                "reason": r.reason,
                "factors": r.factors,
                "mode": r.mode,
            }
            for r in results
        ],
    }
