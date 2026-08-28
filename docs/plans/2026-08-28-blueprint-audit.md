# Reloop 架构升级蓝图 · 审计报告

> 日期：2026-08-28 ｜ 审计对象：`docs/plans/2026-08-28-architecture-upgrade-blueprint.md`
> 方法：蓝图逐条论断 × 本地代码实测 × 生产服务器实证（SSH 查 systemd + 进程树）

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

## 三、修正后风险矩阵（仅列变化项）

| # | 风险 | 原评级 | 修正 | 说明 |
|---|---|---|---|---|
| 1 | 多 worker 状态不一致 | 🔴 20 | 🟡 9（潜伏约束） | 单 worker 下当前正确，但约束未文档化，人一扩就复发 → 批次 1 补文档 + 注释，R6 落库后解除 |
| 3 | 同步费用放大 | 🔴 12 | 🔴 12 不变 | hash skip 已缓解内容不变场景，增量+限流仍要 R6 |
| 2 | 匹配分批内校准 | 🔴 15 | 🔴 15 不变 | R4 删除，需清 recommend_runs 缓存 |
| 4 | 巨型文件盲改 | 🔴 12 | 🔴 12 不变 | R1/R2 |
| 5 | 访客池 /sync/ttc 409 | 🟡 12 | 🟡 12 不变 | **唯一用户可感知阻塞项，等你一句话给 token 决策** |

## 四、修正后排期（锁定版 v2）

> 决策沿用蓝图默认：方案 A ｜ 接受 M1 分数变化 ｜ R1→R7 顺序不变。

| 批次 | 内容 | 变化 |
|---|---|---|
| **批次 1（今天，~1.5h）** | ~~R3~~（已完成，改为：README/systemd 文档写明"单 worker 是 auto_login/进度/锁的正确性前提"）→ R5 死代码删除 → R4 删分位校准 + 清 recommend_runs 缓存 | 缩短，因 R3 已 de facto 完成 |
| **批次 2（明天，~1 天）** | R1 拆 engine.py → services+core；R2 拆 App.tsx → pages/（纯搬运，测试断言禁改） | 不变 |
| **批次 3（后天，~2 天）** | R6 sync_runs 落库 + 增量同步 + 批量 embedding + 限流（=Phase 2 主体） | 不变，且优先级上调：它是回多 worker 的前提 |
| **批次 4（本周内，~1 天）** | R7 CI + 安全四件套 + README 对齐 | 不变 |

每批次守则不变：全量测试绿 → tar 部署 → /health + 冒烟 → 单 commit 可 revert。

## 五、待拍板（收敛为 2 项）

1. **访客池 token**（风险 #5）：`BRAINX_TTC_SHARED_AUTH_TOKEN` 用全局同值还是专用只读？——今天一句决策即可解除唯一的用户可感知阻塞。
2. **按修正后排期开工**：默认按 v2 执行，有异议指出即可。
