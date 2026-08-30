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
    UniqueConstraint,
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
    # TTC user identifier returned by the official profile endpoint (display and audit only).
    ttc_space_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # User-owned TTC token, encrypted at rest and never returned by the API.
    ttc_auth_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # TTC profile display name.
    ttc_bound_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    last_sync_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)
    last_sync_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # 会话版本(R4 2026-08-28): 登出/吊销时自增, 旧 token 立即失效
    session_version: Mapped[int] = mapped_column(Integer, default=0)
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
    # 联系方式 (TTC basic.phone / basic.email, 列表取首个)
    contact_phone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    contact_email: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    # 求职状态 (TTC dynamic.macro.seek_status: 已离职找工作/在职看机会/在职不考虑...)
    seek_status: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # 当前薪资 / 期望薪资 (TTC dynamic.macro.current_salary_raw / expected_salary)
    current_salary: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    expected_salary: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # 目标岗位 (TTC dynamic.macro.target_positions)
    target_positions: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # 联系状态 (运营备注: 未联系/已联系/沟通中/面试/已入职; 初始来自 TTC 备注, 人工可改)
    contact_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    # 经验年限(年, 由 "X年X月经验" 解析)
    work_years: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    education: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    skills: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # 结构化后的画像文本 (供 embedding 与匹配)
    resume_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 画像文本向量 (RDS MySQL 无向量类型, JSON 存, 应用层算余弦)
    resume_embedding: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # 改造②(2026-08-28): 向量来源标记 real(真模型) | hash(离线兜底)
    embedding_source: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    # DEPRECATED(2026-08-24): 不再纳入核心评分, 保留列供历史数据回溯
    value_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # DEPRECATED(2026-08-24): 不再纳入核心评分, 保留列供历史数据回溯
    tendency_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # TTC 平台上该人才最近活跃/更新时间 (活跃度因子来源)
    last_active_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)
    # 人才标签 (HRBP / 投资经理 / 销售...) -> 粗筛 + 收藏
    tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # TTC 原始记录(归一化前的字段全量留底, 便于回溯重算)
    source_payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # 运营备注 / 联系记录 / 求职意向标注 (同步时从 TTC 备注字段提取)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 简历最新更新时间(活跃度核心参考维度, 数据获取成本低且准确性高)
    resume_updated_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)
    # 职业发展稳定性指标 (JSON): {avg_tenure, max_tenure, recent_tenure, company_count}
    stability: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # 工作经历明细 (JSON list, 对齐 TTC work.items 多段):
    #   [{company, company_std, business_line, position, position_std, job_level,
    #     start_date, end_date, tenure_months, duration_months,
    #     description(工作职责长文本), management_scale, has_management,
    #     company_category, business_domain_category, is_internship}]
    work_history: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # 项目经验 (JSON list, 对齐 TTC project.items):
    #   [{name, company, role, industry, business_scenario, tech_stack,
    #     start_date, end_date, description, core_achievement, project_nature,
    #     is_ai_project, has_landing, is_zero_to_one}]
    projects: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # 教育经历明细 (JSON list, 对齐 TTC education.items):
    #   [{school, school_std, major, degree, start_date, end_date,
    #     school_tier, is_full_time, overseas_region, qs_ranking}]
    education_history: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # 投递记录 (JSON list): [{position, company, date, status, source}]
    delivery_records: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now
    )

    __table_args__ = (
        Index("ix_talent_owner", "owner_user_id", "id"),
        Index("ix_talent_source", "owner_user_id", "source_id"),
        # F2(2026-08-28): 同 owner 同 source_id 唯一——数据库层兜底, 从根上
        # 堵死重复导入(此前只有普通索引, 并发同步可双插)。旧库需先跑
        # scripts/dedup_talents.py 清历史重复, 再由 _ensure_indexes() 建索引。
        UniqueConstraint(
            "owner_user_id", "source_id", name="uq_talent_owner_source"
        ),
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
    # 解析后的结构化 JD；原始 jd_text 仍是推荐缓存和匹配的输入。
    jd_analysis: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    jd_analysis_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    jd_embedding: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # 改造②(2026-08-28): 岗位向量来源标记 real | hash
    embedding_source: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
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


# ---------------------------------------------------------------------
# 同步运行记录 (R6 2026-08-28): 进度 + per-owner 幂等锁的跨进程事实源。
# 替代进程内 _SYNC_PROGRESS/_OWNER_SYNC_ACTIVE 的单机局限——
# gunicorn 多 worker 下任意 worker 均可查询进度、识别"已有 running 同步"。
# ---------------------------------------------------------------------
class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    # 幂等键: 同 owner 的活跃 running 行复用其 sync_id
    sync_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # owned | shared | ingest
    source: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    # running / done / failed
    status: Mapped[str] = mapped_column(String(16), default="running")
    total: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    current: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    synced: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    skipped: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    message: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    __table_args__ = (
        Index("ix_sync_owner_status", "owner_user_id", "status"),
        UniqueConstraint("owner_user_id", "sync_id", name="uq_sync_owner_sync"),
    )


# ---------------------------------------------------------------------
# 公司共享池快照 (v2.2 2026-08-30): 撞库查询的持久化存储。
# 替代 v2.1 的进程内 _snapshot(重启即失/多 worker 各存一份)——
# 整表同批替换, 任意进程/重启后立即可读; TTL 由 MAX(fetched_at) 判定。
# 【隔离约定例外】本表全公司共享一份(公共只读数据), 不带 owner_user_id。
# ---------------------------------------------------------------------
class CompanyPoolSnapshot(Base):
    __tablename__ = "company_pool_snapshot"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    # TTC 人才 ID(共享池视角), 撞库连接键; 一人一行唯一约束兜底
    source_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    # 快照轻字段(与 TalentOut 同名: notes/seek_status/contact_status/company/
    # position/current_salary/expected_salary/base_location/skills/
    # last_active_at/resume_updated_at/work_years/education)
    payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # 本行最近从共享池刷新的时间(整表同批刷新, 取 MAX 即快照版本)
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, index=True)
