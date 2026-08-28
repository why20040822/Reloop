# Reloop 迭代版本留痕（2026-08-29 收口）

> 原则：主功能不动，架构升级与维护优先；每版发布前 = 密钥扫描 + 多轮测试 + 三方对齐（本地 = GitHub = 服务器）。

## 版本台账

| 版本 | 提交 | 内容 | 状态 |
|---|---|---|---|
| v2.0 | `53b265c` + `1b9b7ec` | 断桥修复（jd_analysis 接入匹配链路、skill 覆盖率+命中清单、cosine 失配防护）+ 算法护栏（v2 默认 + 结构自检 + 自动回退 v1 + `BRAINX_MATCH_ALGO_V2` 手动开关） | ✅ 已上线（08-28 23:35，生产冒烟通过） |
| v2.1（基建） | `ce053a2` | 向量真实化基建：独立 embed 端点（`BRAINX_LLM_EMBED_*`，chat 与 embedding 可分属厂商）、`embed_with_source` 来源标记（real/hash）、`embedding_source` 落库列、`scripts/recompute_embeddings.py` 双侧重算脚本（dry-run/离线拒跑） | ✅ 已上线（08-29 00:10） |
| v2.1（功能） | `58afb9d` | 公司人才库补充：只读实时拉共享池（30min TTL 快照）+ 撞库查询（contact_exact→name→fuzzy→semantic 四层置信度）+ TalentDetail 差异面板；新端点 `GET /talents/{id}/company-supplement`，异常返回 `found=false` 不抛 500 | ✅ 已上线（08-29 00:10） |

- 标签：`v2.1.0`（已推送 GitHub）
- 测试基线：**67 Python + 28 Node，3 轮复跑全绿**（含护栏 4 用例、改造② 5 用例、公司库补充 5 用例）
- 三方对齐：本地 `c313047` = GitHub `main` = 服务器 `/opt/reloop`（同 bundle `index-hViDo4K6.js`，health ok，工作区零漂移）

## 08-29 收口动作（纯维护，零功能变更）

1. 工作区未提交的 v2.1 功能代码审查后收口提交（纯新增只读端点 + 异常兜底，不动旧路由/评分链路）
2. 密钥扫描（origin/main..HEAD 全量 diff）：0 硬编码密钥、无凭据文件 → 推送
3. `scripts/deploy.sh` 标准部署：health ok、新 bundle 上线、AppleDouble 0、`embedding_source` 列自动建成（positions + talent_profiles）
4. 服务器 LLM chat 通道实测恢复：`.env` 已是 `step_plan/v1`，部署重启后 `_chat_online=True`（此前 404 为旧进程未重启所致）
5. 建立每日三方一致性定时巡检（只读校验，不自动修复）

## 下一版本计划（v2.2，待用户拍板）

| # | 事项 | 依赖 | 预估 |
|---|---|---|---|
| 1 | **改造②执行**：服务器/本地配置 BigModel embedding key（`BRAINX_LLM_EMBED_*`）→ `recompute_embeddings.py` 重算存量 539 人哈希向量 + jd 向量（双侧同步，防 2048/256 失配）→ 清 recommend_runs 缓存 | 需用户提供 BigModel key | ~0.5h（脚本已备） |
| 2 | 验收口径落实：人工 Top5 ∈ 算法 Top10；skill 命中项可列举；`embed_source=hash` 占比 < 10% | 依赖 #1 | 抽样验证 |
| 3 | 安全 backlog：BUG-003 token 无吊销 / BUG-004 OAuth state / BUG-005 CORS * / BUG-006 sync 限流 | 无 | ~1 天 |
| 4 | Phase 2 同步后台化（R6 sync_runs 落库，扩 worker 前置条件） | 无 | 另行排期 |

## 护栏速查（运维）

- 一键回退旧算法：服务器 `.env` 加 `BRAINX_MATCH_ALGO_V2=False` → `systemctl restart reloop`
- v2 结果特征：`match_detail.source` = `llm_struct_mix`（LLM 主通道）| `struct_fallback`（LLM 离线降级）| `struct_prefilter`（初筛）；v1 回退结果**无** `match_detail`
- 重算向量：`python scripts/recompute_embeddings.py --dry-run` 先看影响面，确认后去掉 dry-run
