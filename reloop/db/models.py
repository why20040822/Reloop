"""ORM 模型。

【数据隔离核心】所有业务表均带 owner_user_id(用户唯一标识)。
每个用户从 TTC 人才库同步进来的数据完全隔离, 任何查询都按 owner_user_id 过滤。

表:
  users               用户
  talent_profiles     统一人才画像库 (TTC 同步 + 算法/LLM 结构化后落库)
  positions           用户设定的当前招聘岗位
  interaction_records 站内互动记录 (历史关系 + 活跃度信号来源)
  recommendations     推荐结果缓存 (Top3/Top10/TopN 一次运行的全部条目)
  feedback_logs       用户反馈 (供后期模型调优/前端使用)
"""

import datetime as dt
from typing import Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from reloop.db.engine import Base


def _now() -> dt.datetime:
    # UTC(naive), 避免 datetime.utcnow() 的弃用告警; 与评分层的时间基准一致。
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


# 可移植自增主键: MySQL 用 BIGINT, SQLite 用 INTEGER(否则 SQLite 不自增)
BigIntPK = BigInteger().with_variant(Integer, "sqlite")


# ---------------------------------------------------------------------
# 用户表: owner_user_id 的归属
# ---------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    # 用户唯一标识(隔离键)。开发期由 X-Owner-User-Id 请求头传入;
    # 后期前端接入后可换成登录态/SSO 解析出的用户 ID。
    user_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    # DEPRECATED: TTC 逐用户绑定已于 2026-08 移除, 改服务端全局 Token(BRAINX_TTC_TALENT_AUTH_TOKEN)。
    # 以下三列保留以兼容旧库, 不再写入; 新同步统一由服务端全局 Token 拉取并按 owner 隔离。
    # 该用户在 ttcadvisory 人才库对应的 space_id(已弃用)
    ttc_space_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # 用户绑定的 TTC 网关登录 Token(已弃用, 不再由用户粘贴)
    ttc_auth_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # TTC Token 解析出的身份(展示用, 已弃用)
    ttc_bound_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


# ---------------------------------------------------------------------
# 统一人才画像库 (核心数据载体)
# ---------------------------------------------------------------------
class TalentProfile(Base):
    __tablename__ = "talent_profiles"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    # ===== 数据隔离键 =====
    owner_user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    # TTC 侧的人才 ID
    source_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # base 地点 (如 上海/深圳)
    base_location: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    company: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    position: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    # 经验年限(年, 由 "X年X月经验" 解析)
    work_years: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    education: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    skills: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # 结构化后的画像文本 (供 embedding 与匹配)
    resume_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 画像文本向量 (RDS MySQL 无向量类型, JSON 存, 应用层算余弦)
    resume_embedding: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # 人才价值静态分 (公司等级+学历+稀缺技能, 0~1)
    value_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # LLM 求职倾向分 (0~1, None=未分析)
    tendency_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # TTC 平台上该人才最近活跃/更新时间 (活跃度因子来源)
    last_active_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)
    # 人才标签 (HRBP / 投资经理 / 销售...) -> 粗筛
    tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # TTC 原始记录(归一化前的字段全量留底, 便于回溯重算)
    source_payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now
    )

    __table_args__ = (
        Index("ix_talent_owner", "owner_user_id", "id"),
        Index("ix_talent_source", "owner_user_id", "source_id"),
    )


# ---------------------------------------------------------------------
# 用户设定的当前招聘岗位 (设定后实时触发推荐引擎)
# ---------------------------------------------------------------------
class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    position_name: Mapped[str] = mapped_column(String(128), nullable=False)
    # JD 文本 (可选; 为空则只用岗位名做匹配)
    jd_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    jd_embedding: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Integer, default=1)  # 1=生效
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    __table_args__ = (Index("ix_position_owner", "owner_user_id", "is_active"),)


# ---------------------------------------------------------------------
# 互动记录: 历史关系因子 + 站内活跃信号 (外部活跃信号已移除)
# ---------------------------------------------------------------------
class InteractionRecord(Base):
    """顾问与人才的互动: 通话 / 消息 / 面试 / 备注。"""

    __tablename__ = "interaction_records"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    talent_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("talent_profiles.id"), index=True
    )
    # call / message / interview / note
    interaction_type: Mapped[str] = mapped_column(String(32), nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=1)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[dt.date] = mapped_column(Date, default=dt.date.today)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    __table_args__ = (Index("ix_inter_owner_talent", "owner_user_id", "talent_id"),)


# ---------------------------------------------------------------------
# 推荐结果 (一次引擎运行的 TopN 全量落库, 按 rank 排名)
# ---------------------------------------------------------------------
class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    talent_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("talent_profiles.id"), index=True
    )
    focus_position: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    # 本次运行批次号(同一次 compute 的条目相同)
    run_id: Mapped[Optional[str]] = mapped_column(String(40), index=True, nullable=True)
    rank: Mapped[int] = mapped_column(Integer, default=0)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    # 五因子分值明细 (前端展示雷达图等)
    score_breakdown: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # 联系理由话术
    contact_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    recommend_date: Mapped[dt.date] = mapped_column(Date, default=dt.date.today)
    # pending / confirmed / rejected (前端反馈入口用)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    __table_args__ = (
        Index("ix_rec_owner_date", "owner_user_id", "recommend_date"),
        Index("ix_rec_run", "owner_user_id", "run_id"),
    )


# ---------------------------------------------------------------------
# 推荐运行记录: 持久化结果缓存栈(两阶段计算的核心)。
# 同一 (owner + 岗位 + JD + 池版本) 命中缓存直接返回, 不重算;
# 精算在后台线程跑, 状态/结果落库, 供前端轮询(跨 gunicorn worker 可见)。
# ---------------------------------------------------------------------
class RecommendRun(Base):
    __tablename__ = "recommend_runs"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    # 缓存键: sha256(owner | 岗位名 | JD | 池版本), 岗位/JD/数据任一变化即失效
    cache_key: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    position_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    jd_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # running / done / failed
    status: Mapped[str] = mapped_column(String(16), default="running", index=True)
    # 人才池版本(命中判断留档, 便于排查缓存失效原因)
    pool_version: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    # 最终结果 JSON(top3/top10/top_n 完整结构, done 时非空)
    result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now
    )

    __table_args__ = (
        Index("ix_run_owner_key", "owner_user_id", "cache_key"),
    )


# ---------------------------------------------------------------------
# 用户反馈日志 (供后期模型调优)
# ---------------------------------------------------------------------
class FeedbackLog(Base):
    __tablename__ = "feedback_logs"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    talent_id: Mapped[int] = mapped_column(BigInteger, index=True)
    recommendation_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    # confirm / reject / correct
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    corrected_tag: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
