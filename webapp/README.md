# Reloop 触达工作台 — 配套前端 (webapp/)

面向招聘顾问的移动端优先工作台，严格对齐后端接口契约（`TalentOut` / `PositionOut` /
`RecommendItemOut` 五因子 `score_breakdown` / `FeedbackCreate` / `InteractionCreate`）。
纯静态 SPA（零框架、无需构建）。

## 合并部署（推荐）

后端 `reloop/main.py` 通过 `uvicorn` 直接伺服本目录（`BRAINX_SERVE_WEBAPP=true`，同源免 CORS）。
一条命令起前后端：

```bash
conda activate reloop
uvicorn reloop.main:app --reload --host 0.0.0.0 --port 8000
# 打开 http://localhost:8000/
```

前端默认 `mode=live` 且「后端地址」留空 → **同源调用**后端 API，开箱即用，无需配地址/CORS。
在「设置」页可切 `mock`（内置样本离线演示）或填外部后端地址走远程（远程需在后端
`BRAINX_CORS_ALLOW_ORIGINS` 放通该域名）。详见根目录 `README.md`。

## 页面

- **今日** — 岗位切换 + 概览数字 + 触达优先级列表；展开五因子雷达 / 因子条 / “为什么排这里” / 三键决策（去联系·跳过·修正）。
- **人才库** — 关键词搜索 + 列表 → 人才详情（画像 / 五因子 / 互动记录 / 记一次互动）。
- **岗位** — 设定/切换在招岗位（含 JD），设定后重新计算。
- **设置** — 中/英语言、数据模式（真实 API / 样本）、可选后端地址、数据隔离键。

## 纯前端离线预览（可选，不参与合并部署）

仅用于不启后端、单独设计/调试 UI（mock 样本）：

```bash
npm run dev     # = node server.js，默认端口 3000 → http://localhost:3000
```

Eazo App ID: `ilXe3nSaLkbf3qE4`（品牌横幅已内置于 `index.html`）。
