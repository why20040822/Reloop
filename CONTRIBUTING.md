# 贡献指南 / 代码变更流程

> 依据《Hayden.md 第六部分：代码变更流程》制定。目的：**避免直接破坏线上**。
> 协作者：Hayden（文档负责人）、Iris（@cdfyyds-ctrl）、Otto（@jiands233，前端）、Mia（@zhongxiaomi06-sudo）

## 变更流程（必须按顺序）

1. **拉取最新代码**：`git pull origin main`（本地 `.env` 不动，永不被覆盖）
2. **开分支**：`git checkout -b <type>/<topic>`，type ∈ `feat / fix / chore / docs / refactor`
3. **本地修改 + 自测通过**（见下方"自测清单"，全绿才允许提交 PR）
4. **推到分支并开 PR**：`git push origin <branch>` → GitHub 开 PR 到 `main`，描述写清：变更点 / 自测结果 / 是否涉及配置或数据库变更
5. **部分协作者同意**后，PR 合入 `main`
6. **全体协作者（Hayden / Iris / Otto / Mia）同意后**，才允许部署到云服务器 `47.110.93.137`

⛔ 禁止：直接 push 到 `main`、未自测开 PR、未全员同意就部署。

## 自测清单（PR 前必跑）

```bash
python tests/test_pipeline.py        # 端到端: 同步→结构化→引擎→缓存→API smoke
python tests/test_sync_pipeline.py   # 真实同步路径: HTTP ingest→真落库→推荐区分→反馈
pytest tests/ -q                     # 单元/契约测试(忽略上述两个独立脚本即可)
```

测试使用 SQLite + LLM 离线降级，**无需任何凭据**；不依赖本机 `.env`。

## 敏感信息红线

- 凭据只走 `.env`（`BRAINX_` 前缀），**任何账号/密码/Token/AccessKey 禁止写入代码、文档、测试**。
- 团队私密文档（含凭据）放 `hanyu接下来的文档/`（已 gitignore），**禁止提交、禁止外发**。
- 发现凭据泄漏：先轮换，再清理（git 历史脱密用 filter-repo），最后复盘。
- GitHub 已开 Push Protection，含密钥的 push 会被直接拒绝——不要点 "allow secret"，先检查是不是误提交。

## 部署（仅维护者执行，全员同意后）

- 服务器：阿里云 ECS `47.110.93.137`，代码 `/opt/reloop`，服务 `systemctl reloop`，公网入口 `https://reloop.yorkteam.cn`。
- 原则：**服务器 `.env` 永不被覆盖**（部署前自动备份 `.env.bak.<ts>`）；切换前快照代码目录可秒回滚。
- 部署后必验：`/health` 返回 `env=prod`、公网 HTTPS 200、前端可加载、真实接口有数据。
- 详细步骤见 README「云端部署」一节。
