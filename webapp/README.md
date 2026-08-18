# Reloop 触达工作台 — 配套前端 (webapp/)

面向招聘顾问的移动端优先工作台，配套 Reloop FastAPI 推荐引擎。纯静态 SPA（无需构建），
严格对齐后端接口契约（`TalentOut` / `PositionOut` / `RecommendItemOut` 五因子 `score_breakdown` /
`FeedbackCreate` / `InteractionCreate`）。

## 页面
- **今日** — 岗位切换 + 概览数字 + 触达优先级列表；展开五因子雷达 / 因子条 / “为什么排这里” / 三键决策（去联系·跳过·修正）。
- **人才库** — 关键词搜索 + 列表 → 人才详情（画像 / 五因子 / 互动记录 / 记一次互动）。
- **岗位** — 设定/切换在招岗位（含 JD），设定后重新计算。
- **设置** — 中/英语言切换、数据来源开关。

## 运行
```bash
cd webapp && python3 -m http.server 3000
# 打开 http://localhost:3000
```

## 数据来源开关（样本 ↔ 真实 API）
默认跑贴合契约的**真实感样本数据**（预览可离线跑通）。切真实数据：
1. 后端上公网并开启 CORS（`fastapi.middleware.cors.CORSMiddleware`，放通前端域名）。
2. 前端 **设置** 页把「后端地址」填成 FastAPI 地址（如 `https://your-reloop.example.com`），
   「数据隔离键」填 `X-Owner-User-Id`（默认已填已同步 358 人的 open_id）。
3. 保存即切换，业务视图不动。

## 已知后端接口待办（见 App 内“设置 > 接口待办”）
CORS、`GET /talents` 分页/筛选、按人查互动的 GET、重算 embedding、仪表盘聚合、feedback 回包。

Eazo App ID: `ilXe3nSaLkbf3qE4`（品牌横幅已内置于 `index.html`）。
