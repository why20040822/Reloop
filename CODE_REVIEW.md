# Reloop 云端代码审查报告

> 审查范围：后端 `reloop/`（FastAPI）、`server.js`、`sql/schema.sql`、`tests/`、配置文件；前端 `webapp/`（含前后端接口契约核对）。
> 审查方式：静态代码阅读（未实际运行服务器与测试；`.env` 为敏感文件未读取）。
> 日期：2026-08-22

## 一、当前已可用（最新可用性）

- **登录与隔离**：飞书扫码登录全链路（授权 URL → SVG 二维码 → code 换 token → HMAC 会话 token）；所有业务表按 `owner_user_id` 隔离 + 越权 403 拦截，有测试覆盖。
- **数据同步**：TTC 接口分页拉取（100/页）+ 页面导出 JSON 导入双通道，对真实 TTC 嵌套字段有专门归一化映射（`reloop/modules/sync/normalizer.py:154-224`）。
- **画像结构化**：LLM 增强抽取 + 价值分 + 2048 维 embedding + 按 `source_id` upsert；无 LLM key 时全链路降级兜底（哈希向量 / 规则抽取 / 模板理由），离线可跑。
- **五因子推荐引擎**：活跃度（分事件半衰期冷却）/ 岗位匹配 / 人才价值 / 历史关系 / 求职可能，加权乘法模型（权重 0.3/0.4/0.15/0.1/0.05，可 env 调）；两阶段推荐——缓存命中秒回、preview 初筛 + 线程池后台精算 + 池版本号自动失效 + 僵死任务判定（900s）。
- **反馈闭环**：confirm/reject 回写推荐状态，correct 追加人才标签。
- **前端四页**（今日 / 人才库 / 岗位 / 设置）+ 中英 i18n + mock 模式；前后端接口逐一核对，**前端调用的接口后端全部存在且字段匹配**，未发现"调了不存在接口"的情况。
- **测试**：两个端到端测试脚本（SQLite + 离线 LLM），覆盖同步 → 入库 → 隔离 → 设岗 → 两阶段推荐 → 缓存命中 → 反馈 → token 篡改/过期，断言具体。

## 二、业务缺点

### 1. 安全事故级：真实生产凭据已泄露

- `reloop/config.py:51-52` 把 RDS 账号 `hayden` / 密码 `Haydenmia2026` 写死为默认值；`.env.example:10-13` 含真实 RDS 外网地址 + 明文密码，且已推到 GitHub 公开仓库。**密码应立即轮换并清理仓库历史**。
- 会话签名密钥兜底为固定串 `"reloop-dev-secret"`（`config.py:113`）——忘配密钥时任何人可伪造任意用户的 `X-Auth-Token`；token 无吊销机制，退出登录只是清 localStorage，7 天 TTL 内持续有效。
- OAuth 无 state 校验（`feishu.py:84` 写死 `"reloop"`），无 PKCE；CORS 默认 `*`（`config.py:34`）；无任何速率限制。
- `POST /sync/ttc` 任何登录用户可无限触发：全量拉取 + 每人才一次 LLM 调用（368 人约 10 分钟），无幂等锁、无频率限制，**存在 LLM 费用放大风险**。
- README、`webapp/data/provider.js:16`、`_migrate_linda.py:15` 硬编码了真实用户 open_id `ou_ff894386d0ca340dcc2f7bdc53c57a81`。

### 2. 影响业务正确性的 Bug

- **反馈状态刷新即丢**：推荐结果 JSON 不带 `status` 字段（`engine.py:643-657`），点过"去联系"后重进页面命中缓存全部回到 pending，"待确认"计数失真。后端 `Recommendation.status` 已有，只是没序列化进结果。
- **时区混用**：`engine.py:506` 用本地时间 `dt.datetime.now()` 算活跃度衰减，与落库的 UTC 基准差 8 小时（UTC+8 环境下），是确定性偏差；`normalizer.py:93,104` 同样用本地时间。`factors.py` 注释自称"统一 UTC"，但调用方没遵守。
- **反馈接口越权缺口**：confirm/reject 不校验 talent_id 是否属于当前 owner（`recommend.py:126-132` 只有 correct 分支校验），可对他人 talent_id 写入 feedback_logs；且状态回写只匹配 `recommend_date == today`（`recommend.py:123`），对昨日缓存条目的反馈静默不落状态。
- **ingest 无去重**：结构化 upsert 只在 `source_id` 非空时按 (owner, source_id) 去重（`structuring.py:70-80`）；导出 JSON 缺 id 字段时重复导入产生重复人才行。
- **删除人才不级联**：`DELETE /talents/{id}`（`talents.py:58-70`）不清理关联 interaction_records / recommendations，留孤儿行。
- **TTC 拉取静默截断**：fetch 遇非 200 只 `break` 返回已拉的部分页（`client.py:67-70`），调用方无法区分"拉全了"与"拉了一半"。

### 3. 前端"看起来有、实际没有"的功能

- 人才详情页**五因子雷达图是编造的固定值**（`app.js:212`：activity 0.5 / match 0.6 / relationship 0.3 写死），每个候选人显示一模一样的雷达形状——后端没有"单人才实时因子"接口。
- **"修正"按钮是半成品**：点击只发 `{talent_id, action:"correct"}`，没有任何 UI 输入 `corrected_tag`（`app.js:153,171`），后端校准逻辑永远拿不到值。
- feedback 请求无 try/catch，失败时 UI 已先改成"已确认"并扣减计数、不回滚，且产生 unhandled rejection（`app.js:171`）。
- `renderSettings` 里 `api.me()` 任何异常（含网络抖动）都 `clearAuth()` 强制登出（`app.js:268`）。
- 前端 `http()` 把所有非 2xx 压成裸状态码（`provider.js:53`），后端 detail（如"请先设定岗位"）完全丢失。
- preview 态靠中文字符串前缀 `"快速初筛"` 判断（`app.js:138` ↔ `engine.py:315` 模板文案），改文案即破。
- 新用户无岗位时首页 fallback 到硬编码 `"商业分析师"`（`app.js:73`），必然拿到 400。

### 4. 工程与配置漂移

- `environment.yml` 缺 `segno`（`requirements.txt:10` 有，`/auth/feishu/qrcode` 依赖）——按 README 主推的 conda 装环境，二维码接口必 500。
- 测试不显式设 `BRAINX_AUTH_REQUIRE_TOKEN=false`，而代码默认 `True`（`config.py:42`）——能跑过纯属本机 `.env` 恰好关了它，换机器 / 上 CI 全红。
- LLM 厂商三处说法不一：README 写智谱 BigModel、`config.py:61` 默认阿里云 DashScope、`.env.example:23` 填火山方舟。
- TTC `base_url` 默认值与 `.env.example` 注释矛盾（`app.ttcadvisory.com` vs `gateway.ttcadvisory.com`），用默认值拉取必失败。
- README 接口表缺 `/recommend/result`、`/auth/*`、`/talents/{id}/interactions`，鉴权说明仍写 `X-Owner-User-Id`（生产已强制 `X-Auth-Token`），照 README 操作会 401。
- 噪声阈值代码默认 0.1（`config.py:99`）与 `.env.example:47` 的 0.2 不一致；README 称"6 张 ORM 表"实际 7 张；`check_db.py:93-94` 漏检 `recommend_runs`。
- schema.sql 与 ORM 不完全一致：`recommendations.talent_id` 索引缺失、FK 策略不统一、部分列默认值不同。

### 5. 死代码 / 遗留

- `frontend/app/` 空目录（误导性）；`server.js` + `package.json` 仅为离线预览，与后端 StaticFiles 功能重复。
- 后端死代码：`LLMService.analyze_tendency` + `TENDENCY_PROMPT`、`scoped_query`、`match_score`（v1 保留）；users 表 `ttc_space_id/ttc_auth_token/ttc_bound_name` 三列已 DEPRECATED 仍在建表/补列逻辑里维护。
- 前端死代码：i18n `ttc_*` 整套死键、`gaps_list` 文案过时（声称缺的接口已补上）、`api.health()` 无调用方；`index.html` 重复加载 mock.js/provider.js。
- 无调用方的接口：`GET /recommend/latest`（且 N+1）、`DELETE /talents/{id}`。
- `.workbuddy/tmp_*.py` 临时脚本（硬编码 `/opt/reloop`）、根目录 `test_local.db`、被 git 跟踪的测试 db 文件（`.gitignore` 未覆盖 `*.db`）；mock 数据含脏人名 `"周render"`。

### 6. 业务设计层面待决策

- `/sync/ttc` 全局 Token 设计意味着**任何登录用户能把全公司 TTC 人才库拉进自己池子**（`sync.py:18-42`）——注释称是明确决策，但数据治理上需确认。
- 同步是 10 分钟级的同步阻塞 HTTP 请求，无后台化、无进度反馈、无并发锁，失败整批回滚。
- 无 Dockerfile、无 CI、无部署脚本 / gunicorn 配置，部署知识散落在临时脚本里。
- 性能隐患（当前 368 人可接受，上万后需处理）：`_shortlist` 全表扫描后在 Python 过滤（`engine.py:449-472`）、embedding 余弦在应用层逐人计算、`/recommend/latest` N+1、`/talents` 不传 limit 全量返回。

## 三、后续改进点（按优先级）

1. **轮换 RDS 密码**，清掉 `config.py` 和 `.env.example` 里的真实凭据并脱敏 git 历史；`auth_secret` 兜底固定串改为启动即报错。
2. 推荐结果 item 序列化进持久化的 `status`，修复反馈状态刷新即丢（后端字段已有，只差吐出来）。
3. 雷达图接真数据或删除；"修正"按钮补 `corrected_tag` 输入 UI 或摘除；feedback 加错误回滚与 detail 展示。
4. 统一时间基准为 UTC（`engine.py:506`、`engine.py:255`、`normalizer.py:93,104`）。
5. `/sync/ttc` 改后台任务 + 进度查询 + 并发锁 + 触发频率限制。
6. 测试显式设 `BRAINX_AUTH_REQUIRE_TOKEN=false`，补 CI；`environment.yml` 补 segno。
7. feedback 接口补 owner 校验、支持非当天推荐；删除人才做级联；ingest 补去重；TTC 拉取失败显式报错而非静默截断。
8. 清理死代码与过时文档：README 接口表与鉴权说明、i18n `gaps_list` / `ttc_*` 死键、空 `frontend/` 目录、DEPRECATED 列、临时脚本；`.gitignore` 加 `*.db`。
9. OAuth 补 state 校验；CORS 生产收紧；会话 token 加吊销机制。
10. 补 Dockerfile / 部署脚本；人才池规模上万前处理 N+1、全表扫描、应用层向量计算。

---

*未能验证事项：`.env` 实际内容（敏感文件未读），因此"测试在本机是否能过""生产实际开了哪些开关"无法确认；以上结论均为静态阅读得出。*
