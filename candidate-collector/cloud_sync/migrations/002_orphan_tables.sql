-- 002_orphan_tables.sql — 历史手工建表补录（R1：结构变更只走 migrations）
-- 由 scripts/gen_migration_002.py 于 2026-08-05 从 live RDS SHOW CREATE TABLE 生成。
-- 生成后禁止手工改库；后续变更一律新增 NNN_*.sql。

-- ---- plugin_users ----
CREATE TABLE IF NOT EXISTS `plugin_users` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `feishu_open_id` varchar(255) DEFAULT NULL,
  `email` varchar(320) DEFAULT NULL,
  `password_hash` varchar(255) DEFAULT NULL,
  `name` varchar(255) NOT NULL,
  `avatar_url` text,
  `approval_status` varchar(32) NOT NULL DEFAULT 'pending',
  `base_record_id` varchar(255) DEFAULT NULL,
  `last_login_at` datetime DEFAULT NULL,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `feishu_open_id` (`feishu_open_id`),
  UNIQUE KEY `idx_plugin_users_email` (`email`),
  KEY `idx_plugin_users_status` (`approval_status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ---- plugin_sessions ----
CREATE TABLE IF NOT EXISTS `plugin_sessions` (
  `id` char(36) NOT NULL,
  `user_id` bigint NOT NULL,
  `device_id` varchar(255) NOT NULL,
  `access_token_hash` char(64) NOT NULL,
  `refresh_token_hash` char(64) NOT NULL,
  `access_expires_at` datetime NOT NULL,
  `refresh_expires_at` datetime NOT NULL,
  `revoked_at` datetime DEFAULT NULL,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `access_token_hash` (`access_token_hash`),
  UNIQUE KEY `refresh_token_hash` (`refresh_token_hash`),
  KEY `idx_plugin_sessions_user` (`user_id`),
  KEY `idx_plugin_sessions_refresh` (`refresh_token_hash`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ---- plugin_activity_events ----
CREATE TABLE IF NOT EXISTS `plugin_activity_events` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `event_key` char(64) NOT NULL,
  `user_id` bigint NOT NULL,
  `candidate_id` bigint DEFAULT NULL,
  `resume_file_id` bigint DEFAULT NULL,
  `platform` varchar(64) NOT NULL,
  `source_candidate_id` varchar(255) DEFAULT NULL,
  `action` varchar(64) NOT NULL,
  `page_session_id` varchar(255) NOT NULL,
  `plugin_version` varchar(32) DEFAULT NULL,
  `metadata_json` json DEFAULT NULL,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `event_key` (`event_key`),
  KEY `idx_plugin_activity_user` (`user_id`,`created_at`),
  KEY `idx_plugin_activity_resume` (`resume_file_id`,`created_at`),
  KEY `idx_plugin_activity_candidate` (`candidate_id`,`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ---- candidate_resume_files ----
CREATE TABLE IF NOT EXISTS `candidate_resume_files` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `candidate_id` bigint DEFAULT NULL,
  `platform` varchar(64) NOT NULL,
  `source_candidate_id` varchar(255) NOT NULL,
  `source_url` text,
  `file_name` varchar(255) NOT NULL,
  `content_type` varchar(128) NOT NULL,
  `file_size` bigint NOT NULL,
  `sha256` char(64) NOT NULL,
  `oss_bucket` varchar(255) NOT NULL,
  `oss_object_key` varchar(1024) NOT NULL,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `first_archived_by_user_id` bigint DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_resume_candidate_sha256` (`platform`,`source_candidate_id`,`sha256`),
  KEY `idx_resume_source_candidate` (`platform`,`source_candidate_id`),
  KEY `idx_resume_candidate_id` (`candidate_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ---- adoption_events ----
CREATE TABLE IF NOT EXISTS `adoption_events` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `recommendation_id` bigint NOT NULL,
  `request_id` varchar(64) NOT NULL,
  `event_type` varchar(16) NOT NULL,
  `actor` varchar(64) DEFAULT '',
  `detail_json` json DEFAULT NULL,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_request` (`request_id`),
  KEY `idx_rec` (`recommendation_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ---- recommendations ----
CREATE TABLE IF NOT EXISTS `recommendations` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `rec_date` date NOT NULL,
  `consultant` varchar(64) NOT NULL DEFAULT '',
  `job_signal_fingerprint` varchar(64) NOT NULL,
  `job_title` varchar(255) DEFAULT '',
  `company` varchar(255) DEFAULT '',
  `signal_type` varchar(32) DEFAULT '',
  `jd_text_snapshot` text,
  `total_score` double NOT NULL,
  `reasons_json` json NOT NULL,
  `trial_candidates_json` json NOT NULL,
  `status` varchar(24) NOT NULL DEFAULT 'pending',
  `ignore_reason` varchar(255) DEFAULT '',
  `weight_version` int NOT NULL DEFAULT '1',
  `sent_at` datetime DEFAULT NULL,
  `send_attempts` int NOT NULL DEFAULT '0',
  `last_send_error` varchar(255) DEFAULT '',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `action` varchar(24) NOT NULL DEFAULT '',
  `confidence_band` varchar(8) NOT NULL DEFAULT '',
  `evidence_coverage` double NOT NULL DEFAULT '0',
  `policy_version` varchar(40) NOT NULL DEFAULT '',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_rec` (`rec_date`,`consultant`,`job_signal_fingerprint`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ---- weight_config ----
CREATE TABLE IF NOT EXISTS `weight_config` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `version` int NOT NULL,
  `weights_json` json NOT NULL,
  `change_source` varchar(16) NOT NULL DEFAULT 'slider',
  `change_note` varchar(255) DEFAULT '',
  `changed_by` varchar(64) DEFAULT '',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_version` (`version`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ---- decision_events ----
CREATE TABLE IF NOT EXISTS `decision_events` (
  `seq` bigint NOT NULL AUTO_INCREMENT,
  `event_id` varchar(40) NOT NULL,
  `consultant_id` varchar(64) NOT NULL,
  `opportunity_id` varchar(64) NOT NULL,
  `decision_id` bigint DEFAULT NULL,
  `event_type` varchar(24) NOT NULL,
  `previous_state` varchar(16) DEFAULT '',
  `next_state` varchar(16) DEFAULT '',
  `actor` varchar(64) NOT NULL,
  `reason_code` varchar(64) DEFAULT '',
  `metadata_json` json NOT NULL,
  `policy_version` varchar(40) DEFAULT '',
  `occurred_at` datetime NOT NULL,
  `recorded_at` datetime NOT NULL,
  `idempotency_key` varchar(80) NOT NULL,
  PRIMARY KEY (`event_id`),
  UNIQUE KEY `uq_seq` (`seq`),
  UNIQUE KEY `uq_idem` (`idempotency_key`),
  KEY `idx_consultant` (`consultant_id`,`opportunity_id`),
  KEY `idx_decision` (`decision_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ---- engagements ----
CREATE TABLE IF NOT EXISTS `engagements` (
  `consultant_id` varchar(64) NOT NULL,
  `opportunity_id` varchar(64) NOT NULL,
  `state` varchar(16) NOT NULL,
  `state_version` int NOT NULL DEFAULT '0',
  `last_event_id` varchar(40) NOT NULL,
  `last_action_at` datetime NOT NULL,
  `expires_at` datetime DEFAULT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`consultant_id`,`opportunity_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ---- outcome_observations ----
CREATE TABLE IF NOT EXISTS `outcome_observations` (
  `outcome_id` varchar(40) NOT NULL,
  `consultant_id` varchar(64) NOT NULL,
  `opportunity_id` varchar(64) NOT NULL,
  `scope` varchar(16) NOT NULL,
  `source` varchar(24) NOT NULL,
  `stage` varchar(24) DEFAULT '',
  `value_json` json NOT NULL,
  `recorded_by` varchar(64) NOT NULL,
  `idempotency_key` varchar(80) NOT NULL,
  `observed_at` datetime NOT NULL,
  `recorded_at` datetime NOT NULL,
  PRIMARY KEY (`outcome_id`),
  UNIQUE KEY `uq_outcome_idem` (`idempotency_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ---- policy_versions ----
CREATE TABLE IF NOT EXISTS `policy_versions` (
  `policy_version` varchar(40) NOT NULL,
  `consultant_id` varchar(64) NOT NULL,
  `kind` varchar(16) NOT NULL,
  `status` varchar(16) NOT NULL,
  `weights_json` json NOT NULL,
  `bounds_json` json NOT NULL,
  `parent_version` varchar(40) DEFAULT '',
  `metadata_json` json DEFAULT NULL,
  `activated_at` datetime DEFAULT NULL,
  `rollback_reason` varchar(255) DEFAULT '',
  `created_at` datetime NOT NULL,
  PRIMARY KEY (`policy_version`),
  KEY `idx_consultant_kind` (`consultant_id`,`kind`,`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ---- sync_runs ----
CREATE TABLE IF NOT EXISTS `sync_runs` (
  `sync_id` varchar(40) NOT NULL,
  `consultant_id` varchar(64) NOT NULL,
  `source` varchar(24) NOT NULL,
  `as_of` datetime NOT NULL,
  `rows_expected` int DEFAULT NULL,
  `rows_read` int NOT NULL,
  `complete` tinyint NOT NULL,
  `errors_json` json NOT NULL,
  `input_hash` varchar(64) NOT NULL,
  `started_at` datetime NOT NULL,
  `completed_at` datetime DEFAULT NULL,
  PRIMARY KEY (`sync_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 反向孤儿表：client.py:168-199 引用但 live 从未建表（插件登录码流程此前必炸）。
-- 列清单依据代码用法：code_hash 查询/更新、user_id 回链、expires_at 比较、used_at 置位。
CREATE TABLE IF NOT EXISTS plugin_login_codes (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    code_hash VARCHAR(128) NOT NULL,
    user_id BIGINT NOT NULL,
    expires_at DATETIME NOT NULL,
    used_at DATETIME NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_plugin_login_codes_code_hash (code_hash),
    KEY idx_plugin_login_codes_user (user_id)
);
