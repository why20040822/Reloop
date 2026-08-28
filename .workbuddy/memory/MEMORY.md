# Reloop 项目长期备忘

## 技术栈与约定
- conda 环境 `reloop`(Py3.11)；FastAPI + SQLAlchemy 2.0；唯一 DB = RDS MySQL `reloop_app`(账号 hayden)。
- 环境变量 `BRAINX_` 前缀；配置 `reloop/config.py`(pydantic-settings)，启动 `validate_security()` 自检（缺密钥/缺 DB 凭据直接报错）。
- 外部接口仅三类：TTC 人才库 / LLM(OpenAI 兼容) / RDS。隔离键 `owner_user_id`，生产强制 `X-Auth-Token`(HMAC 会话)，`X-Owner-User-Id` 仅开发 fallback。
- 目录：`reloop/modules/{sync,profile,scoring,recommend,positions,auth}` + api/db/schemas/utils。
- **不推 GitHub**（用户明确）：本地 commit 照常，推送用户手动。
- LLM：指定智谱 BigModel(open.bigmodel.cn/api/paas/v4, glm-4-flash + embedding-3)；本地 .env 的 stepfun 配置实际不可用(chat 404/embedding 400)，全靠熔断+降级跑。LLM 熔断：连续 3 次失败进程内自动离线(`modules/profile/llm.py`)，gunicorn 多 worker 各自独立熔断。无向量库：embedding 存 JSON、应用层算余弦。
- 两阶段推荐：`recommend_runs` 持久缓存(sha256 owner|岗位|JD|池版本)；未命中先本地初筛，LLM 后台精算，前端轮询 `/recommend/result`。`DEFAULT_TOP_SIZES=(3,10,None)`。
- TTC 同步用服务端全局 Token(`BRAINX_TTC_TALENT_*`)；users.ttc_* 列 DEPRECATED。TTC 真实字段路径：`work.items[]` / `project.items[]` / `skill.ai_ability` / `dynamic.macro.concern_reason`。models 新增 8 列经 `engine._ensure_columns()` 自动 ALTER(MySQL+SQLite 兼容)。

## 云端部署（ECS 47.110.93.137, cn-hangzhou, 实例 i-bp1dgg3rzmehc33fwpsn, PrePaid 到期会锁停）
- 链路：nginx(:80→301 HTTPS；:443 reloop.yorkteam.cn，LE 证书 acme.sh DNS-01，域名未备案 HTTP-01 不可用) → **uvicorn 127.0.0.1:8000 --workers 1**（systemd `reloop.service`，2026-08-28 SSH 实证；旧记录的 gunicorn 4 workers 已过时）。**单 worker 是 auto_login 会话/同步进度/幂等锁的正确性前提，扩 worker 前必须先做 R6 sync_runs 落库**。管理：`systemctl restart reloop`。
- 代码 `/opt/reloop`，venv `/opt/reloop/.venv`(Py3.11) 别动；**服务器 .env 含真实凭据勿覆盖**（自动备份 .env.bak.*）。SSH：`ssh -i ~/.ssh/id_ed25519 root@47.110.93.137`。
- 同步流程：tar 打包(排除 .git/.env/.workbuddy/venv/__pycache__/tests/*.db) + scp **同一条命令完成**(/tmp 跨回合清空) → 解压删 .env → 备份后 cp -rf 进 /opt/reloop → chown → venv pip install → restart → 验证 /health。
- 服务器独立脚本两坑：必须先 `os.chdir('/opt/reloop')` 否则 .env 读不到；`sync_for_user(db=...)` 需自己 `db.commit()` 否则回滚。
- 本地连 RDS 需把本机公网 IP 加白名单。

## 前端与测试
- `frontend/`(React+TS, vite) 是源码；`npm run build` 输出到 `webapp/`（构建产物，入库）；`webapp.before-*` 是死拷贝可删；server.js 仅离线预览。
- 测试：`pytest tests/`（37 个）+ `node --test tests/*.test.mjs`（28 个），SQLite+离线 LLM 无需凭据。本地跑测试用 managed venv `/Users/ashley/.workbuddy/binaries/python/envs/default`（已装 pytest），需 `BRAINX_DATABASE_URL`(sqlite) + `BRAINX_LLM_API_KEY=""` + `BRAINX_AUTH_REQUIRE_TOKEN=false`。

## 2026-08-28 架构审核（报告 docs/2026-08-28-architecture-review.md）
- main=58bf1ce（origin/main 781663e + 本地 perf gzip/slim 提交，已按云端为主 fast-forward 合并）。65 测试全绿。
- 已验证修复：BUG-001(代码层)/BUG-002/BUG-102 时区/BUG-106 TTC截断/BUG-305 README。
- 仍开放 P1：BUG-101 反馈状态不回序列化(`_build_items` 无 status)；BUG-103 feedback 只匹配当天 recommend_date；BUG-105 delete 不级联；BUG-003 token 无吊销；BUG-004 OAuth state="reloop"；BUG-005 CORS 默认*；BUG-006 sync 无限流。
- 5→50 瓶颈=同步链路（阻塞 HTTP/全量重拉/逐人 LLM 无批量）；性能债：_shortlist 全表扫、list_followed 全表+tags 过滤、/recommend/latest N+1、/talents 默认全量(slim+gzip 是缓解)。
- 工程卫生：.gitignore 缺 *.db(test_local.db 入库)、environment.yml 缺 segno、check_db.py 漏 recommend_runs、死代码(analyze_tendency/scoped_query/v1 match_score/DEPRECATED 权重+ttc_*列/i18n 死键)、schema.sql 与 ORM 漂移、无 Dockerfile/CI。
- 已修复(2026-08-25)：`/followed/list` 路由必须在 `/{talent_id}` 前；feedback fav/unfav 统一"已关注"标签。

## 其他
- git 仓库曾损坏("bad object HEAD")，改公开 remote URL `https://github.com/why20040822/Reloop.git` 后 fetch 恢复。
- 本地/服务器 .env LLM 配置不一致，建议用户统一厂商。

## LLM 厂商现状（2026-08-28）
- **JD 解析 = stepfun Plus Plan**：base `https://api.stepfun.com/step_plan/v1`，模型 `step-3.7-flash`（备选 step-router-v1），json_object 兼容，有效期 **2026-11-22**（到期需续费）。本地 .env 已配 BRAINX_DEEPSEEK_*；服务器 .env 待用户同步。
- step_plan **无 embedding 模型** → 画像 embedding 保持智谱 BigModel 或离线降级，勿切 stepfun。

## 数据正确性两大已知病灶（2026-08-28 实锤，方案 docs/plans/2026-08-28-gap-audit-and-refactor-plan.md）
- **导入重复**：normalizer 缺 id 时 source_id="" → sync 跳过查重 → 无条件 INSERT；且 (owner,source_id) 无唯一约束、/sync/ttc 无 per-owner 锁。修复 F1 指纹兜底/F2 唯一约束/F3 幂等锁/F4 IntegrityError 兜底。
- **全员活跃**：TTC last_updated_at 是记录更新时间非候选人活跃 + created_at 兜底 + 批内 min-max 相对归一化(0.6 权重)必造高分 + 180 天窗口过宽 + 无门禁。修复：去兜底、删相对项、纯绝对衰减、>90 天判不活跃。
