# Reloop 需求缺口审核与工程架构整改方案

> 日期：2026-08-28 ｜ 基线：`main` = `58bf1ce` ｜ 前置报告：`docs/2026-08-28-architecture-review.md`
> 本文档只审不改。所有代码改动以下述 Phase 为准，每个 Phase 带验收标准。

---

## 〇、本轮输入验证结论（已实测）

### stepfun Plus Plan（JD 自动解析通道）
- Key 实测**有效**：`GET /step_plan/v1/models` 返回 200，可用模型 `step-3.7-flash` / `step-router-v1` / `step-3.5-flash(-2603)` 及 audio/image 系列。
- `chat/completions` + `response_format: {"type":"json_object"}` 实测 200，两个文本模型都原生返回独立 `reasoning` 字段——`jd_parser.py` 只读 `content`，**完全兼容，无需改代码**。
- **已写入本地 `.env`**（备份 `.env.bak.20260828-174113`）：
  ```
  BRAINX_DEEPSEEK_BASE_URL=https://api.stepfun.com/step_plan/v1
  BRAINX_DEEPSEEK_API_KEY=<已配置>
  BRAINX_DEEPSEEK_MODEL=step-3.7-flash
  BRAINX_DEEPSEEK_TIMEOUT_SECONDS=60
  ```
- **服务器 `.env` 需同样追加这三行**（勿动其他配置），重启 `reloop` 生效。
- ⚠️ 两个边界：① step_plan **没有 embedding 模型** → 画像 embedding 通道不能切过来，保持智谱 BigModel 或离线降级；② 有效期 **2026-11-22**，到期前需续费否则 JD 解析静默降级为不可用（`JDParserUnavailable`）。Key 属于凭据，禁止入库（.env 已被 gitignore，安全）。

---

## 一、数据导入重复 — 根因链（代码级实锤）

### 根因链（四个环节叠加）
1. **normalizer 造出空 source_id**：`_normalize_ttc_api_item` 与通用路径都是 `str(item.get("id") or "")` —— 记录缺 `id` 字段时 source_id 是**空字符串**（normalizer.py:306, 518）。
2. **sync 编排跳过查重**：`sync_for_user` 里 `sid = t.get("source_id") or None` → 空串转 `None` → `if sid:` 查重分支被跳过（client.py:222-224）。
3. **落库层无条件 INSERT**：`enrich_and_save` 收到 `sid=None` 不查 existing，每次必新增一行（structuring.py:64-117）。
4. **DB 层无唯一约束**：`(owner_user_id, source_id)` 只有普通索引 `ix_talent_source`，**没有 UniqueConstraint**（models.py:77,143）→ 即使 source_id 存在，并发同步（如访客池为空自动同步 talents.py:48-62 + 用户手动 `/sync/ttc` 同时跑）也能双插。且 `/sync/ttc` 无 per-owner 幂等锁，同一 owner 可并发触发两个全量同步线程。

### 现网验证 SQL（在 RDS `reloop_app` 上执行）
```sql
-- 空source_id的重复重灾区
SELECT owner_user_id, COUNT(*) FROM talent_profiles
WHERE source_id IS NULL OR source_id='' GROUP BY 1;
-- 同owner同source_id的重复
SELECT owner_user_id, source_id, COUNT(*) c FROM talent_profiles
WHERE source_id IS NOT NULL AND source_id<>''
GROUP BY 1,2 HAVING c>1 ORDER BY c DESC LIMIT 20;
-- 疑似同人重复(无source_id时按姓名+手机/公司兜底查)
SELECT owner_user_id, name, contact_phone, COUNT(*) c FROM talent_profiles
GROUP BY 1,2,3 HAVING c>1 ORDER BY c DESC LIMIT 20;
```

### 修复方案（F1–F4，全部必做）
- **F1 指纹兜底**：source_id 为空时生成稳定指纹 `hashlib.sha256(f"{owner}|{name}|{phone}|{email}|{company}|{position}")` 作为 source_id，**禁止落空串**。改 normalizer + sync_for_user 两处。
- **F2 唯一约束**：models.py 给 `(owner_user_id, source_id)` 加 `UniqueConstraint`；配套一次性去重迁移脚本（保留 id 最大/最新一行，删其余，先清历史再建约束）。
- **F3 同步幂等锁**：`TalentSyncService` 加 per-owner `threading.Lock` 注册表；同一 owner 已有 running 同步时直接返回进行中的 sync_id 而不是再开线程。`_SYNC_PROGRESS` 增加启动时间，>30min 视为僵死可覆盖。
- **F4 INSERT 冲突转 UPDATE**：`enrich_and_save` 捕获 `IntegrityError` 后回退到按 (owner, source_id) 更新，双保险。

---

## 二、活跃度指标失真（全员活跃）— 根因链

### 现象
全部人才都表现为"活跃"，活跃度因子失去区分度与门禁作用。

### 根因链（五个环节叠加，按影响排序）
1. **信号源本身不可信**（主因）：TTC 的 `dynamic.macro.last_updated_at` 是**记录更新时间**，不是"候选人活跃时间"——批量运营操作、同步刷新都会推高它；而字段缺失时 normalizer **兜底用 `item.created_at`（入库时间）**（normalizer.py:225-233）→ 新导入记录全员"刚活跃"。`resume_updated_at` 也 fallback 到 `last_updated_at`/`created_at`，两者恒同源。
2. **批内相对归一化制造假分布**：`hybrid_activity_normalize = 0.4×绝对 + 0.6×min-max相对`（factors.py:102-112）。min-max 归一化**保证池内必然有人得 1.0**——即使全员都不活跃，也会造出一个"活跃分布"。
3. **绝对窗口太宽**：`absolute_activity = 1 - days/180`（factors.py:95-99），60 天内得 0.67、30 天内 0.83，兜底即 0.4×0.83 ≈ 0.33 起步。
4. **无"不活跃"判定**：`FACTOR_FLOOR=0.05` 托底 + 0.1 噪声阈值，没有任何 days_since > N 即判不活跃的门禁逻辑。
5. 同源双计已修复（build_activity_events 去重），非本次问题。

### 检验方法（改造前后各跑一次，量化对比）
```sql
SELECT DATEDIFF(NOW(), last_active_at) AS days_ago, COUNT(*)
FROM talent_profiles WHERE owner_user_id='<owner>'
GROUP BY 1 ORDER BY 1 LIMIT 30;
```
若分布集中在 0–7 天 → 证实信号源失真（真实候选人不可能齐刷刷上周活跃）。

### 修复方案（A1–A5）
- **A1 信号源求真**：抓 TTC XHR 确认 `dynamic` 里是否有真实活跃事件字段（浏览/沟通/登录类）；确认前一律视为"未知"，**不猜**。
- **A2 去掉 created_at 兜底**（normalizer.py:226,232）：字段缺失就落 `NULL`，宁可"未知"不要假数据。
- **A3 删除批内相对项**：活跃度改为**纯绝对衰减**（`absolute_activity` 或牛顿冷却分），废除 min-max 混合——相对归一化只用于展示排序点缀，不进因子。
- **A4 活跃门禁（用户要求的"门禁"）**：`days_since > 90` → 标记 `inactive`，推荐默认排除（或 rank_score × 0.1 硬惩罚）；`last_active_at IS NULL` → 标 `unknown` 单独分组，不冒充活跃。阈值进配置 `BRAINX_ACTIVITY_INACTIVE_DAYS`。
- **A5 窗口收紧**：180 → 90 天（可配），让绝对分真正拉开差距。
- **A6 前端**：活跃度显示为等级（7 天内 / 30 天内 / 90 天内 / 90 天+ / 未知），不显示伪精确小数。

---

## 三、JD 自动解析接入 stepfun — 状态与要求

| 项 | 状态 |
|---|---|
| 代码 | ✅ 无需改动（OpenAI 兼容 + json_object 实测通过） |
| 本地 .env | ✅ 已写入并备份 |
| 服务器 .env | ⬜ 需用户按同样三行追加 + `systemctl restart reloop` |
| embedding 通道 | ⚠️ 保持现状（step_plan 无 embedding 模型） |
| 有效期管理 | ⚠️ 2026-11-22 到期，建议设提前 2 周的续费提醒 |
| 模型选型 | `step-3.7-flash`（默认，快且便宜）；解析质量不满意可试 `step-router-v1` |
| 成本控制 | 建议 .env 加开关 `BRAINX_JD_PARSE_ENABLED`（kill-switch 风格），解析失败不影响手动保存 JD |

---

## 四、工程架构总评与分阶段整改（严格方案）

### 脆弱性总评（一句话版）
**同步链路是"daemon 线程 + 内存进度 + 无锁 + 全量重拉 + 逐人 LLM"的临时堆叠；数据完整性没有 DB 约束兜底；评分因子建立在不可信信号源上；工程上无 CI、构建产物入库。** 能跑，但经不起并发、换机器和规模放大。

### Phase 1 — 数据正确性（最高优先级，约 1–2 天）
| 改动 | 文件 | 验收标准 |
|---|---|---|
| F1 source_id 指纹兜底 | normalizer.py / client.py | 同一导出 JSON 连续导入 2 次，第二次 `synced=0 skipped=N`，零新增行 |
| F2 唯一约束 + 去重迁移脚本 | models.py + `scripts/dedup_talents.py` | 现网去重后建约束成功；并发双同步不再产生重复 |
| F3 per-owner 同步锁 | client.py | 同 owner 连续 POST /sync/ttc 两次返回同一 sync_id |
| F4 IntegrityError 兜底 | structuring.py | 人为制造冲突时转 UPDATE 不报 500 |
| A2 去掉 created_at 兜底 | normalizer.py | 缺时间字段的记录 last_active_at=NULL |
| A3/A4/A5 活跃度重构 | factors.py + engine.py + config.py | 检验 SQL 分布与因子分脱钩；>90 天人才被门禁拦截；同池活跃分有区分度（非全员>0.4） |
| BUG-101 补 status 序列化 | engine.py `_build_items` | 点确认→刷新→状态保持 confirmed |
| BUG-103 跨天反馈 / BUG-105 删除级联 | recommend.py / talents.py | 昨日缓存条目反馈可回写；删除后无孤儿行 |

### Phase 2 — 同步链路后台化（5→50 简历/天的关键，约 2–3 天）
1. 增量同步：拉取带 `updated_after` 参数（若 TTC 支持）或按 source_hash 跳过不变记录（现已有，需配合 F1 全覆盖）。
2. LLM 批量化：embedding 走批量接口（现有逐人 embed 改批量）；contact_reason 只对 TopN 已是，保持。
3. 进度持久化：`_SYNC_PROGRESS` 内存字典 → 落 `sync_runs` 表（worker 重启不丢进度）。
4. 限流：同 owner 同步最小间隔（如 10 分钟），超出返回 429 + 上次成功时间。
5. 验收：378 人重复同步 <1 分钟完成（全 skip）；LLM 调用次数 = 新增/变更人数；并发 10 人各自同步互不阻塞。

### Phase 3 — 工程化（约 2–3 天）
1. CI：GitHub Actions 两步（`pytest tests/` + `node --test tests/*.test.mjs`），conftest 显式设 `BRAINX_AUTH_REQUIRE_TOKEN=false`（BUG-302）。
2. 仓库卫生：删 `webapp.before-*`；`.gitignore` 补 `*.db`；`environment.yml` 补 segno；死代码摘除（analyze_tendency / scoped_query / v1 match_score / DEPRECATED 权重与 ttc_* 列 / i18n 死键）。
3. webapp 构建产物：**建议** gitignore + 部署脚本加 `npm run build`（需用户拍板，涉及现有部署流程）。
4. schema.sql 与 ORM 二选一对齐（建议废弃 schema.sql，以 ORM + init_db 为准）。
5. 验收：CI 全绿；`pytest` 在干净机器（无 .env）可直接跑通。

### Phase 4 — 安全补齐（约 1–2 天）
1. token 吊销：users 表加 `session_version`，登出/改密自增，HMAC 校验带版本。
2. OAuth state：一次性随机 state 存 short-TTL 缓存，回调校验。
3. CORS：生产 `.env` 显式设 `BRAINX_CORS_ALLOW_ORIGINS=https://reloop.yorkteam.cn`。
4. `/sync/ttc` 限流见 Phase 2.4；D-1 全局 Token 治理需用户拍板范围。

---

## 五、待用户拍板（不拍板不动）
1. **D-1**：全局共享 Token 允许任何登录用户拉全公司池——维持现状还是收紧白名单？
2. **webapp 产物入库**：改 gitignore + 部署时构建（推荐），还是维持现状并写入文档？
3. **活跃门禁阈值**：90 天不活跃是否合理？（影响推荐池大小）
4. **服务器 .env** 的 stepfun 三行由用户粘贴还是授权我 SSH 执行？

---

## 六、逐步要求、后果与排序依据

### 总排序三原则（为什么是这个顺序）
1. **止血 > 提效 > 还债 > 加锁**：重复数据和时间戳污染是**不可逆累积**的（每天导入都在变糟），必须最先停；同步提效（5→50）是业务目标第二位；工程债和安全债利息最低，靠后。
2. **依赖链决定先后**：唯一约束(F2)依赖指纹兜底(F1)先铺好、否则建约束后大量 INSERT 直接失败；IntegrityError 兜底(F4)依赖约束(F2)存在；增量同步(Phase 2)依赖去重键和可信时间戳；CI(Phase 3) 要等 Phase 2 表结构（sync_runs）稳定后再建，避免建两次。
3. **风险递增**：Phase 1 全是应用层小改、随时可回滚；越往后越涉及数据迁移、部署流程、安全策略——需要更多拍板和回滚预案，放后面给足确认时间。

---

### Phase 1 — 数据正确性

#### F1 source_id 指纹兜底
- **要求**：定死指纹字段组合（`name|phone|email|company|position` + owner）；明确指纹只是兜底——有真实 TTC id 时永远优先 id；接受"同人改手机号会生成新指纹"的边界情况（有 id 的记录不受影响）。
- **做的后果**：重复导入立即止血，改动仅 normalizer + client 两处，半小时级工作量，零迁移。
- **不做的后果**：每次导入继续膨胀表；池版本号频繁变化 → 推荐缓存反复失效 → 推荐结果闪烁；评分在重复人身上重复计算浪费 LLM。
- **排位原因**：止血优先、成本最低收益最大，且 F2 的前置。

#### F2 唯一约束 + 去重迁移
- **要求**：① 先跑"六、验证 SQL"确认重复规模；② **拍板保留策略**（推荐保留 id 最大=最新一次导入的行）；③ 迁移脚本必须幂等可重跑；④ 现网在低峰执行（会短暂锁表）；⑤ 先在本地 SQLite 全量跑一遍测试再碰 RDS。
- **做的后果**：数据库层兜底——从此任何应用层 bug 都不可能再造出重复，并发双同步也安全。这是一劳永逸的一步。
- **不做的后果**：F1 只是应用层防御，并发窗口和漏网路径仍会产脏数据；历史重复继续存在污染评分。
- **风险**：去重删除是**不可逆**的——必须先备份表（`CREATE TABLE talent_profiles_bak_2026xxxx AS SELECT...`）；人工改过 tags/contact_status 的旧行可能被当成重复删掉，所以保留策略要选"最新"。
- **排位原因**：必须在 F1 之后（否则建约束瞬间大量 INSERT 报错）、F4 之前（F4 依赖约束存在）。

#### F3 同步幂等锁
- **要求**：⚠️ 一个隐藏坑——生产 gunicorn 是 **4 worker 多进程**，纯线程锁只保护本进程，跨进程要用 DB 层 running 标记（recommend_runs 已有同款 stale 判定可复用其模式）。方案落地时应做成"DB running 行 + 进程内锁"双层。
- **做的后果**：前端双击/重试不再开出并行全量同步；LLM 费用不再×N。
- **不做的后果**：并发同步是重复数据的第二来源（绕过 F1 指纹，因为两个线程查重的间隙都在 INSERT），且是最贵的故障方式——直接烧 LLM 钱。
- **排位原因**：和 F1/F2 构成"止重复"闭环的最后一块；独立实现，不阻塞他人。

#### F4 IntegrityError 兜底
- **要求**：只捕获唯一冲突（IntegrityError），其他异常照常抛出——不能变成吞错误的 `except: pass`（那是本项目已有教训，talents.py:61）。
- **做的后果**：F2 建约束后，并发残存冲突自动降级为 UPDATE 而不是 500。
- **不做的后果**：F2 上线瞬间并发窗口内可能冒 500。
- **排位原因**：必须紧随 F2，是约束的配套安全网。

#### A2 去掉 created_at 兜底
- **要求**：产品决策——前端要能优雅展示"活跃度未知"（第三态），不能显示空白或 0 分造成"这人死了"的误读；配套 A4 的 unknown 分组。
- **做的后果**：一部分人才活跃度变 NULL——**这是有意的**：数据宁缺勿假。
- **不做的后果**：新导入记录永远伪装"刚活跃"，门禁（A4）无从谈起，整个活跃度体系持续失真。
- **排位原因**：活跃度重构的第一张多米诺，先让信号变真，后面的算法改造才有意义。

#### A3 删除批内相对归一化 + A5 窗口 180→90
- **要求**：① 现有测试断言可能依赖混合归一化的分数分布，需同步更新测试；② A3/A5 必须**联动上线**（只删相对项会把全员压到低分区，窗口同时收紧才能拉开区分度）；③ 做成可配置（`BRAINX_ACTIVITY_ABS_WINDOW` 已有雏形），便于线上不满意时回滚。
- **做的后果**：活跃分获得**真实语义**——0.8 就是"约 20 天前有动作"，跨池可比、跨时间稳定，不再随每次导入的批次重排。
- **不做的后果**：min-max 相对归一化每次导入都重造一次分布——"全员活跃"必然复发，这是失真的算法级放大器。
- **风险**：上线后首屏排序会**明显变化**（以前靠假分布撑起来的排序消失），要提前和用户对齐预期："排序变了才是修好了"。
- **排位原因**：依赖 A2 先把信号洗干净；是 A4 门禁的数值基础。

#### A4 活跃门禁（>90 天）
- **要求**：① **拍板阈值与动作**——推荐"先降权×0.1 观察一周 → 再收紧为直接排除"两步走，避免池子骤缩带来"怎么人变少了"的观感冲击；② 前端显示被门禁拦下的人数（"另有 N 人超过 90 天未活跃"），保持透明。
- **做的后果**：首屏真正浮上来的是"最近可联系"的人——这是用户要的"门禁"，直接改善推荐业务价值。
- **不做的后果**：即使 A2/A3/A5 修好，排序仍无硬性质量底线，僵尸人才靠匹配度仍可能挤进 Top3。
- **做错的后果**：阈值太紧（如 30 天）会把 378 人池子砍到几十人，推荐列表空荡——所以默认 90 + 降权缓冲 + 可配置。
- **排位原因**：放在活跃度链条最后，因为它消费前面所有改造的成果。

#### BUG-101 status 序列化
- **要求**：不只改新算路径——**缓存命中路径也要回填**（从 recommendations 表按 run_id 查一次状态映射），注意这次额外查询的成本（仅 TopN 条，可忽略）；缓存 JSON 结构变更要向后兼容旧缓存。
- **做的后果**：点"去联系"→刷新→状态保留，反馈闭环可信，"待确认"计数准确。
- **不做的后果**：用户每次刷新看到自己的操作被吞，会判定"功能是坏的"——这是当前最伤使用信任的 bug。
- **排位原因**：一行级改动、用户可感知收益最大，插在 Phase 1 顺手做掉。

#### BUG-103 跨天反馈 / BUG-105 删除级联
- **要求**：BUG-103 改为按"最近一次 run"定位而非 `recommend_date==today`，注意不要误伤更早历史 run 的状态；BUG-105 级联删除不可逆——删除接口加确认语义（前端二次确认即可），并同步清理 recommendations / recommend_runs 缓存（否则缓存还引用已删 talent_id）。
- **不做的后果**：103=昨日反馈静默丢；105=孤儿行累积 + 推荐/缓存引用悬空 talent_id（`_build_items` 里 `t is None: continue` 已经在为这种脏数据打补丁）。
- **排位原因**：与 101 同属反馈/数据一致性，一批做完一批测。

---

### Phase 2 — 同步链路后台化

#### 增量同步
- **要求**：**先验证 TTC 接口是否支持 `updated_after` 类参数**（拿真实 XHR 试一次）——支持则真增量；不支持则退化为"source_hash 全量比对跳过"（已实现，F1 后全覆盖），同样能把 10 分钟压到 ~1 分钟（省掉全部 LLM 调用，HTTP 拉取本身不慢）。
- **做的后果**：50 人/天场景下同步从"10 分钟阻塞级"变成"秒级常态操作"，这是 5→50 的**硬前提**。
- **不做的后果**：50 人/天 = 每天全量重拉 + 全池 LLM 精算，token 成本和时长都不可接受——目标直接不可达。
- **排位原因**：必须在 Phase 1 之后——增量同步在脏数据上跑等于"更快地生产重复数据"。

#### LLM 批量化
- **要求**：智谱 embedding-3 支持批量入参（已确认过接口形态）；批量大小与超时要配；失败要整批降级而不是整批报废。
- **后果**：embedding 调用次数从 N 降到 N/batch_size，成本与时长大降；contact_reason 已只算 TopN，无需动。
- **排位原因**：与增量同步共同构成成本可控的同步链路。

#### 进度落库（sync_runs 表）
- **要求**：新表 + `_ensure_columns`/init_db 迁移；进度更新频率节流（每 N 条写一次，别逐条 UPDATE）。
- **做的后果**：顺手修复一个**现在就存在的隐患**——`_SYNC_PROGRESS` 是进程内存字典，4 worker 下 `/sync/ttc/status` 只有开同步的那个 worker 能查到，其余 worker 返回 not_found（前端表现为进度条时灵时不灵）；worker 重启不再丢进度；同步历史可审计。
- **排位原因**：做完它，F3 的跨进程锁也有了落点（同一张表做 running 标记），一次迁移两用。

#### 限流
- **要求**：拍板最小间隔（建议 10 分钟/owner）；超出返回 429 + 上次成功时间，前端提示。
- **后果**：BUG-006（LLM 费用放大）正式关闭；代价是手动"强制刷新"场景要等——可加 force 参数给管理员。
- **排位原因**：同步后台化的最后一块拼图，依赖前面的幂等/增量都稳了再加限制，避免限制自己人。

---

### Phase 3 — 工程化

#### CI
- **要求**：⚠️ 与"不推 GitHub"的约定冲突——Actions 依赖 push。两条路：a) 用户恢复 push 后上 GitHub Actions（推荐）；b) 不 push 则本地 git pre-push/pre-commit hook 跑同样两条命令。conftest 显式补 `BRAINX_AUTH_REQUIRE_TOKEN=false`（BUG-302），保证干净机器可跑。
- **后果**：65 个现成测试从"我这次手动跑全绿"变成"每次改动自动把关"，回归不再靠人肉记忆。
- **排位原因**：等 Phase 2 的表结构（sync_runs）定稿后再建，一次到位；否则 CI 建两次。

#### 卫生清理（死拷贝/*.db/segno/死代码/schema 对齐）
- **要求**：每个死代码项先 grep 确认零调用再删（文档里已给清单）；schema.sql 建议直接废弃（以 ORM init_db 为唯一事实源），但删文件前要确认没有部署脚本引用它。
- **后果**：diff 变干净、新人不再被 `webapp.before-*` 和三个 LLM 厂商说法迷惑；`environment.yml` 补 segno 后换机器部署不再踩二维码 500。
- **排位原因**：低风险低收益，不阻塞任何业务，纯粹降长期摩擦。

#### webapp 产物 gitignore
- **要求**：**改部署流程**——服务器构建（需装 node）或本地构建后随 tar 上传；这是"待拍板"项的原因：改的是你熟悉的部署链路，不是代码。
- **后果**：git 历史不再每次前端改动都膨胀 ~2MB；代价是部署多一步 `npm run build`。
- **排位原因**：独立可做，放 Phase 3 是因为它需要你先拍板。

---

### Phase 4 — 安全

#### token 吊销 / OAuth state / CORS 收紧
- **要求**：token 吊销 = users 表加 `session_version` 列（`_ensure_columns` 自动迁移，零手工操作）；OAuth state 需要 short-TTL 存储——多 worker 下内存不可靠，落 DB 或复用现有表；CORS 生产改一行 .env（同源部署下其实可以大幅收紧甚至关闭跨域）。
- **后果**：登出真正生效（现在登出后 7 天内 token 仍是万能钥匙）；CSRF 面关闭；攻击面收窄。
- **不做的后果**：当前内测规模下风险敞口有限（这是它排最后的原因——**债的利息还没到**），但一旦对外给团队用，这三个都是必修。
- **排位原因**：技术独立性最强、不阻塞任何人，放最后；**唯一例外**：D-1 全局 Token 治理如果决定收紧，要提到 Phase 2 一起做（它直接影响同步链路设计）。

---

### 一句话版本
> **先让数据变真（Phase 1），再让流程变快（Phase 2），再让迭代变稳（Phase 3），最后让门变锁（Phase 4）。** 顺序错了的代价：先做 Phase 2 = 更快生产脏数据；先做 Phase 4 = 锁住一个数据失真的系统。
