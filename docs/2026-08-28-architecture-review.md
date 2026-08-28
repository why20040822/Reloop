# Reloop 架构全面审核（2026-08-28）

> 审核基线：`main` = `58bf1ce`（origin/main `781663e` + 本地 perf 提交，本次已按"云端为主"fast-forward 合并，工作树干净）
> 测试结果：**37 Python + 28 前端 = 65 全部通过**（SQLite + 离线 LLM，无需外部凭据）
> 方法：对照 2026-08-22 `CODE_REVIEW.md` 逐项代码复核 + 近 33 个新提交的增量审查（不信任旧文档，只信当前代码）

## 一、结论摘要

1. 测试全绿，代码可跑；旧审查（2026-08-22）的 6 项高优先级问题已修复并经本次验证。
2. 仍有 **3 个实锤开放的 P1 正确性 bug**：反馈状态刷新即丢（BUG-101）、跨天反馈静默丢（BUG-103）、删除人才不级联（BUG-105）。
3. 安全缺口 4 项开放：token 无吊销、OAuth state 硬编码、CORS 默认 `*`、`/sync/ttc` 无限流。
4. **5→50 简历/天的最大瓶颈在同步链路**：阻塞式 HTTP + 全量重拉 + 逐人 LLM 调用。
5. 工程卫生：webapp/ 构建产物入库、死的前端备份目录、`.gitignore` 缺 `*.db`、environment.yml 缺 segno。

## 二、与 2026-08-22 审查对照（逐项验证已修复）

| 旧编号 | 问题 | 本次验证结果 | 证据 |
|---|---|---|---|
| BUG-001 | RDS 凭据硬编码 | ✅ 代码已修复（默认空 + 启动 `validate_security()` 报错）。⚠️ git 历史脱敏仍待人工 | config.py:53-58, 151-160 |
| BUG-002 | auth_secret 固定串兜底 | ✅ 已修复：强制登录无密钥直接 RuntimeError | config.py:131-149 |
| BUG-102 | 时区混用 | ✅ 已修复：全部 `timezone.utc`（仅 engine.py:298,377 `generated_at` 显示串用本地时间，纯显示无正确性影响） | factors.py:116 / engine.py:68-70 / normalizer.py:104-127 / models.py:37-38 |
| BUG-106 | TTC 静默截断 | ✅ 已修复：非 200 抛 `TTCFetchError` + 重试退避 | client.py:111-114, 147-165 |
| BUG-305 | README 鉴权/接口过时 | ✅ 基本修复（X-Auth-Token、/recommend/result、/auth/* 已写明） | README:86, 97, 203, 251 |
| — | "两个前端并存"疑云 | 实为源码+产物：`frontend/`(React, vite) `npm run build` → `webapp/` | vite.config.ts `outDir: "../webapp"` |

## 三、仍开放问题（逐项代码验证）

### P1 正确性（3 个实锤）
| 编号 | 问题 | 位置 | 影响 |
|---|---|---|---|
| BUG-101 | 推荐结果不序列化 `status` → 点"去联系"后刷新/命中缓存回到 pending | engine.py `_build_items` 718-737：item dict 无 status 字段（只有 `/recommend/latest` 有） | 反馈闭环失真，"待确认"计数不准 |
| BUG-103 | 反馈回写只匹配 `recommend_date == today` | recommend.py:124-129 | 昨日缓存条目的反馈静默丢弃 |
| BUG-105 | `DELETE /talents/{id}` 不级联 | talents.py:149-151 | 孤儿 interaction_records / recommendations |

BUG-104（ingest 去重）**部分改善**：client.py 已加 `_source_hash` 同步内去重，但缺 source_id 的导出 JSON 跨导入仍重复。

### P1 安全（开放）
- **BUG-003** token 无吊销（7 天 TTL，登出仅清 localStorage）
- **BUG-004** OAuth state 硬编码 `"reloop"`（feishu.py:100），无 PKCE
- **BUG-005** CORS 默认 `*`（config.py:34）——生产必须显式设 `BRAINX_CORS_ALLOW_ORIGINS`
- **BUG-006** `/sync/ttc` 无幂等锁/限流 → LLM 费用放大
- **D-1** 全局 Token 设计：任何登录用户可把全公司池拉进自己名下（治理决策，需拍板）

### P2 性能（5→50 简历/天的瓶颈链，按阻塞程度排序）
1. 同步阻塞式 HTTP、全量重拉、无后台任务/对外进度 API/幂等锁 → 单次 10 分钟级
2. LLM embedding 逐人调用无批量 → 50 人 = 50 次调用
3. `_shortlist` 全表扫描 + Python 过滤（engine.py）
4. `list_followed` 全表 `.all()` + Python 过滤 tags（talents.py:82-87），无分页
5. `/recommend/latest` N+1（逐条 `db.get(TalentProfile)`）
6. `/talents` 默认仍全量返回；slim + gzip 是缓解不是根治（需确认前端列表请求带 `slim=true`）

### P3 工程卫生
- `webapp/` = vite 构建产物却入库（git 历史大 diff、合并冲突源）。两条路：gitignore + 部署时 `npm run build`；或文档化"提交产物"决策
- `webapp.before-d58319f-20260821-153955/` 死拷贝（旧 vanilla 版备份，已被 React 取代），可删
- `.gitignore` 缺 `*.db`（根目录 `test_local.db` 已入库）
- `environment.yml` 缺 `segno` → 按 README 用 conda 装环境，`/auth/feishu/qrcode` 必 500
- `check_db.py` 漏检 `recommend_runs` 表
- 根目录散落脚本：`_migrate_linda.py` / `check_db.py` / `server.js` / `test_match_score.py`
- 死代码：`analyze_tendency` + TENDENCY_PROMPT、`scoped_query`、v1 `match_score`、DEPRECATED 权重（score_w_value/relation/tendency）、DEPRECATED `users.ttc_*` 列、i18n 死键
- `schema.sql` 与 ORM 漂移；无 Dockerfile / 无 CI

## 四、新发现（旧审查未覆盖）

1. **vite `emptyOutDir` 直接清空 webapp/**——一旦 webapp 里混入手写文件会被 build 静默删除（当前无手写文件，属操作风险）。
2. `modules/auth/` 7 个文件 + `api/auth.py` 边界模糊；`auto_login`（Playwright 无头登录抓 Token）通道最脆弱，建议加显式开关 + 独立超时与审计日志。
3. LLM 熔断是**进程内**单例，gunicorn 4 worker 下各 worker 独立熔断（预期内，但排障/日志要按 worker 看）。
4. 前端 `.mjs` 测试是字符串/CSS 断言（如"侧栏样式定义了 icon rail"），集成度低：改类名即碎，改行为测不出。
5. `tests/conftest.py` 未显式设 `BRAINX_AUTH_REQUIRE_TOKEN=false`（test_pipeline.py 自己设了），CI 换机器可能全红——BUG-302 仍开放。
6. 访客池为空自动同步（talents.py:48-62）吞掉所有异常 `except: pass`——静默失败，违背"禁止静默失败"约定。

## 五、建议动作（优先级排序）

1. **BUG-101**：`_build_items` item 补 `status`（从 Recommendation 表回填），改动最小、收益最大。
2. **BUG-103 + BUG-105**：feedback 去掉 `recommend_date==today` 限制（或按 run_id 定位）；delete 级联清理关联表。
3. **同步链路后台化 + 增量同步**：5→50 的关键——后台任务 + 进度 API + 幂等锁 + 按 `updated_at` 增量拉取 + embedding 批量调用。
4. **安全四件套**：token 吊销（版本号方案最简单）、OAuth state 一次性化、生产 CORS 收紧、`/sync/ttc` 限流。
5. **仓库卫生一次性清理**：删 `webapp.before-*`、`.gitignore` 补 `*.db`、environment.yml 补 segno、死代码摘除、check_db.py 补表。
6. **CI**：`pytest tests/` + `node --test tests/*.test.mjs` 两条命令即可，65 个测试现成。

---

*BUGS.md 的状态标记尚未按本报告刷新（102/106 等可改 ✅），需要的话可同步更新。*
