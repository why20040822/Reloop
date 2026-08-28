# Reloop 架构升级蓝图（骨架设计 v2）

> 日期：2026-08-28 ｜ 基线：`main` = `0acda2a`（Phase 1 止血已上线）｜ 测试基线：42 Python + 28 前端全绿
> **状态：待审核。本文档是实施前置件——你审核通过后，才按第四节迁移路线动代码。**
> 前置报告：`docs/2026-08-28-architecture-review.md`（问题清单）、`docs/plans/2026-08-28-gap-audit-and-refactor-plan.md`（四阶段方案）

---

## 〇、审计修订记录（2026-08-28，采纳 `docs/plans/2026-08-28-blueprint-audit.md`）

审计经生产实证（SSH 查 systemd + 进程树）后本蓝图已修订，**实证结论如下**：

1. **生产实际 = `uvicorn --workers 1` 单 worker**（systemd ExecStart 实证，无 gunicorn 进程）——本文原风险 #1（多 worker 状态不一致 🔴20）**当前不成立**，降级为 🟡9 **潜伏约束**：auto_login/进度/幂等锁的正确性依赖单 worker，但该约束此前未文档化，任何人按旧文档改回多 worker 会整套复发。
2. **R3 由"改部署"改为"文档化约束"**：README/systemd 注释写明"单 worker 是 auto_login/进度/幂等锁的正确性前提"；R6（sync_runs 落库）升为**回多 worker 的必要前置护栏**。
3. 基线更新：`main` = `1ea156c`（+2 commit：dedup 脚本修复、JD 解析修复）；测试基线统一为 **43 Python + 28 前端**。
4. 死代码链（provider/check/capture）经审计确认**可安全删除**（全仓引用关系核验）。
5. 第九节排期以**审计 v2 版**为准（批次 1 缩短为 ~1.5h，R6 优先级上调）。

---

## 一、全量代码解析结论（内部代码逐文件盘点）

### 1.1 模块清单与实测职责

| 层 | 文件 | 行数 | 职责 | 健康度 |
|---|---|---|---|---|
| 入口 | main.py | 83 | lifespan 安全自检+CORS+GZip+5 路由+webapp 静态托管 | ✅ 清晰 |
| 配置 | config.py | ~210 | pydantic-settings，~40 配置项，validate_security 启动自检 | ✅（有死配置） |
| 路由 | api/auth.py | 172 | 飞书 OAuth / TTC 绑定 / auto-login 端点 / me | ⚠️ 混业务 |
| 路由 | api/sync.py | 46 | 同步触发+进度 | ✅ 薄 |
| 路由 | api/talents.py | 204 | 列表/详情/关注/互动/删除 | ⚠️ 访客自动同步藏在列表接口里 |
| 路由 | api/positions.py | 112 | parse-jd + 设岗（含手写幂等 upsert） | ⚠️ 实体 upsert 逻辑在路由层 |
| 路由 | api/recommend.py | 153 | compute/result/latest/feedback | ⚠️ feedback 里写状态回写规则 |
| 数据 | db/engine.py | 152 | create_all + _ensure_columns + _ensure_indexes | ✅（补丁式迁移的天花板快到了） |
| 数据 | db/models.py | 275 | 7 表，owner 隔离键，唯一约束已加 | ✅（FK 策略不统一） |
| 同步 | modules/sync/client.py | ~330 | TTC HTTP+重试+hash 去重+指纹+per-owner 锁+异步线程 | ⚠️ 编排+IO 混在一文件 |
| 同步 | modules/sync/normalizer.py | ~580 | 双路径归一化+字段映射+指纹 | ✅ |
| 画像 | modules/profile/structuring.py | ~150 | LLM 增强+upsert+IntegrityError 兜底 | ✅ |
| 画像 | modules/profile/llm.py | 409 | chat/embed 双熔断+批量评分+title 相似度+2 进程缓存 | ⚠️ 见 1.2-2 |
| 推荐 | modules/recommend/engine.py | **787** | 两阶段计算+缓存栈+粗筛+精算+排名+条目构建+状态回填 | 🔴 单类 7 种职责 |
| 评分 | modules/scoring/factors.py + priority.py | ~370 | 活跃度+匹配度+加权乘法 | ✅（Phase1 已修） |
| JD | modules/positions/jd_parser.py | 77 | stepfun OpenAI 兼容解析 | ✅ |
| 认证 | modules/auth/feishu.py | 179 | OAuth+HMAC 会话 token（无状态） | ✅ |
| 认证 | modules/auth/ttc.py | 52 | 官方 token 校验 | ✅ |
| 认证 | modules/auth/vault.py | 127 | Fernet 加密存储 | ✅ |
| 认证 | modules/auth/auto_login.py | **375** | Playwright 无头扫码抓 token，**进程内会话** | 🔴 见 1.2-1 |
| 认证 | modules/auth/provider.py + check.py + capture.py | 251 | 上一代手动抓 token 方案 | 🔴 死代码链（见 1.2-3） |
| 前端 | frontend/src/App.tsx | **424** | 单文件 8 个页面组件+路由 | 🔴 无法单测 |
| 前端 | frontend/src/lib/api.ts | 231 | 类型化 API 层+mock 模式 | ✅ 优质资产 |
| 前端 | lib/*（6 个工具）+ components（2 个） | ~600 | 抽离良好的纯函数/组件 | ✅ |

### 1.2 本轮全量解析的新发现（此前报告未覆盖）

**1. 进程内状态 vs 4 worker 的系统性矛盾（本轮最重要发现）**

生产 gunicorn 跑 **4 worker**，但以下状态全部活在**单个进程**里：

| 状态 | 位置 | 后果 |
|---|---|---|
| auto_login 扫码会话 | `_sessions` dict（代码自注释"必须单 worker 部署"） | 轮询请求落到别的 worker → **3/4 概率"会话不存在"**，扫码绑定随机失败 |
| 同步进度 | `_SYNC_PROGRESS` dict | 前端进度条时灵时不灵（只有发起 worker 查得到） |
| 同步幂等锁 | `_OWNER_SYNC_ACTIVE` dict | 锁只在本进程有效，跨 worker 可并开全量同步 |
| 推荐/评分缓存 | `_FINAL_CACHE`/`_PREVIEW_CACHE`/`_MATCH_SCORE_CACHE`/`_TITLE_SIM_CACHE` | 命中率打 4 折（只是浪费，不是错误） |

**结论：当前是"多进程部署 + 单进程状态"的最差组合**。要么降单 worker，要么共享状态全部落 DB/Redis——必须二选一（见 2.3）。

**2. 匹配度分位校准也是"批内相对归一化"**（llm.py:388-396）：`batch_match_scores` 把本批 LLM 分数线性映射到 [0.1, 0.9]（min→0.1，max→0.9）。这与活跃度已废除的 min-max 是**同一种病**：同一候选人在强批次里被压低、弱批次里被抬高，跨岗位/跨时间不可比。应删除校准、在 prompt 里锚定绝对评分标准（prompt 已有锚定规则，校准反而破坏它）。

**3. auth 模块死代码链**：`provider.py:24` 引用 config 里**不存在**的 `settings.auth_token_ls_keys`（调用即 AttributeError）→ 依赖它的 `check.py` 一并失效；`capture.py` 是 Playwright 手动抓 token 的上一代方案。三者共 251 行，全部被 `auto_login` 取代，且 provider 已是**坏代码**（不是仅未使用）。

**4. `engine.py` 787 行单类**：`RecommendEngine` 承担缓存键管理/粗筛召回/精算/排名/条目构建/状态回填/后台线程管理 7 种职责。Phase 1 改它时必须逐行小心——这就是"脆弱"的直接来源。

**5. `App.tsx` 424 行单文件 8 个组件**：Dashboard/TalentList/TalentDetail/Positions/Settings/3 个回调页全在一个文件。`lib/api.ts`（类型化+mock 双模式）质量很好，是拆分的天然接缝。

**6. 隐藏契约无测试**：`set_position` 里"同名同 JD 同解析 → 幂等返回"是手写实体 upsert，Dashboard 和 Positions 两条 UI 路径都依赖它去重——没有测试守护，改文案即碎。

**7. FK 策略不统一**：`interaction_records`/`recommendations.talent_id` 有 FK 无 ondelete；`feedback_logs.talent_id` 无 FK。BUG-105 只能靠应用层手动级联（已做），约束层没兜底。

---

## 二、目标骨架（方案 A：保守治理，推荐）

**原则：目录不大挪移**（部署路径、git 历史、测试引用全不动），用两条硬规则治理——**依赖方向** + **状态归属**——然后把两个巨文件拆掉。

### 2.1 依赖方向（单向，违者即架构 bug）

```
api/ ──▶ services/ ──▶ core/（纯算法，零 IO）
            │               ▲
            └───▶ infra/ ───┘（db / llm / ttc / feishu，只有 infra 碰网络和 DB）

schemas/ = 唯一契约：api 与 services 之间只传 schemas 定义的结构
```

### 2.2 新骨架（增量新建，旧位逐步清空）

```
reloop/
  api/                  # 只做：参数校验 → 调 service → 异常映射 HTTP。禁止业务规则
  services/             # 【新】业务编排（从 api 与 engine 抽出）
    recommend_service.py   # compute/result_of 编排 + 缓存键 + 状态回填
    sync_service.py        # 同步编排 + 幂等锁 + 进度（Phase2 落 sync_runs 表）
    talent_service.py      # 列表/删除级联/关注/访客自动同步（从 talents.py 路由里拔出）
    auth_service.py        # 登录/绑定/会话签发
  core/                 # 【新】纯算法（零 IO，全部可内存单测）
    activity.py            # 活跃度：纯绝对衰减 + 门禁（从 factors 拆出）
    scoring.py             # factors 剩余 + priority 合并
    matching.py            # 结构化五维 + LLM 批量评分封装（不含 HTTP）
  infra/                # 【新】IO 边界
    llm_client.py          # 原 modules/profile/llm.py（去业务缓存，缓存归 core）
    ttc_client.py          # 原 modules/sync/client.py 的 HTTP/重试部分
    db/                    # 原 reloop/db/（engine/models 原位保留亦可）
  modules/              # 逐步清空后删除（迁移期允许旧新并存）
frontend/src/
  pages/                # 【新】Dashboard / TalentList / TalentDetail / Positions / Settings
  components/           # 通用件：Avatar / Notice / KeyValue / Empty / Loading（从 App.tsx 拔出）
  lib/                  # api.ts 保留；新增 hooks（useAuth / useSyncPolling）
  App.tsx               # 只留路由（目标 < 80 行）
```

### 2.3 状态治理（解决 4 worker 矛盾，二选一拍板）

| 方向 | 做法 | 代价 | 适合 |
|---|---|---|---|
| **方向 1（短期推荐）** | gunicorn 降为 **1 worker**（uvicorn worker + 进程内线程池承接并发） | 部署改一行；并发上限=线程池 | 内测规模（当前日活个位数~几十），auto_login/进度/锁立即全部正确 |
| 方向 2（中期） | 共享状态落 DB：`sync_runs` 表（进度+幂等锁）+ auto_login 会话表/Redis | 多一张表+改造 auto_login | 用户量上来、单 worker 成瓶颈时 |

**推荐节奏：先方向 1（立即生效、零改造），方向 2 并入 Phase 2 的 sync_runs 一并做。**

### 2.4 算法修正（解析直接得出，随骨架一并做）

- **M1** 删除 `batch_match_scores` 分位校准（批内相对归一化），评分锚定交给 prompt 既有规则；⚠️ 上线后匹配分数会变（更真实但和旧缓存不可比），需清一次 recommend_runs 缓存。
- **M2** 死代码链执行删除：`provider.py` / `check.py` / `capture.py` / `analyze_tendency`+`TENDENCY_PROMPT` / `scoped_query` / DEPRECATED 权重与 ttc_* 列（列改为注释保留说明）。

---

## 三、方案 B：完整重排（不推荐现在做）

`src/reloop` 布局 + Alembic 正式迁移 + Dockerfile + 多服务拆分。**触发条件（满足任一再启动）**：外部团队接入 / 需要水平扩多实例 / sync_runs 仍扛不住并发 / 招聘日处理量稳定 >200 份。现在做只会拖慢 Phase 2 的业务目标。

---

## 四、迁移路线（每步独立可回滚，测试守护）

| 步 | 内容 | 前置 | 验收 | 回滚 |
|---|---|---|---|---|
| **R1** | 拆 `engine.py` → `services/recommend_service.py` + `core/{activity,scoring,matching}.py`（**纯搬运不改行为**，旧 engine 变 2 行转发壳） | 无 | 42+28 测试全绿，断言不改 | git revert 单 commit |
| **R2** | 拆 `App.tsx` → `pages/` + `components/`（纯搬运） | 无 | `npm run build` 过 + 28 mjs 绿 + 手点五页 | 同上 |
| **R3** | 部署改为**单 worker**（gunicorn -w 1） | 拍板 2.3 方向 1 | auto-login 轮询/进度条跨请求稳定 | 改回 -w 4 |
| **R4** | M1 校准删除 + 清 recommend_runs 缓存 | 拍板 | 分数绝对可比（同人在不同批次分差 < 噪声阈值） | revert + 重新缓存 |
| **R5** | 死代码链删除（M2 清单） | 无 | 全量测试绿 + grep 零引用 | revert |
| **R6** | `sync_runs` 表 + 进度/锁落库（=Phase 2 第一项） | R1 | 双 worker 也能查进度（若已回多 worker） | 表保留，代码回退 |
| **R7** | CI（pytest + node --test）+ 可选 Dockerfile | 拍板"恢复 push 或本地 hook" | 干净机器一键跑绿 | 不适用 |

**关键约束：R1/R2 是"搬运不变行为"——现有测试一个断言都不能改；改了就说明搬错了。**

---

## 五、总验收标准

1. 42 Python + 28 前端测试全绿（R4 除外——它有显式的分数变化说明）。
2. 同一请求打到任意 worker 行为一致（进度查询、auto-login 轮询不再随机 404）。
3. `engine.py` < 50 行（转发壳）；`App.tsx` < 80 行（纯路由）；api/ 路由内无业务规则、无裸 DB 写。
4. `core/` 内模块零 IO import（可用一条 import 守卫测试固化）。
5. 部署脚本/文档与实际架构一致（README 同步更新）。

---

## 六、待你拍板（通过后立即按 R1 开工）

1. **方案 A（保守治理，推荐）还是方案 B**？
2. **状态治理**：先单 worker（推荐）还是直接 sync_runs 落库？
3. **M1 删分位校准**会改变线上匹配分数（更真实但与旧缓存不可比），接受吗？
4. **迁移顺序** R1→R7 有无要调整的？

---

## 七、完整目标架构（方案 A 展开到文件级）

### 7.1 运行拓扑（目标态）

```
用户浏览器 (React SPA, webapp/ 构建产物, 同源)
     │ HTTPS
nginx :443 (LE 证书, 反代 127.0.0.1:8000)
     │
gunicorn :8000 ── 单 worker (uvicorn worker + 线程池)     ← R3 改动点
     │
FastAPI app
  ├─ api/        5 个路由: auth / sync / talents / positions / recommend
  ├─ services/   业务编排: recommend_service / sync_service / talent_service / auth_service
  ├─ core/       纯算法(零 IO): activity / scoring / matching
  ├─ infra/      IO 边界: llm_client(stepfun/智谱) / ttc_client(TTC HTTP) / db/
  └─ schemas/    唯一契约(jd / talent)
     │
     ├── RDS MySQL reloop_app (7 表 + sync_runs)
     ├── stepfun Plus Plan (JD 解析, 至 2026-11-22)
     ├── 智谱 BigModel (embedding, 或离线哈希降级)
     └── TTC 网关 (人才库数据源)
```

### 7.2 services/ 层契约（每个文件的输入/输出/副作用）

| 文件 | 公开函数 | 输入 | 输出 | 副作用 |
|---|---|---|---|---|
| services/recommend_service.py | `compute(db, owner, ...)` `result_of(db, owner, ...)` `backfill_status(...)` | db 会话+查询参数 | 结果 dict（schemas 结构） | 写 recommend_runs / recommendations |
| services/sync_service.py | `trigger_sync(owner, ...)` `progress(sync_id)` | owner+凭据 | sync_id / 进度 dict | 写 talent_profiles / sync_runs(R6) |
| services/talent_service.py | `list_talents(...)` `delete_cascade(...)` `toggle_follow(...)` `maybe_autosync_guest(...)` | db+owner+过滤条件 | ORM 行 / bool | 删关联三表（BUG-105 逻辑归此） |
| services/auth_service.py | `login_by_feishu(code)` `bind_ttc(user, token)` `me(user)` | 凭据 | token/user dict | 写 users |

规则：api/ 路由内**禁止**出现裸 `db.query(...).delete()`、业务分支、状态回写——全部下沉 services；api 只剩 参数校验→调用→HTTP 异常映射。

### 7.3 core/ 层契约（纯函数，可内存单测，零 IO import）

| 文件 | 公开函数 | 说明 |
|---|---|---|
| core/activity.py | `activity_score(events, now)` `days_since(events, now)` `absolute_score(days)` `gate_status(days)` | 活跃度 v3：纯绝对衰减+门禁（Phase1 已修逻辑的归属地） |
| core/scoring.py | `weighted_product(fs)` `rank_candidates(...)` `min_max_normalize(...)` | 加权乘法模型 |
| core/matching.py | `match_score_structured(...)` `skill_coverage(...)` `years_fit(...) edu_fit(...)` | 结构化五维；LLM 批量评分的**编排**留在 service，HTTP 在 infra |

### 7.4 infra/ 层

| 文件 | 从哪来 | 改造点 |
|---|---|---|
| infra/llm_client.py | modules/profile/llm.py | 保留双熔断；`_MATCH_SCORE_CACHE`/`_TITLE_SIM_CACHE` 迁到 core 层由调用方注入；删 M1 分位校准 |
| infra/ttc_client.py | modules/sync/client.py 的 TTCClient 类 | 纯 HTTP+重试+归一化调用；编排（锁/进度/落库）归 sync_service |
| infra/db/ | reloop/db/ 原位不动 | R6 增加 sync_runs 模型 |

### 7.5 sync_runs 表（R6，DDL 预览）

```sql
CREATE TABLE sync_runs (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  owner_user_id VARCHAR(64) NOT NULL,
  sync_id VARCHAR(64) NOT NULL,             -- 幂等键: per-owner 唯一活跃行
  source VARCHAR(16) NOT NULL,              -- owned | shared | ingest
  status VARCHAR(16) NOT NULL DEFAULT 'running',  -- running/done/failed
  total INT NULL, current INT NULL, synced INT NULL, skipped INT NULL,
  message VARCHAR(256) NULL, error TEXT NULL,
  created_at DATETIME NULL, updated_at DATETIME NULL,
  INDEX ix_sync_owner (owner_user_id, status),
  UNIQUE KEY uq_sync_active (owner_user_id, sync_id)
);
```
幂等锁语义：触发同步前 `SELECT ... WHERE owner=? AND status='running' AND updated_at > now-30min`，存在则复用其 sync_id；跨进程正确。

### 7.6 方案 B 完整形态（预览，触发即启动）

```
src/reloop/
  domain/        # 实体+纯逻辑（=core）
  application/   # 用例层（=services）
  adapters/      # http(=api) / db / llm / ttc
Alembic 迁移目录 + Dockerfile + docker-compose(app+nginx+redis) + GitHub Actions
多服务拆分线: 同步 daemon 独立进程(消费队列) / 推荐 API 水平扩
```
触发条件（任一满足）：外部团队接入；需要水平扩多实例；日处理量稳定 >200 份；sync_runs 落库后仍有跨进程竞争热点。**在此之前不做。**

---

## 八、当前风险评估（量化评析）

> 评估时点：2026-08-28 19:50，Phase 1 止血 + JD 修复已上线。
> 打分：概率(1-5) × 影响(1-5)，≥12 红灯 / 6-11 黄灯 / ≤5 绿灯。

### 8.1 风险矩阵

| # | 风险 | 概率 | 影响 | 分 | 等级 | 状态 |
|---|---|---|---|---|---|---|
| 1 | ~~多 worker 进程内状态不一致~~ → **单 worker 隐性约束未文档化**（生产实证 uvicorn -w 1；谁按旧文档改回多 worker，auto_login/进度/幂等锁整套复发） | 2 | 4 | **8** | 🟡 黄 | 批次 1 文档化；R6 落库后解除 |
| 2 | 匹配分批内分位校准（分数跨批漂移、排序随导入批次抖动） | 5 | 3 | **15** | 🔴 红 | 开放 → R4 删除 |
| 3 | 同步费用放大（全量重拉+逐人 embedding，同步接口无限流） | 3 | 4 | **12** | 🔴 红 | 部分缓解（hash skip 已上线，内容不变时零 LLM）→ R6 增量+限流 |
| 4 | 巨型文件改动风险（engine 787 行 / App 424 行，每次修改都是盲改） | 4 | 3 | **12** | 🔴 红 | 开放 → R1/R2 |
| 5 | 访客池 /sync/ttc 409（服务器缺 BRAINX_TTC_SHARED_AUTH_TOKEN，配置缺口） | 4 | 3 | **12** | 🟡 黄 | **待你给 token 决策** |
| 6 | 无 CI，回归靠人肉（今天 3 次上线全靠手动跑测试） | 3 | 3 | 9 | 🟡 黄 | → R7 |
| 7 | token 无吊销 / OAuth state 固定 / CORS 默认 * | 2 | 4 | 8 | 🟡 黄 | Phase 4（内测期利息低） |
| 8 | 死代码链（provider 已损坏，误调用即 500） | 2 | 3 | 6 | 🟡 黄 | → R5 删除 |
| 9 | webapp 构建产物入库（git 历史膨胀、合并冲突） | 3 | 2 | 6 | 🟡 黄 | 待拍板 gitignore |
| 10 | LLM key 单点（stepfun 2026-11-22 到期、BigModel 本地配置长期不可用） | 2 | 4 | 8 | 🟡 黄 | 设续费提醒；降级链路已通 |
| 11 | 单 worker 后吞吐上限（线程池并发，当前日活完全够用） | 1 | 2 | 2 | 🟢 绿 | R6 后可回多 worker |
| 12 | 数据重复 / 假活跃 / 反馈丢失 / JD 解析 2/3 失败 | — | — | — | 🟢 绿 | **今日已清零** |

### 8.2 总体评析（三句话）

1. **数据正确性主链路已闭环**：同步去重、活跃度、反馈闭环、JD 解析四大病灶今日全部修复上线并有测试守护——这是最不可逆的一层，已安全。
2. **剩余红灯全部集中在"并发状态一致性 + 费用"**（#1/#2/#3/#4），且每项都有 <1 天的确定性修复，不存在需要研究探索的未知项。
3. **安全债利息仍低**（内测规模），但 #5 访客池 409 是唯一一个**阻塞用户体验**的配置缺口——今天就能由你一句话解决。

---

## 九、确定排期（锁定版 v2，按审计修订）

> 默认决策已按推荐锁定，你只需否决不需要逐项确认：**方案 A ｜ 接受 M1 分数变化 ｜ 顺序按收益/成本比排列**。（单 worker 已是生产现状，不再是决策项——改为文档化约束。）

| 批次 | 内容 | 预计 | 上线物 |
|---|---|---|---|
| **批次 1（今天，~1.5h）** | 单 worker 约束文档化（README + systemd 注释写明"单 worker 是 auto_login/进度/幂等锁的正确性前提"）→ R5 死代码删除（provider/check/capture 等）→ R4 删分位校准+清 recommend_runs 缓存 | 3 个 commit | 潜伏约束显性化、代码 -251 行、排序不再随批次抖动 |
| **批次 2（明天，~1 天）** | R1 拆 engine.py → services+core；R2 拆 App.tsx → pages/（纯搬运，测试断言禁改） | 2 个 commit | engine <50 行壳、App <80 行路由 |
| **批次 3（后天，~2 天）** | R6 sync_runs 落库 + 增量同步 + LLM 批量 embedding + 同步限流（=Phase 2 主体；**优先级上调：回多 worker 的必要前置护栏**） | 1 个 commit | 5→50 简历/天达成；可选回多 worker |
| **批次 4（本周内，~1 天）** | R7 CI + 安全四件套（token 吊销/state/CORS）+ README 对齐 | 2 个 commit | 干净机器一键回归 |

**每个批次的通用守则**：上线前 43+28 测试全绿 → tar 部署 → `/health` + 冒烟 → 单 commit 可 revert。

**你现在只需要回一句话**：「按锁定排期开工」或指出要改的默认项（含：#5 访客池 token 用全局同值还是专用只读）。
