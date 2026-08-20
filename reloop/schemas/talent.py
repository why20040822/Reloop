"""请求/响应 schema (前后端接口契约, 后期前端直接复用)。"""

import datetime as dt
from typing import Optional

from pydantic import BaseModel, Field


# ---------- 用户/人才 ----------
class TalentOut(BaseModel):
    id: int
    source_id: Optional[str] = None
    name: str
    base_location: Optional[str] = None
    company: Optional[str] = None
    position: Optional[str] = None
    work_years: Optional[float] = None
    education: Optional[str] = None
    skills: Optional[list] = None
    value_score: Optional[float] = None
    tendency_score: Optional[float] = None
    last_active_at: Optional[dt.datetime] = None
    tags: Optional[list] = None

    class Config:
        from_attributes = True


class InteractionCreate(BaseModel):
    interaction_type: str = Field(..., description="call/message/interview/note")
    count: int = 1
    summary: Optional[str] = None
    occurred_at: Optional[str] = None


# ---------- 岗位设定 ----------
class PositionCreate(BaseModel):
    position_name: str = Field(..., description="岗位名, 如: HRBP")
    jd_text: Optional[str] = None


class PositionOut(BaseModel):
    id: int
    position_name: str
    jd_text: Optional[str] = None
    is_active: bool

    class Config:
        from_attributes = True


# ---------- 同步 ----------
class SyncIngestBody(BaseModel):
    """从 TTC 页面导出/复制的原始 JSON 直接导入(站点需登录, 开发期最实用)。"""
    talents: list[dict] = Field(..., description="TTC 原始人才记录数组")


# ---------- 推荐 ----------
class RecommendItemOut(BaseModel):
    rank: int
    talent_id: int
    name: str
    company: Optional[str] = None
    position: Optional[str] = None
    base_location: Optional[str] = None
    work_years: Optional[float] = None
    education: Optional[str] = None
    score: float
    score_breakdown: Optional[dict] = None
    last_active_at: Optional[dt.datetime] = None
    contact_reason: Optional[str] = None


class RecommendResultOut(BaseModel):
    """引擎输出(Top3/Top10/TopN 同构)。"""
    run_id: str
    owner_user_id: str
    position: str
    generated_at: str
    total_pool: int
    shortlisted: int
    top3: list[RecommendItemOut] = []
    top10: list[RecommendItemOut] = []
    top_n: list[RecommendItemOut] = []


class FeedbackCreate(BaseModel):
    talent_id: int
    action: str = Field(..., description="confirm/reject/correct")
    corrected_tag: Optional[str] = None
    note: Optional[str] = None
