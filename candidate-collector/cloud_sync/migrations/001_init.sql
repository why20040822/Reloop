-- 001_init.sql — 初始三表（cloud_candidates / memories / job_signals）。
-- 从 cloud_sync/schema.sql 原样落库；schema.sql 此后作废，以 migrations/ 为唯一真相（R1）。
-- 注：003 修复前 live 的 cloud_candidates 曾被手工 DROP 6 列，此文件保留完整定义作基线。

CREATE TABLE IF NOT EXISTS cloud_candidates (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    fingerprint VARCHAR(128) NOT NULL UNIQUE,
    name VARCHAR(255),
    platform VARCHAR(128),
    source_candidate_id VARCHAR(255),
    source_url TEXT,
    source_type VARCHAR(128),
    title VARCHAR(255),
    location VARCHAR(255),
    current_company VARCHAR(255),
    current_role VARCHAR(255),
    phone VARCHAR(64),
    email VARCHAR(255),
    undergraduate_school VARCHAR(255),
    expected_salary VARCHAR(128),
    experiences_json JSON,
    education_json JSON,
    keywords_json JSON,
    raw_text LONGTEXT,
    review_status VARCHAR(32) DEFAULT 'pending',
    attachment_path TEXT,
    attachment_sha256 VARCHAR(128),
    collected_at DATETIME,
    parsed_json JSON,
    first_collected_by_user_id BIGINT NULL,
    activity_score INT NOT NULL DEFAULT 0,
    activity_signals JSON NULL,
    owner VARCHAR(64) DEFAULT NULL,
    visibility ENUM('private','team') NOT NULL DEFAULT 'team',
    starred TINYINT(1) NOT NULL DEFAULT 0,
    last_active_at DATETIME NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS memories (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    project_id VARCHAR(128) NOT NULL,
    source VARCHAR(128) NOT NULL,
    content_type VARCHAR(64) NOT NULL,
    content_text LONGTEXT NOT NULL,
    metadata JSON,
    embedding JSON,
    embedding_model VARCHAR(128),
    embedded_at DATETIME,
    source_record_id VARCHAR(255),
    content_hash VARCHAR(32) GENERATED ALWAYS AS (
        MD5(CONCAT(project_id, ':', source, ':', content_text))
    ) STORED,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_source_record (source, source_record_id),
    UNIQUE KEY uk_content_hash (project_id, source, content_hash)
);

-- R5 岗位信号采集：lark-cli 读飞书群聊/驾驶舱抽岗位活跃信号。
-- 写入方：scripts/job_signals_collect.py（fingerprint 幂等 upsert）。
CREATE TABLE IF NOT EXISTS job_signals (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    fingerprint VARCHAR(64) NOT NULL UNIQUE COMMENT 'md5(source:chat_id:job_title_norm:company_norm)',
    source VARCHAR(32) NOT NULL COMMENT 'group_chat | base | mail',
    source_ref VARCHAR(255) NOT NULL COMMENT 'chat_id 或 chat_id+message_id 等来源定位',
    chat_id VARCHAR(128),
    job_title VARCHAR(255) COMMENT '岗位原文（未识别时为 NULL）',
    company VARCHAR(255),
    keywords_json JSON COMMENT '命中关键词数组',
    signal_type VARCHAR(32) NOT NULL COMMENT 'new|heating|cooling|fake_active|closed|active',
    evidence_json JSON COMMENT '活跃度证据：消息数/实质消息数/时间跨度/提及人数/代表消息ID',
    excerpt TEXT COMMENT '原始摘录（拼接代表消息，截断）',
    first_seen_at DATETIME,
    last_seen_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
