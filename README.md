# Reloop - 私域人才触达优先级推荐

> **今天你最应该联系谁，以及为什么。**
> 从 TTC 私域人才库提取人才数据 → 标准结构化 → 统一人才画像库(RDS MySQL) →
> 用户设定当前岗位 → 实时触发引擎(粗筛+精算) → Top3 / Top10 / TopN 推荐列表。

外部接口只有三类：**TTC 私域人才库(数据源)**、**大模型(智谱 BigModel, OpenAI 兼容)**、**RDS MySQL(唯一数据库)**。

---

## 1. 运行环境

- Python 3.11（**conda 环境，不装进系统 Python**）
- 依赖：FastAPI / SQLAlchemy 2.0 / PyMySQL / pydantic-settings / httpx（见 `environment.yml`）
- 数据库：阿里云 RDS MySQL（唯一数据库；测试可用 SQLite 覆盖，不碰 RDS）
- 前后端合并部署：单进程 `uvicorn` 同时伺服 API 与前端静态文件（同源免 CORS），无需 Node

```bash
# 首次：创建并进入 conda 环境
conda env create -f environment.yml
conda activate reloop
# 依赖有更新时
conda env update -f environment.yml --prune
```

---

## 2. 本地如何跑（三步）

### 2.1 配置 `.env`

项目根目录 `.env`（已配好，关键项如下）：

```ini
# ① RDS MySQL —— 用外网地址；本地跑需在 RDS 控制台白名单放行本机公网 IP
BRAINX_MYSQL_HOST=ttc-rds-public-0707.mysql.rds.aliyuncs.com
BRAINX_MYSQL_DATABASE=reloop_app

# ② 大模型 —— 智谱 BigModel (OpenAI 兼容)
BRAINX_LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
BRAINX_LLM_API_KEY=<你的智谱 key>
BRAINX_LLM_MODEL=glm-4-flash              # 话术/结构化/岗位相似度
BRAINX_LLM_EMBEDDING_MODEL=embedding-3    # 2048 维真实向量

# ③ TTC 私域人才库(数据源)
BRAINX_TTC_TALENT_BASE_URL=https://gateway.ttcadvisory.com
BRAINX_TTC_TALENT_API_PATH=/api/private-talent/v1/all-talents
BRAINX_TTC_TALENT_AUTH_TOKEN=eyJ...       # 飞书登录态 JWT(约 2 个月有效)
```

> **RDS 白名单**：本地连不上 RDS 时，去阿里云 RDS 控制台 → 数据安全 → 白名单，
> 加入本机公网 IP（`curl ifconfig.me` 查）。
>
> **TTC Token 抓取**（过期后照此重抓）：浏览器打开人才库页面 → F12 → Network →
> Fetch/XHR → 刷新 → 点 `gateway.ttcadvisory.com/api/private-talent/.../talents?page=1` →
> Request Headers → 复制 `Authorization: Bearer eyJ...` 中 `Bearer ` 之后那串。

### 2.2 启动（自动建表 + 伺服前端）

```powershell
conda activate reloop
uvicorn reloop.main:app --reload --host 0.0.0.0 --port 8000
```

启动日志出现 `[startup] DB tables ready` + `serving webapp from .../webapp` 即就绪。

### 2.3 浏览器打开 <http://localhost:8000/>

- 前端默认 `mode=live`、同源调用，**直接看到 RDS 里已同步的 368 人真实数据**；
- 数据隔离键 `X-Owner-User-Id` 默认填了已同步数据的 open_id，开箱即用；
- 「今日」页设定岗位（如 *商业分析师* / *AI研发工程师*）→ 实时推荐 Top10。

首次/数据过期时重新同步（需 TTC Token）：

```powershell
$H = @{ "X-Owner-User-Id" = "ou_ff894386d0ca340dcc2f7bdc53c57a81" }
Invoke-RestMethod "http://localhost:8000/sync/ttc" -Method Post -Headers $H
# { ok: true, synced: 368, mode: "api" }
```

同步会为每个人才调用智谱 LLM 做画像结构化 + 生成真实 embedding（368 人约 10 分钟）。

---

## 3. 文件结构（按模块划分）

```
Reloop/
├── environment.yml            # conda 环境定义
├── requirements.txt           # pip 版依赖(备用)
├── .env                       # 接口配置(见 §2.1)
├── sql/schema.sql             # RDS MySQL 建表脚本(生产)
├── reloop/
│   ├── config.py              # 统一配置(BRAINX_ 前缀环境变量)
│   ├── main.py                # FastAPI 入口 + API 路由 + 伺服前端静态文件
│   ├── db/                    # 数据层(引擎/会话 + 6 张 ORM 表, 全部带 owner_user_id)
│   ├── modules/
│   │   ├── sync/              # TTC 拉取(client.py) + 字段归一化(normalizer.py)
│   │   ├── profile/           # LLM 服务(llm.py) + 画像结构化(structuring.py)
│   │   ├── scoring/           # 五因子(factors.py) + 加权乘法(priority.py)
│   │   └── recommend/         # 推荐引擎(粗筛+精算, engine.py)
│   ├── api/                   # HTTP 接口(同步/人才/岗位/推荐) + deps(数据隔离)
│   └── schemas/talent.py      # 请求/响应契约(前后端共用)
├── webapp/                    # 前端静态 SPA(零框架, 无需构建)
└── tests/                     # 全流程测试(见 §6)
```

---

## 4. 前端对接的接口

全部接口（除 `/health`、文档、静态资源）都需带请求头 **`X-Owner-User-Id`**（数据隔离键）。
自动文档：`GET /docs`（Swagger）。契约定义集中在 `reloop/schemas/talent.py`。

| 用途 | 方法 & 路径 | 关键参数 | 返回 / 说明 |
| --- | --- | --- | --- |
| 健康检查 | `GET /health` | — | `{status, app, env}` |
| 数据同步(接口拉取) | `POST /sync/ttc` | Header 隔离头 | `{ok, synced, mode}`（需 Token） |
| 数据同步(JSON 导入) | `POST /sync/ttc/ingest` | Body `{talents:[...]}` | 无需 Token，备用 |
| 人才列表/详情/删除 | `GET/DELETE /talents(/{id})` | `keyword?/limit?/offset?` | `TalentOut`，按 owner 隔离 |
| 记录互动 | `POST /talents/{id}/interaction` | `{interaction_type,count?}` | 影响历史关系+活跃度 |
| 设定岗位 | `POST /positions` | `{position_name, jd_text?}` | 同名旧岗位置失效 |
| 实时推荐 | `POST /recommend/compute` | Query `position_name?` | `{run_id, top3, top10, top_n}` |
| 最近一次推荐 | `GET /recommend/latest` | `limit?` | `{run_id, position, items[]}` |
| 用户反馈 | `POST /recommend/feedback` | `{talent_id, action}` | confirm/reject/correct |

**推荐条目字段**：`talent_id/name/company/position/score/score_breakdown(五因子)/contact_reason`。

---

## 5. 一条龙跑通（PowerShell）

```powershell
$H = @{ "X-Owner-User-Id" = "ou_ff894386d0ca340dcc2f7bdc53c57a81" }

# 1) 从 TTC 网关拉取真实人才库并入库(需 .env 已配 Token; 368 人约 10 分钟)
Invoke-RestMethod "http://localhost:8000/sync/ttc" -Method Post -Headers $H

# 2) 查看入库人才数量
(Invoke-RestMethod "http://localhost:8000/talents" -Headers $H).Count

# 3) 设定当前岗位(如 AI研发工程师)
Invoke-RestMethod "http://localhost:8000/positions" -Method Post -Headers $H `
  -ContentType "application/json" `
  -Body '{"position_name":"AI研发工程师","jd_text":"机器学习 大模型 Python 3年以上"}'

# 4) 实时推荐 Top3 / Top10 / TopN
$r = Invoke-RestMethod "http://localhost:8000/recommend/compute" -Method Post -Headers $H
"pool=$($r.total_pool) shortlisted=$($r.shortlisted)"
$r.top10 | ForEach-Object { "  #$($_.rank) $($_.name) | $($_.position) | score=$($_.score)" }
```

> 用 `Invoke-RestMethod`（PS 原生）而非 `curl`——PS 5.1 会吞掉 `curl -d '{...}'` 的 JSON 引号。

---

## 6. 如何测试

```bash
conda activate reloop
python tests/test_pipeline.py            # 全流程(SQLite 临时库 + LLM 离线, 不碰 RDS)
```

依次验证：**字段解析 → 标准格式 → 结构化入库 → 数据隔离 → 设岗 → 引擎计算 → TopN 排序 → 结果落库**。全部通过打印 `=== 全流程测试通过 ===`。

---

## 7. 推荐算法（v2, 2026-08 重构）

**8 环链路**：① TTC 取数 → ② 归一化 → ③ 画像结构化(LLM+价值分+向量) →
④ 落库 talent_profiles(按 owner 隔离) → ⑤ 用户设岗 → ⑥ 粗筛+五因子精算 →
⑦ 落库 recommendations → ⑧ 用户反馈。

**综合分 = 活跃度^0.3 × 岗位匹配^0.4 × 人才价值^0.15 × 历史关系^0.1 × 求职可能^0.05**
（权重 `.env` 的 `BRAINX_SCORE_W_*` 可调；乘法模型下任一关键因子趋 0 显著压低总分）。

### 活跃度（v2）

- **分事件半衰期冷却**：`Σ w·e^(-λ_t·days)`，λ_t = ln2/半衰期。
  平台活跃 14d / 档案更新 21d / 面试 30d / 通话·消息 45d——"正在看机会"信号衰减快，关系维护信号衰减慢。
- **绝对×相对混合归一化**：`0.4·绝对分(最近事件新近度, 180 天窗口) + 0.6·批内 min-max`。
  修复单人池退化、全员死池被强行拉开区分度两类失真。

### 岗位匹配度（v2，多维加权，缺失维度自动重归一）

| 维度 | 权重 | 算法 |
| --- | --- | --- |
| title 职位语义 | 0.25 | **LLM 批量推理岗位相似度**（"AI研发工程师" vs "算法工程师"≈0.7）；离线降级 bigram Dice |
| skill 技能覆盖 | 0.30 | JD 关键词被人才技能/标签覆盖比例（子串容错） |
| semantic 语义 | 0.35 | max(0, cosine(JD 向量, 简历向量))，智谱 embedding-3 |
| years 年限 | 0.05 | JD 抽"X年"要求，实际/要求线性衰减 |
| edu 学历 | 0.05 | JD 抽学历要求，差级衰减不硬杀 |

LLM 岗位相似度带**进程内缓存**（岗位不变时二次推荐零调用）。

### 降级策略（无外部凭据流程仍跑通）

- LLM 无 Key：结构化走纯规则抽取；embedding 用本地哈希向量；岗位相似度退化为字面 bigram。
- TTC 无 Token：跳过接口拉取，用「页面导出 JSON 导入」（`POST /sync/ttc/ingest`）。

---

## 8. 后续待办

- 前端接入登录态（替换 `reloop/api/deps.py::get_current_user` 解析 SSO，其余不动）。
- `BRAINX_SCORE_W_*` 权重按反馈调优；补「按人查互动 GET」与仪表盘聚合接口。
