# Reloop 审计轮次记录（2026-08-03）

本记录只统计开发提交 `627603a` 之后、针对该基线启动的正式只读审计。审计 agent 均未访问真实 RDS、飞书或 Gmail，未修改仓库文件；工作树中的其他未提交改动不视为本次开发结果。

| 轮次 | Agent | 关注面 | 主要结论 | 本轮处理 |
|---:|---|---|---|---|
| 1 | `019fc702-3615-7321-8d8f-921e575cba4e` | 架构与旁路 | legacy API、one-off 写入绕过 outbox；双 daemon 与共享文件加载 | legacy 入库补 outbox；one-off 改为排队；保留双 daemon 为发布限制 |
| 2 | `019fc702-36a7-7983-90f2-e770bfeed8be` | outbox 状态机 | Feishu/RDS 崩溃窗口、查重失败、review fingerprint、日志不同步 | 增加 Feishu reconcile、canonical fingerprint、lease fencing、worker 日志镜像 |
| 3 | `019fc702-37f2-7093-9913-6dfd2cfe2ee9` | RDS 与凭据 | RDS schema 唯一键缺证据、旧链路直接 RDS、凭据/错误响应泄露风险 | 增加 RDS migration、补 phone/email；凭据轮换与旧链路隔离仍需运维动作 |
| 4 | `019fc702-38e1-7c02-849e-136a7c8b3b0c` | API/安全 | API 无鉴权、SSRF、任意文件路径、health 路径泄露 | 增加可配置 Bearer 鉴权、CORS allowlist、DNS/IP/逐跳重定向校验、文件根限制、health 脱敏 |
| 5 | `019fc702-3b31-7b21-843d-a8bc79f52118` | 最小验收/测试 | 默认 pytest 收集、干净 SQLite bootstrap、测试数量与 handoff 基线不一致 | 补充当前测试/命令证据；基线数量差异与缺失 fixture 保留为限制 |
| 6 | `019fc702-3a27-7fe2-b2cd-783c9e01d076` | 脚本/部署 | worker/daemon 入口、check_env 路径、README 漂移、one-off 命名 | 修复 module 入口、check_env、核心文档路径；日期前缀与历史 daemon 仍是限制 |
| 7 | `019fc711-721f-7532-97e7-6166442dc9b3` | API 安全复审 | owner/visibility 仍缺失；TTC daemon 另有 SSRF/鉴权/CORS 风险 | Reloop 鉴权与输入边界已加强；对象级多租户和 TTC daemon 统一鉴权未宣称完成 |
| 8 | `019fc711-72b0-7b81-92e6-b1b7aa2be5f3` | 故障注入复审 | lease 无 fencing、崩溃会重复外部副作用、RDS 身份字段丢失 | 增加 lease token、Feishu 查询对账、RDS phone/email、失败脱敏与状态镜像 |
| 9 | `019fc711-7369-74b2-965c-38207ab37f2b` | 启动/打包复审 | worker wrapper、uvicorn 依赖、daemon module 入口、dry-run 远程 mkdir | 增加 `reloop-worker` 与 uvicorn 依赖，修复 daemon/Docker/systemd/module 入口，dry-run 跳过 SSH mkdir |
| 10 | `019fc711-7434-7a30-82ce-e87931b81606` | 最终验收/clean HEAD | clean HEAD 发现共享 LLM 缺失 `complete_with_image`；测试/fixture/文档仍有证据缺口 | shim 改为兼容旧 shared client；当前全量 Reloop 回归 82 passed；真实外部投递与生产设计门禁仍未证明 |

## 当前验证边界

- 已验证：`reloop/tests` 本地回归、Reloop 包 ruff、Python/JS/shell 静态检查、fake sink 故障注入、临时 SQLite 状态机。
- 未验证：真实 RDS schema 已应用 migration、真实飞书字段映射与幂等行为、Gmail 生产同步、公网反向代理、TTC daemon 旧链路下线。
- 交接文档引用的 `2026-08-03-reloop-production-design.md` 与 `2026-08-03-reloop-mvp-design.md` 当前未在 Desktop 或仓库 `docs/plans/` 找到，因此 6 条生产上线门禁不能标记为已签字。
