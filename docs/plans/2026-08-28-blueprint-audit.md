# Reloop 架构升级蓝图 · 审计报告（v2，2026-08-28 20:40 更新）

> 日期：2026-08-28 ｜ 审计对象：`docs/plans/2026-08-28-architecture-upgrade-blueprint.md`
> 方法：蓝图逐条论断 × 本地代码实测 × 生产服务器实证（SSH 查 systemd + 进程树）
> **v2 更新**：批次 1（文档/R5/R4）、批次 2（R1/R2/token）均已上线并经独立复核，详见第六节执行日志；当前推进到批次 3（R6 sync_runs）。

---

## 一、总判定

**蓝图骨架设计（方案 A）与迁移路线（R1-R7）成立，可以开工；但风险矩阵的 #1 存在事实性错误，排期批次 1 相应缩短。**

- 生产实际运行的是 `uvicorn --workers 1`（单 worker），不是蓝图假设的"gunicorn 4 worker"。
- 因此"多 worker 进程内状态不一致"这条**当前不成立**，但它是一个**未文档化的隐性约束**——蓝图和运维文档都还写着 4 worker，未来任何人按旧文档把 worker 调回去，auto_login 404 / 进度条失灵 / 幂等锁失效会整套复发。
- 结论：R3 从"要做的事"变成"已完成 + 需文档化"，R6（sync_runs 落库）从"中期可选"升为"回多 worker 的必要前置护栏"。

## 二、逐条核验结果

| 蓝图论断 | 核验 | 证据 |
|---|---|---|
| engine.py 787 行单类 7 职责 | ✅ 属实 | 实测 787 行 |
| App.tsx 424 行 8 组件 | ✅ 属实 | 实测 424 行 |
| auto_login 进程内 `_sessions` | ✅ 属实 | 374 行，代码自注释"必须单 worker" |
| llm.py:388-396 分位校准（批内 min-max 映射 [0.1,0.9]） | ✅ 属实 | 逐行确认，M1 必要 |
| 死代码链 provider/check/capture（251 行） | ✅ 属实 | provider.py:24 引用 `settings.auth_token_ls_keys`，config.py 无此字段（调用即 AttributeError）；全仓仅 check.py 引用 provider，capture 无人引用 → **可安全删除** |
| FK 无 ondelete / feedback_logs 无 FK | ✅ 属实 | models.py:186,207 两处 FK 无 ondelete |
| 生产 4 worker（风险 #1 前提） | 🔴 **过时** | systemd ExecStart = `uvicorn ... --workers 1`；ps 确认无 gunicorn，服务 active |
| 基线 main = 0acda2a | ⚠️ 过时 | HEAD 已到 1ea156c（+2 commit：dedup 脚本修复、JD 解析修复） |
| 测试基线 42 Python | ⚠️ 内部不一致 | 蓝图 §5 写 42、§9 守则写 43，需统一实测口径 |

## 三、修正后风险矩阵（仅列变化项；v2 状态更新）

| # | 风险 | 原评级 | 修正 | v2 状态（2026-08-28 20:40） |
|---|---|---|---|---|
| 1 | 多 worker 状态不一致 | 🔴 20 | 🟡 9（潜伏约束） | ✅ **已解除**：README 写明单 worker 是正确性前提 + 扩 worker 前必须 R6；约束已文档化 |
| 3 | 同步费用放大 | 🔴 12 | 🔴 12 | ⏳ 开放 → 批次 3（增量+限流+批量 embedding）；当前 hash skip 已使内容不变时零 LLM（冒烟实证 539 人全跳过） |
| 2 | 匹配分批内校准 | 🔴 15 | 🔴 15 | ✅ **已清零**：R4 删除 + recommend_runs 缓存已清（生产库行数=0 实证） |
| 4 | 巨型文件盲改 | 🔴 12 | 🔴 12 | ✅ **已清零**：R1 engine 787→13 行壳（逐字节纯搬运 diff 实证）；R2 App.tsx 424→16 行纯路由 |
| 5 | 访客池 /sync/ttc 409 | 🟡 12 | 🟡 12 | 🟡 **功能已通**：`BRAINX_TTC_SHARED_AUTH_TOKEN` 已配置，shared 源直连 TTC 全池拉取 539 人实证；但当前与全局服务 token 同值，"专用只读"差异化待用户签出后仅换 .env 值 |
| 6 | 无 CI 回归靠人肉 | 🟡 9 | — | ⏳ 开放 → 批次 4（R7） |
| 7 | 安全四件套 | 🟡 8 | — | ⏳ 开放 → 批次 4 |
| 8 | 死代码链 | 🟡 6 | — | ✅ **已清零**：R5 删除 provider/check/capture（251 行）+ scoped_query + analyze_tendency + DEPRECATED 权重，grep 零残留 |

## 四、修正后排期（v2 执行状态）

> 决策沿用蓝图默认：方案 A ｜ 接受 M1 分数变化 ｜ R1→R7 顺序不变。

| 批次 | 内容 | 状态 |
|---|---|---|
| **批次 1（~1.5h）** | 补单 worker 文档（README:211-220）→ R5 死代码删除 → R4 删校准 + 清 recommend_runs 缓存 | ✅ 已上线并验证（commit `1f9d483` / `234cb2e` / `5664061`） |
| **批次 2（~1 天）** | R1 拆 engine.py → services+core；R2 拆 App.tsx → pages/；共享 token 配置 | ✅ 已上线并验证（commit `70fe1bd` / `b1de5f9`） |
| **批次 3（~2 天）** | R6 sync_runs 落库 + 增量同步 + 批量 embedding + 限流（=Phase 2 主体） | ⏳ **下一项，待开工** |
| **批次 4（~1 天）** | R7 CI + 安全四件套 + README 对齐 | ⏳ 待批次 3 后 |

每批次守则不变：全量测试绿 → tar 部署 → /health + 冒烟 → 单 commit 可 revert。
当前测试基线：**43 Python + 28 Node 全绿**（批次 2 后实测）。

## 五、待办收敛（v2：仅剩 1 项）

1. **专用只读 token 差异化**（低优先）：当前共享 token 与全局同值，功能正确；用户在 TTC 签出专用只读凭据后，仅需替换服务器 .env 的 `BRAINX_TTC_SHARED_AUTH_TOKEN` 值并重启（若专用 token 属不同 space，需一并补 shared space_id 配置项）。

## 六、执行日志（独立复核记录）

### 批次 1 复核（20:16-20:25）
- 3 commit 内容 diff 逐项确认；生产 20:13 部署 + 重启实证（auth 目录 mtime、llm.py M1 注释版、scoped_query=0）。
- recommend_runs 生产库 = 0（缓存已清）；测试 43+28 全绿；死代码引用仅剩历史文档（BUGS.md/CODE_REVIEW.md）。
- 顺带发现：服务器 venv 实为 Python 3.14（旧记录 3.11 已更正）；生产 DSN 属性名为 `sync_dsn`。

### 批次 2 复核（20:32-20:39）
- R1：`services/recommend_service.py` 与原 engine.py **diff 逐字节一致**（纯搬运实锤）；engine.py 13 行转发壳；core/{activity 158, matching 172, scoring 101} 落位；factors.py 门面 re-export 兼容旧路径。
- R2：App.tsx 16 行纯路由；pages/ 6 个 + components/ 2 个；两个字符串断言测试（auth-state/sidebar）diff 仅输入管道改动（单文件读取 → 8 文件组合源拼接），**断言正则一字未动**。
- 部署：服务器 services/core 就位、bundle `index-DwikBRYv.js` 生效、服务 active、/health 200、单 worker 保持。
- Token 冒烟独立复现：绕过应用层直接用共享 token 以 shared 源连 TTC 全池拉取 = **539 人**，与执行侧冒烟吻合；数据终态 dup_groups=0（talent_profiles 全库 3997，跨全 owner 口径）。
