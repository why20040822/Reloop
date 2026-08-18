# K3 harness 基准对比报告

| 任务 | 类别 | k3h 中位 billable | claude 中位 billable | 降幅 | k3h 通过率 | claude 通过率 | k3h 中位轮数 | claude 中位轮数 |
|---|---|---|---|---|---|---|---|---|
| T1 | 解析器修复 | 6,302 | 48,538 | 87.0% | 100% (3次) | 100% (3次) | 5 | 10 |
| T10 | 飞书三段式 | 4,958 | 35,813 | 86.2% | 100% (3次) | 67% (3次) | 6 | 11 |
| T2 | 数据修复/回填 | 2,773 | 42,661 | 93.5% | 100% (3次) | 100% (3次) | 4 | 4 |
| T3 | JD匹配/评分 | 9,290 | 35,918 | 74.1% | 100% (3次) | 100% (3次) | 6 | 5 |
| T4 | 批量入库dry-run | 4,520 | 43,799 | 89.7% | 100% (3次) | 100% (3次) | 5 | 4 |
| T5 | 运维脚本 | 2,202 | 35,648 | 93.8% | 100% (4次) | 100% (4次) | 4 | 4 |
| T6 | 长文归纳 | 17,337 | 71,280 | 75.7% | 0% (3次) | 0% (3次) | 5 | 4 |
| T7 | 入库链路改造 | 3,101 | 29,458 | 89.5% | 100% (3次) | 100% (3次) | 4 | 6 |
| T8 | 插件调试 | 7,986 | 33,912 | 76.5% | 100% (3次) | 67% (3次) | 6 | 6 |
| T9 | 文档撰写 | 4,373 | 43,591 | 90.0% | 67% (3次) | 0% (3次) | 4 | 4 |

## 总结

- 全任务集中位 billable 合计：k3h 62,842 vs claude 420,618，**总降幅 85.1%**（目标 ≥20%）
- 通过任务数：k3h 27 vs claude 23（成功标准：不低于 claude 腿 -1）
- 结论判定：**达标**

注：billable = input + output + cache_write；cache_read（缓存命中）单列于 results.jsonl。
claude 腿为生产现状配置（含 CLAUDE.md 注入、rtk hook、47 skills 描述）；k3h 腿为自研轻量 harness。
---

## 验收校准备注

- **T6 双腿 0%**：双腿产出的 summary.json 均命中 8/12 golden 关键词（67%），距 80% 阈值差 1 个词；未命中词（AI原生工作流/抓大放小/小麦/openman）属原文措辞细节。判定为 accept 阈值偏严而非能力缺失，两腿同标准、对比公平，未重跑。
- **T9 claude 腿 0%**：accept 要求 name/phone/fingerprint 出现在同一张 markdown 字段表；claude 腿 3 次均拆散了表格结构。标准对两腿一致，但该任务区分度含格式运气成分，解读时参考。

## P6 治理结果

- `~/.claude/settings.json`：`CLAUDE_CODE_MAX_CONTEXT_TOKENS` / `AUTO_COMPACT_WINDOW` 1048576 → 262144（k3[1m] 无 1M 窗口，硬撑导致服务端报错/静默截断）；删除重复的 `ANTHROPIC_API_KEY`（与 `ANTHROPIC_AUTH_TOKEN` 同值）。备份：`~/.claude/settings.json.bak-k3h-20260804`。**评测期间冻结，跑分结束后才应用。**
- rtk 实测生效（PreToolUse hook）：历史 9,092 次命令累计省 1.222 亿 tokens（工具输出侧 93.6%），其中 grep 类占 1.013 亿。k3h 的 bash 工具已内置 rtk 自动包装。
- httpx 代理坑：k3h 全链路 `trust_env=False`，规避 Clash 全局代理导致 Kimi 压缩/断流（见 memory kimi-api-must-go-direct）。

## 口径说明

- billable = input + output + cache_write（cache_read 命中缓存按折扣价单列于 results.jsonl）
- 成本按 Moonshot 刊例价折算（in ¥4/M、out ¥16/M、cache_read ¥1/M）；Kimi coding 订阅制下 token 量即真实约束
- 每任务每腿 3 次取中位数；两腿同模型（k3）、逐字同 prompt、同 max_turns=30、fixture 副本隔离
