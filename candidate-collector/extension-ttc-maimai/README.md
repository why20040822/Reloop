# TTC/脉脉自动导入插件（jiands 版，存档）

来源：`jiands233/ttc-ai-recruiting-workflow` 分支 `feature/merge-talentmatch`（2026-08-04 合并时存档）。

与 `candidate-collector/extension/`（本地 Plasmo 构建的「ot小插件」v4.8.0，BOSS/猎聘/脉脉 + 云端直写）是**两个不同需求的插件**，并行保留：

- 本插件 v0.7.3：TTC 人才库 + 脉脉的**网络拦截自动导入**（content/network_interceptor.js 在 MAIN world 拦截 API 响应），
  服务端走 `candidate-collector` 8765 的 `/api/import-browser-capture-v2`（multipart 上传 PDF 原件）。
- 安装：Chrome → 扩展程序 → 开发者模式 → 加载已解压扩展，选择本目录。
- 注意：manifest 的 host_permissions 仅 `http://127.0.0.1:8765` / `http://localhost:8765`。
