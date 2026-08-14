# Reloop 项目长期备忘

## 技术栈与关键约定
- **conda 环境 `reloop`**（Python 3.11, environment.yml）——用户明确不装系统 Python；不要用 venv。
- FastAPI + SQLAlchemy 2.0；唯一数据库 RDS MySQL(reloop 库, 账号 hayden)。
- 环境变量统一 `BRAINX_` 前缀；配置入口 `reloop/config.py`(pydantic-settings)。
- **外部接口只有三类**：TTC 私域人才库(数据源) / 大模型(OpenAI 兼容通用接口) / RDS MySQL。OSS、外部活跃信号、飞书均已移除（用户 2026-08-14 明确要求）。
- 数据隔离键 = 通用 user_id（请求头 X-Owner-User-Id），存为各表 `owner_user_id`；前端接入登录后只改 `reloop/api/deps.py`。
- 目录按模块：`reloop/modules/{sync,profile,scoring,recommend}` + api/db/schemas/utils。
- 评分核心：`modules/scoring/`(factors.py 五因子 + priority.py 加权乘法模型)。权重 .env 的 `BRAINX_SCORE_W_*`。
- 活跃度因子 = TTC 平台 last_active_at + 站内互动记录（牛顿冷却）。
- 无原生向量库：embedding 存 JSON、应用层算余弦；LLM 无 Key 时哈希向量兜底，全流程离线可跑。

## 数据源
- TTC 私域人才库: https://app.ttcadvisory.com/app/private-talent/talents/all-talents/U2034543869059211264
- 页面需飞书登录（实测）。同步双通道：接口拉取(client.py, 需 Token) / 页面导出 JSON 导入(POST /sync/ttc/ingest)。
- 字段映射集中在 `modules/sync/normalizer.py::FIELD_ALIASES`，拿到真实 XHR 后在此补。

## 测试
- `python tests/test_pipeline.py`（SQLite 覆盖 + LLM 离线，无需任何凭据）。

## 待办/已知缺口
- BRAINX_MYSQL_HOST 需填真实 RDS 内/外网地址(.env.example 占位)。
- TTC 真实接口路径(BRAINX_TTC_TALENT_API_PATH)与字段映射待补。
- 后期前端：契约在 schemas/talent.py + api/ 路由，Swagger /docs。
