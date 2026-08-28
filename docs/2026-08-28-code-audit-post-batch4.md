# Reloop 代码审计报告（批次 3/4 后 · 2026-08-28 21:41）

> 审计对象：`main` = `223713c`（origin/main 已同步，批次 3+4 均已推送）
> 方法：新提交逐 diff 审读 × 本地全量测试复跑 × 生产 SSH 实证（表结构/列/CORS/进程）

---

## 一、总判定

**批次 3/4 代码质量整体过关，生产已部署（20:50:43 重启），44 Python + 28 Node 全绿。蓝图 R1-R7 至此全部落地。** 残留 4 个低风险项，均不阻塞，已列修复建议。

## 二、批次 3 审读（`5a3a49e` 同步链路后台化）

### 通过项
| 检查点 | 结论 |
|---|---|
| sync_runs 表结构 | ✅ 与蓝图 §7.5 DDL 一致（owner/sync_id/status/进度字段 + `uq_sync_owner_sync` 唯一约束 + owner_status 索引），create_all 自动建表（生产实证表已存在） |
| 时区口径 | ✅ `_now()` = UTC naive，锁过期判断与限流判断同用 `now(utc).replace(tzinfo=None)`——与 BUG-102 教训一致，无时区错位 |
| 幂等双层锁 | ✅ L1 进程内 → L2 DB running 行（30min 僵死标记 failed 后放行）；DB 故障时降级纯内存锁不阻塞同步 |
| 进度跨进程 | ✅ L1 内存优先 → DB 回退；节流落库（每 25 条/收尾），终态 done/failed 均回写 DB |
| embedding 批量化 | ✅ 两段式：先分类跳过/更新/新增，再 embed_batch 一次一批，单批失败仅该批降级 |
| 限流 | ✅ 同 owner 两次成功同步最小间隔 600s（`BRAINX_SYNC_MIN_INTERVAL_SECONDS`），429 带等待秒数与解释文案；测试环境归零 |

### 残留项（低风险）
1. **L2 锁存在 TOCTOU 窗口**：跨 worker 的 SELECT→INSERT 之间可能双双插入 running 行（唯一约束是 owner+sync_id，挡不住同 owner 两行 running）。概率极低（L1 已挡同进程），回多 worker 后如观察到双跑，用 MySQL advisory lock 或唯一 partial 方案收敛。
2. **限流只计 done**：同步 failed 不占限流额度，持续失败时重试可反复触发 TTC 拉取 + 部分 LLM 消耗。建议后续把 failed 也计入（或单独失败冷却）。
3. **webapp 旧 bundle 残留**：服务器 assets 同时存在 `index-DwikBRYv.js`（批2）与 `index-Dz9Jx3Sy.js`（批4）——部署是 cp -rf 不清理。无功能影响，建议部署流程加"清理 assets 再拷贝"。

## 三、批次 4 审读（`223713c` 安全四件套 + CI）

### 通过项
| 检查点 | 结论 |
|---|---|
| token 吊销 | ✅ `users.session_version`（engine `_ensure_columns` 已自动 ALTER，生产实证列存在）；payload 带 `sv`；**三个鉴权依赖全部校验**（get_current_user / get_optional_user / require_authenticated_non_guest）；`POST /auth/logout` 自增吊销全部会话；旧 token（无 sv）按 0==0 兼容，存量会话不被强制下线 |
| OAuth state | ✅ `/auth/feishu/url` 每次生成 `secrets.token_urlsafe(16)` 随机 state，前端保存并在回调比对 |
| CORS | ✅ prod + `*` 启动告警；生产 .env 已实测收紧为 `https://reloop.yorkteam.cn,https://47.110.93.137` |
| CI | ✅ GitHub Actions 双 job（backend pytest + frontend tsc/test/build）；无 secrets 依赖；`package.json` 三个脚本（check:web/test:web/build:web）全部存在；限流/env 测试口径显式（BUG-302） |

### 残留项（低风险）
4. **OAuth state 仅前端校验**：服务端 `/auth/feishu/login` 交换 token 时不验证 state，CSRF 防护依赖前端比对（攻击者无法写受害者 localStorage，防护实际有效，但比服务端校验弱一档）。建议 Phase 2 把 state 存短期 DB/缓存并在服务端校验一次性消费。

## 四、蓝图 §5 验收标准对照（终态）

| 验收项 | 状态 |
|---|---|
| 测试全绿 | ✅ 44 + 28（本地复跑） |
| 任意 worker 行为一致 | ✅ 进度/锁/会话状态已落 DB（sync_runs + session_version） |
| engine < 50 行 / App < 80 行 | ✅ 13 行 / 16 行 |
| core/ 零 IO import | ✅ 仅 datetime/math/typing + config（读配置非 IO） |
| 文档与实际一致 | ✅ README API 速查 25 条 + 单 worker 硬约束章节 |

**与蓝图目标骨架的已知差距（过渡态，非缺陷）**：services/ 目前只有 recommend_service 1 个文件；sync 编排落在 `modules/sync/client.py`（TalentSyncService）而非蓝图规划的 services/sync_service.py；talents.py 路由内仍有访客自动同步逻辑。功能与正确性均达标，属"目标架构未走完全程"，建议作为 Phase 3 拆分 余项而非新开工项。

## 五、工程卫生（存量遗留）

- `test_local.db` 仍在 git 追踪中，`.gitignore` 缺 `*.db`（多次审核提过，仍未处理——1 行修复）。
- 服务器 .env 的 CORS 含裸 IP `https://47.110.93.137`（该源无有效证书，实际用不到，可删）。
- 批次 1-4 共 7 个 commit 已推送 GitHub；推送前密钥扫描约定已在执行（`a3206cb` 记录）。

## 六、风险水位（对比审计 v2）

| 项 | v2 状态 | 现在 |
|---|---|---|
| #1 多 worker 状态不一致 | 🟡 潜伏约束 | ✅ **解除**（sync_runs + session_version 落库，文档化约束） |
| #3 同步费用放大 | 🔴 12 | 🟢 **大幅缓解**（增量分类 + 批量 embedding + 600s 限流；实测内容不变零 LLM） |
| #5 访客池 409 | 🟡 功能已通 | 🟢 同上（专用只读差异化仍待凭据，低优先） |
| #6 无 CI | 🟡 9 | ✅ **解除**（GitHub Actions，推 main/PR 自动跑） |
| #7 安全四件套 | 🟡 8 | ✅ 基本解除（残留 state 服务端校验一条，见上） |

**结论：审计 v2 中的 4 红 3 黄，现在全部收敛为绿灯 + 4 条低风险残留（TOCTOU / 限流不计失败 / state 服务端校验 / *.db 卫生）。5→50 简历/天的同步链路改造完成。**
