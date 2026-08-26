# Reloop 云端 Bug 清单

> 来源：CODE_REVIEW.md（2026-08-22 静态代码审查）
> 状态标记：⬜ 未修复 | 🔧 修复中 | ✅ 已修复 | ⚠️ 需人工操作

## P0 — 安全事故级

### BUG-001 ✅(代码) RDS 生产凭据硬编码并已泄露
- **位置**：`reloop/config.py:51-52`（默认值写死）、`.env.example:10-13`（真实外网地址 + 明文密码）、README.md:36
- **问题**：RDS 账号密码写死为代码默认值，且真实凭据已推送到 GitHub 公开仓库
- **影响**：任何人可直连生产数据库，拖库/删库
- **修复**：
  1. ⚠️ **待人工**：立即在 RDS 控制台轮换 `hayden` 账号密码，并同步更新本机/服务器 `.env`
  2. ✅ config.py 删除硬编码默认值，缺凭据启动即报错（`validate_security()`）
  3. ✅ .env.example / README 脱敏为占位符
  4. ⚠️ **待人工**：脱敏 git 历史（git filter-repo / BFG，需 force push，确认后执行）

### BUG-002 ✅ 会话签名密钥兜底为固定串
- **位置**：`reloop/config.py:113`
- **问题**：`auth_secret` 未配置时兜底为 `"reloop-dev-secret"`，任何人可伪造任意用户的 `X-Auth-Token`
- **影响**：生产忘配密钥 = 鉴权完全失效
- **修复**：✅ `auth_require_token=True`（生产）且无显式密钥/飞书密钥时启动即报错（main.py lifespan 调 `validate_security()`）；仅开发降级模式保留兜底串

### BUG-003 ⚠️ Token 无吊销机制
- **位置**：会话 token 签发/校验逻辑
- **问题**：退出登录只清 localStorage，7 天 TTL 内 token 持续有效
- **修复**：P3 阶段加吊销机制（token 黑名单 / 版本号）

### BUG-004 ⬜ OAuth 无 state 校验、无 PKCE
- **位置**：`reloop/api/feishu.py:84`（state 写死 `"reloop"`）
- **影响**：CSRF 攻击面
- **修复**：P3

### BUG-005 ⬜ CORS 默认 `*`，无速率限制
- **位置**：`reloop/config.py:34`
- **修复**：P3 生产收紧

### BUG-006 ⬜ POST /sync/ttc 无限制，LLM 费用放大
- **位置**：`reloop/api/sync.py`
- **问题**：任何登录用户可无限触发全量拉取 + 每人才一次 LLM 调用（368 人约 10 分钟），无幂等锁、无频率限制
- **修复**：P2 任务 5（后台任务 + 并发锁 + 频率限制）

### BUG-007 ⬜ 硬编码真实用户 open_id
- **位置**：`webapp/data/provider.js:16`、`_migrate_linda.py:15`、README
- **问题**：`ou_ff894386d0ca340dcc2f7bdc53c57a81` 泄露在代码库
- **修复**：P3 清理

## P1 — 影响业务正确性

### BUG-101 ⬜ 反馈状态刷新即丢
- **位置**：`reloop/engine.py:643-657`
- **问题**：推荐结果 JSON 不带 `status` 字段，点过"去联系"后重进页面命中缓存全部回到 pending，"待确认"计数失真
- **根因**：`Recommendation.status` 已有持久化，只是没序列化进结果
- **修复**：item 序列化补 `status` 字段

### BUG-102 ⬜ 时区混用，活跃度衰减确定性偏差
- **位置**：`reloop/engine.py:506`、`engine.py:255`、`reloop/modules/sync/normalizer.py:93,104`
- **问题**：用本地时间 `dt.datetime.now()` 算衰减，与落库 UTC 基准差 8 小时（UTC+8 环境）
- **修复**：统一 UTC（`datetime.now(timezone.utc)`）

### BUG-103 ⬜ 反馈接口越权缺口
- **位置**：`reloop/api/recommend.py:126-132`
- **问题**：confirm/reject 不校验 talent_id 是否属于当前 owner（仅 correct 分支校验），可对他人 talent_id 写 feedback_logs；状态回写只匹配 `recommend_date == today`，昨日缓存条目反馈静默丢失
- **修复**：P2 任务 7

### BUG-104 ⬜ ingest 无 source_id 时无去重
- **位置**：`reloop/modules/structuring.py:70-80`
- **问题**：导出 JSON 缺 id 字段时，重复导入产生重复人才行
- **修复**：P2 任务 8（兜底唯一键：owner + name + phone/email 哈希）

### BUG-105 ⬜ 删除人才不级联
- **位置**：`reloop/api/talents.py:58-70`
- **问题**：`DELETE /talents/{id}` 不清理关联 interaction_records / recommendations，留孤儿行
- **修复**：P2 任务 8

### BUG-106 ⬜ TTC 拉取静默截断
- **位置**：`reloop/modules/sync/client.py:67-70`
- **问题**：fetch 遇非 200 只 break 返回部分页，调用方无法区分"拉全了"与"拉了一半"
- **修复**：P2 任务 8（显式报错 + 标记部分同步）

## P1 — 前端假功能

### BUG-201 ⬜ 人才详情雷达图是编造的固定值
- **位置**：`webapp/app.js:212`
- **问题**：activity 0.5 / match 0.6 / relationship 0.3 写死，每个候选人显示一模一样的雷达形状
- **修复**：接真数据（需后端"单人才实时因子"接口）或删除雷达图

### BUG-202 ⬜ "修正"按钮是半成品
- **位置**：`webapp/app.js:153,171`
- **问题**：只发 `{talent_id, action:"correct"}`，无 UI 输入 `corrected_tag`，后端校准逻辑永远拿不到值
- **修复**：补标签输入 UI 或摘除按钮

### BUG-203 ⬜ feedback 失败无回滚
- **位置**：`webapp/app.js:171`
- **问题**：无 try/catch，失败时 UI 已先改成"已确认"并扣减计数、不回滚，产生 unhandled rejection
- **修复**：乐观更新 + 失败回滚

### BUG-204 ⬜ renderSettings 网络抖动强制登出
- **位置**：`webapp/app.js:268`
- **问题**：`api.me()` 任何异常（含网络抖动）都 `clearAuth()` 强制登出
- **修复**：仅 401/403 登出，其余显示错误提示

### BUG-205 ⬜ http() 吞掉后端错误 detail
- **位置**：`webapp/data/provider.js:53`
- **问题**：所有非 2xx 压成裸状态码，"请先设定岗位"等提示完全丢失
- **修复**：透传 response JSON 的 detail

### BUG-206 ⬜ preview 态靠中文字符串前缀判断
- **位置**：`webapp/app.js:138` ↔ `reloop/engine.py:315`
- **问题**：靠 `"快速初筛"` 模板文案判断 preview 态，改文案即破
- **修复**：接口显式返回 `is_preview: true` 字段

### BUG-207 ⬜ 新用户无岗位时首页 fallback 硬编码岗位
- **位置**：`webapp/app.js:73`
- **问题**：fallback 到 `"商业分析师"`，必然 400
- **修复**：无岗位时显示引导设岗的空态页

## P2 — 工程与配置

### BUG-301 ⬜ environment.yml 缺 segno
- **位置**：`environment.yml`（`requirements.txt:10` 有）
- **影响**：按 README 主推的 conda 装环境，`/auth/feishu/qrcode` 必 500
- **修复**：补依赖

### BUG-302 ⬜ 测试不显式设 BRAINX_AUTH_REQUIRE_TOKEN=false
- **位置**：`tests/`
- **问题**：代码默认 `True`（config.py:42），能跑过纯属本机 `.env` 恰好关了它，换机器/CI 全红
- **修复**：测试 conftest 显式设置

### BUG-303 ⬜ LLM 厂商三处说法不一
- **位置**：README（智谱 BigModel）/ `config.py:61`（阿里云 DashScope）/ `.env.example:23`（火山方舟）
- **修复**：统一为实际使用的厂商

### BUG-304 ⬜ TTC base_url 默认值与 .env.example 注释矛盾
- **位置**：`config.py`（`app.ttcadvisory.com`）vs `.env.example`（`gateway.ttcadvisory.com`）
- **影响**：用默认值拉取必失败
- **修复**：统一为正确地址

### BUG-305 ⬜ README 接口表过时
- **位置**：README
- **问题**：缺 `/recommend/result`、`/auth/*`、`/talents/{id}/interactions`；鉴权说明仍写 `X-Owner-User-Id`（生产已强制 `X-Auth-Token`），照 README 操作会 401
- **修复**：P3 文档更新

### BUG-306 ⬜ 配置漂移杂项
- 噪声阈值代码默认 0.1（config.py:99）vs `.env.example:47` 的 0.2
- README 称"6 张 ORM 表"实际 7 张
- `check_db.py:93-94` 漏检 `recommend_runs`
- schema.sql 与 ORM 不一致：`recommendations.talent_id` 索引缺失、FK 策略不统一、列默认值不同

## P3 — 死代码 / 遗留

### BUG-401 ⬜ 死代码清理
- `frontend/app/` 空目录
- `server.js` + `package.json` 与后端 StaticFiles 功能重复
- 后端死代码：`LLMService.analyze_tendency` + `TENDENCY_PROMPT`、`scoped_query`、`match_score`（v1）
- users 表 `ttc_space_id/ttc_auth_token/ttc_bound_name` 三列 DEPRECATED 仍在建表/补列逻辑维护
- 前端死代码：i18n `ttc_*` 死键、`gaps_list` 过时文案、`api.health()` 无调用方、`index.html` 重复加载 mock.js/provider.js
- 无调用方接口：`GET /recommend/latest`（且 N+1）、`DELETE /talents/{id}`

### BUG-402 ⬜ 仓库卫生
- `.workbuddy/tmp_*.py` 临时脚本（硬编码 `/opt/reloop`）
- 根目录 `test_local.db`、被 git 跟踪的测试 db 文件（`.gitignore` 未覆盖 `*.db`）
- mock 数据脏人名 `"周render"`

## 业务设计待决策（非 bug）

- **D-1**：`/sync/ttc` 全局 Token 设计意味着任何登录用户能把全公司 TTC 人才库拉进自己池子——注释称是明确决策，数据治理上需确认
- **D-2**：同步是 10 分钟级阻塞 HTTP 请求，无后台化/进度反馈/并发锁，失败整批回滚
- **D-3**：无 Dockerfile、无 CI、无部署脚本/gunicorn 配置
- **D-4**：性能隐患（上万规模前需处理）：`_shortlist` 全表扫描 + Python 过滤、embedding 应用层逐人余弦、`/recommend/latest` N+1、`/talents` 不传 limit 全量返回
