# k3harness — K3 自研轻量 Agent Harness

替代 Claude Code 接 Kimi 的重型链路，直连 `api.kimi.com/coding/`（Anthropic Messages 协议）。
目标：同等任务成功率下 token 消耗降 ≥20%。

## 用法

```bash
cd k3harness
.venv/bin/python -m k3h.cli probe          # 探测端点能力
.venv/bin/python -m k3h.cli run "任务描述"  # 非交互执行（--mode dry-run|apply）
.venv/bin/python -m k3h.cli repl           # 交互 REPL
```

密钥从环境变量 `ANTHROPIC_AUTH_TOKEN` 或 `~/.claude/settings.json` 读取，不落代码。

## 省 token 设计

1. system prompt ~470 tokens + 工具 schema ~510 tokens（Claude Code >10k）
2. 工具结果截断：bash head4k+tail4k、read_file 默认 400 行、grep 100 条；bash 噪声命令自动走 rtk 包装
3. 每任务新 session + 120k 主动 compact（vs 生产配置 1M 硬撑）
4. dry-run→apply 三段式在工具层强制，不靠 prompt 自觉

## 基准评测

```bash
.venv/bin/python bench/run_bench.py --leg both --reps 3   # 10 任务 × 2 腿 × 3 次
.venv/bin/python bench/report.py                           # 生成 runs/bench_report.md
.venv/bin/python bench/baseline_from_transcripts.py        # 历史转录参考基线
```

- `bench/tasks.yaml`：10 个任务（覆盖 9 类高频画像），两腿逐字同 prompt
- `bench/fixtures/`：自包含可重放输入（gitignored，含脱敏真实素材）
- `bench/accept/`：确定性验收脚本（pristine 失败 / 好解通过，均已双向验证）
- 公平性：同模型（k3）、同 max_turns=30、fixture 副本隔离、每任务 3 次取中位数

## 结构

- `k3h/backends/` anthropic（默认）+ openai（备用，probe 显示 Kimi 端不可用）
- `k3h/tools/` read/write/edit/list/grep/glob/bash 七件套
- `k3h/meter.py` 每轮 usage 落 `runs/*.jsonl`，成本按 Moonshot 刊例价折算

## 自改进循环（autoresearch 范式）

harness 自身的迭代改进走机械化实验循环（灵感：uditgoenka/autoresearch）：

```bash
.venv/bin/python bench/iterate.py status                  # 实验历史与当前 best
.venv/bin/python bench/iterate.py run --desc "改动说明" --patch /tmp/x.diff
.venv/bin/python bench/evals.py                           # 趋势/平台期/停止建议
```

- `bench/goal.yaml`：Goal→Config——scope（可改 harness 本体）/ metric（T1,T3,T5,T8 快速子集 billable 中位和）/ guard（accept、fixtures、tasks.yaml 永不可改 + 全量通过率门槛）
- 纪律：每轮只改一处、先 commit 再 verify、改进 keep 变差 revert、TSV 日志 amend 进提交
- 噪声地板：单 rep 波动 ±15%，keep 决策只在 delta >20% 时可信（E2/E3/E4 均因落入噪声带被 revert）

### 首批迭代结果（2026-08-04）

基线 27,808 → E1 keep（bash 截断 4000→2500）→ 确认复测 22,243（**-20%**）；E2/E3/E4 revert；evals 判定参数微调已达平台期，后续改进应走结构性策略（prompt 结构、compact 触发、工具合并）。
