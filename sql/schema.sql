-- Reloop 建表脚本 (RDS MySQL, 生产用; 开发/测试可由 ORM 自动建表)
-- 所有业务表带 owner_user_id = 数据隔离键(每个用户的人才库完全隔离)

CREATE TABLE IF NOT EXISTS users (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    user_id       VARCHAR(64)  NOT NULL UNIQUE,
    display_name  VARCHAR(128) NULL,
    ttc_space_id  VARCHAR(64)  NULL,
    created_at    DATETIME     DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS talent_profiles (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    owner_user_id   VARCHAR(64)  NOT NULL,
    source_id       VARCHAR(64)  NULL COMMENT 'TTC 人才ID',
    name            VARCHAR(128) NOT NULL,
    base_location   VARCHAR(64)  NULL COMMENT 'base地点',
    company         VARCHAR(128) NULL,
    position        VARCHAR(128) NULL,
    work_years      DOUBLE       NULL COMMENT '经验年限(年)',
    education       VARCHAR(64)  NULL,
    skills          JSON         NULL,
    resume_text     TEXT         NULL COMMENT '结构化画像文本',
    resume_embedding JSON        NULL COMMENT '向量, JSON存, 应用层算余弦',
    value_score     DOUBLE       NULL COMMENT '人才价值静态分0~1',
    tendency_score  DOUBLE       NULL COMMENT 'LLM求职倾向0~1',
    last_active_at  DATETIME     NULL COMMENT 'TTC平台最近活跃时间',
    tags            JSON         NULL COMMENT '粗筛标签',
    source_payload  JSON         NULL COMMENT 'TTC原始记录留底',
    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX ix_talent_owner (owner_user_id, id),
    INDEX ix_talent_source (owner_user_id, source_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS positions (
    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
    owner_user_id VARCHAR(64)  NOT NULL,
    position_name VARCHAR(128) NOT NULL COMMENT '当前招聘岗位',
    jd_text       TEXT         NULL,
    jd_embedding  JSON         NULL,
    is_active     TINYINT      DEFAULT 1,
    created_at    DATETIME     DEFAULT CURRENT_TIMESTAMP,
    INDEX ix_position_owner (owner_user_id, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS interaction_records (
    id               BIGINT AUTO_INCREMENT PRIMARY KEY,
    owner_user_id    VARCHAR(64) NOT NULL,
    talent_id        BIGINT      NOT NULL,
    interaction_type VARCHAR(32) NOT NULL COMMENT 'call/message/interview/note',
    count            INT         DEFAULT 1,
    summary          TEXT        NULL,
    occurred_at      DATE        NULL,
    created_at       DATETIME    DEFAULT CURRENT_TIMESTAMP,
    INDEX ix_inter_owner_talent (owner_user_id, talent_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS recommendations (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    owner_user_id   VARCHAR(64)  NOT NULL,
    talent_id       BIGINT       NOT NULL,
    focus_position  VARCHAR(128) NULL,
    run_id          VARCHAR(40)  NULL COMMENT '同一次引擎运行批次',
    rank            INT          DEFAULT 0,
    score           DOUBLE       DEFAULT 0,
    score_breakdown JSON         NULL COMMENT '五因子明细',
    contact_reason  TEXT         NULL,
    recommend_date  DATE         NULL,
    status          VARCHAR(16)  DEFAULT 'pending' COMMENT 'pending/confirmed/rejected',
    created_at      DATETIME     DEFAULT CURRENT_TIMESTAMP,
    INDEX ix_rec_owner_date (owner_user_id, recommend_date),
    INDEX ix_rec_run (owner_user_id, run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS feedback_logs (
    id               BIGINT AUTO_INCREMENT PRIMARY KEY,
    owner_user_id    VARCHAR(64) NOT NULL,
    talent_id        BIGINT      NOT NULL,
    recommendation_id BIGINT     NULL,
    action           VARCHAR(16) NOT NULL COMMENT 'confirm/reject/correct',
    corrected_tag    VARCHAR(128) NULL,
    note             TEXT        NULL,
    created_at       DATETIME    DEFAULT CURRENT_TIMESTAMP,
    INDEX ix_fb_owner (owner_user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
