-- Reloop v3 数据库迁移: talent_profiles 新增字段
-- 执行时间: 2026-08-24
-- 说明: 新增 notes / stability / work_history / projects / delivery_records / resume_updated_at 六个字段, 保留 value_score / tendency_score 历史数据

ALTER TABLE talent_profiles ADD COLUMN notes TEXT COMMENT '运营备注/联系记录/求职意向标注' AFTER tendency_score;
ALTER TABLE talent_profiles ADD COLUMN stability JSON COMMENT '稳定性指标(avg_tenure/max_tenure/recent_tenure/company_count)' AFTER notes;
ALTER TABLE talent_profiles ADD COLUMN work_history JSON COMMENT '工作经历列表(company/position/start_date/end_date)' AFTER stability;
ALTER TABLE talent_profiles ADD COLUMN projects JSON COMMENT '项目经验列表(name/industry/scenario/tech_stack)' AFTER work_history;
ALTER TABLE talent_profiles ADD COLUMN delivery_records JSON COMMENT '投递记录列表(position/company/date/status/source)' AFTER projects;
ALTER TABLE talent_profiles ADD COLUMN resume_updated_at DATETIME COMMENT '简历最新更新时间(活跃度核心参考维度)' AFTER delivery_records;
