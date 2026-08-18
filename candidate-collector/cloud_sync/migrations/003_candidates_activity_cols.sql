-- 003_candidates_activity_cols.sql — 补回 2026-08-03 后被手工 DROP 的 6 列。
-- 背景：8/3 14 点 274 行写入成功 → 6 列当时在；之后被无记录手工 DROP → 全写入 1054 报错被吞。
-- 列定义与 001_init.sql 基线及 client.py upsert SQL 严格一致。
-- MySQL 无 ADD COLUMN IF NOT EXISTS；重复执行时的 "Duplicate column" 错误由 migrate.py 容忍。

ALTER TABLE cloud_candidates ADD COLUMN activity_score INT NOT NULL DEFAULT 0 AFTER first_collected_by_user_id;
ALTER TABLE cloud_candidates ADD COLUMN activity_signals JSON NULL AFTER activity_score;
ALTER TABLE cloud_candidates ADD COLUMN owner VARCHAR(64) DEFAULT NULL AFTER activity_signals;
ALTER TABLE cloud_candidates ADD COLUMN visibility ENUM('private','team') NOT NULL DEFAULT 'team' AFTER owner;
ALTER TABLE cloud_candidates ADD COLUMN starred TINYINT(1) NOT NULL DEFAULT 0 AFTER visibility;
ALTER TABLE cloud_candidates ADD COLUMN last_active_at DATETIME NULL AFTER starred;

CREATE INDEX idx_cloud_candidates_activity ON cloud_candidates(activity_score DESC, last_active_at DESC);
CREATE INDEX idx_cloud_candidates_owner_visibility ON cloud_candidates(owner, visibility);
