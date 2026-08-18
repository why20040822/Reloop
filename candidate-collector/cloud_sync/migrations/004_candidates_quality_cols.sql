-- 004_candidates_quality_cols.sql — 质量闸门列（R6）+ 求职意向一级列（R4 收口）。
-- quality_score / missing_fields：入库时由 ingestion/quality.py 四要素打分随行进库。
-- expected_title / opportunity_intent：此前只塞 parsed_json（违反 R4），
-- 提升为一级列，QualityGate 与检索可直接用；存量由 P1 回填（从 parsed_json/raw_text）。

ALTER TABLE cloud_candidates ADD COLUMN quality_score DECIMAL(3,2) NULL COMMENT '四要素质量分 0-1：完整简历+手机号+求职意向+薪资职级' AFTER last_active_at;
ALTER TABLE cloud_candidates ADD COLUMN missing_fields JSON NULL COMMENT '缺失的四要素项，JSON 数组' AFTER quality_score;
ALTER TABLE cloud_candidates ADD COLUMN expected_title VARCHAR(255) NULL COMMENT '期望职位（求职意向）' AFTER missing_fields;
ALTER TABLE cloud_candidates ADD COLUMN opportunity_intent VARCHAR(64) NULL COMMENT '是否看机会/求职意向描述' AFTER expected_title;

CREATE INDEX idx_cloud_candidates_quality ON cloud_candidates(quality_score DESC);
