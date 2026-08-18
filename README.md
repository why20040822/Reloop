# Reloop - 私域人才触达优先级推荐

> **今天你最应该联系谁，以及为什么。**>   
> 从 TTC 私域人才库提取人才数据 → 标准结构化 → 统一人才画像库(RDS MySQL) →>   
> 用户设定当前岗位 → 实时触发引擎(粗筛+精算) → Top3 / Top10 / TopN 推荐列表。

外部接口只有三类：**TTC 私域人才库(数据源)**、**大模型(OpenAI 兼容通用接口)**、**RDS MySQL(唯一数据库)**。  
已移除：阿里云 OSS、外部活跃信号(飞书等)、定时推送。

---

## 0. 前后端合并部署（本次变更）

> 原架构是「前后端分离」：前端 `webapp/` 由 Node 预览服务器(`server.js`)伺服在 3000 端口，>   
> 后端 FastAPI 由 `uvicorn` 伺服在 8000 端口，靠 CORS 跨域。>   
> **现已合并为单进程**：`uvicorn` 同时伺服 API 与前端静态文件（同源，免 CORS）。

```
                ┌──────────────────────────────────────────────┐
   浏览器 ──────►│  uvicorn reloop.main:app  (单进程, 端口 8000)  │
                │     ├─ /            → webapp/index.html (SPA)   │
                │     ├─ /styles.css  /app.js /data/* /i18n.js   │
                │     ├─ /health  /docs  /openapi.json           │
                │     └─ /sync /talents /positions /recommend     │──SQL──► RDS MySQL
                └──────────────────────────────────────────────┘        (或 SQLite 测试)
                                     │
                               TTC 网关 / 大模型 (可选, 配置驱动)
```

- **一条命令起前后端**：`uvicorn reloop.main:app --host 0.0.0.0 --port 8000`
- 前端默认 `mode=live` 且 `apiBase` 留空 → **同源调用后端**，无需任何跨域 / 地址配置。
- 仍可在「设置」页切回 `mock`（内置样本，纯离线演示），或填外部后端地址走远程。
- 旧 `server.js` 预览服务器保留为「纯前端离线设计」用途（见 §7），生产/日常用合并部署即可。

---

## 1. 运行环境

- Python 3.11（**conda 环境，不装进系统 Python**）
- 依赖：FastAPI / SQLAlchemy 2.0 / PyMySQL / pydantic-settings / httpx（见 `environment.yml`）
- 数据库：阿里云 RDS MySQL（唯一数据库；测试可用 SQLite 覆盖，不碰 RDS）
- Node.js（仅旧版纯前端预览 `server.js` 需要，合并部署不需要）

```bash
# 首次：创建并进入 conda 环境
conda env create -f environment.yml
conda activate reloop
# 依赖有更新时
conda env update -f environment.yml --prune
```

配置：`cp .env.example .env`，填 `BRAINX_MYSQL_HOST`（RDS 地址）即可；  
大模型 / TTC 登录态不填时自动降级（见下），框架可独立运行。

---

## 2. 文件结构（按模块划分）

```
Reloop/
├── environment.yml            # conda 环境定义
├── requirements.txt           # pip 版依赖(备用)
├── .env.example               # 全部接口配置(复制为 .env)
├── sql/schema.sql             # RDS MySQL 建表脚本(生产)
├── server.js                  # 旧版纯前端预览服务器(Node 零依赖, 可选)
├── package.json               # 前端脚本(dev/start = node server.js)
├── reloop/
│   ├── config.py              # 统一配置(BRAINX_ 前缀环境变量 + 前端托管开关)
│   ├── main.py                # FastAPI 入口 + 挂载 API 路由 + 伺服前端静态文件
│   ├── db/                    # 数据层(引擎/会话 + 6 张 ORM 表, 全部带 owner_user_id)
│   ├── modules/               # 业务: sync / profile / scoring / recommend
│   ├── api/                   # HTTP 接口(同步/人才/岗位/推荐) + deps(数据隔离)
│   ├── schemas/talent.py      # 请求/响应契约(前后端共用)
│   └── utils/isolation.py     # 数据隔离(查询过滤 + 越权校验)
├── webapp/                    # 前端静态 SPA(零框架, 无需构建)
│   ├── index.html  app.js  styles.css  i18n.js
│   └── data/                  # provider.js(可切换数据层) + mock.js(样本)
└── tests/                     # 全流程测试(见 §6)
```

---

## 3. 如何运行（合并部署 · 一条命令）

### 3.1 准备环境（首次）

```powershell
conda env create -f environment.yml   # 首次
conda activate reloop
copy .env.example .env                # 复制模板, 再按 3.3 填真实凭据
```

### 3.2 启动（自动建表 + 伺服前端）

```powershell
uvicorn reloop.main:app --reload --host 0.0.0.0 --port 8000
# 前端:   http://localhost:8000/
# 接口文档: http://localhost:8000/docs
```

启动日志出现 `[startup] DB tables ready` + `serving webapp from .../webapp` 即就绪。  
（若 RDS 没连上，会看到 `init_db skipped`，API 仍启动但写库失败；前端照常可打开。）

> 浏览器打开 **<http://localhost:8000/>** 即进入工作台；默认 `mode=live`、同源调用，>   
> 数据隔离键 `X-Owner-User-Id` 默认填了已同步 358 人的 open_id，开箱即用。

### 3.3 关键配置（.env）

三个外部接口各一处必填，其余默认即可：

```ini
# ① RDS MySQL —— 控制台「数据库连接」申请【外网地址】(内网地址本地连不上),
#    并在白名单放通本机公网 IP。用独立库 reloop_app(共库会撞 recommendations 表名)
BRAINX_MYSQL_HOST=ttc-rds-public-0707.mysql.rds.aliyuncs.com
BRAINX_MYSQL_DATABASE=reloop_app
BRAINX_DATABASE_URL=                         # 留空=用上面 MySQL; 本地无 RDS 时填 sqlite:///./reloop_dev.db

# ② TTC 人才库 —— 接口网关是 gateway 子域(不是 app 子域!)
BRAINX_TTC_TALENT_BASE_URL=https://gateway.ttcadvisory.com
BRAINX_TTC_TALENT_API_PATH=/api/private-talent/v1/all-talents
BRAINX_TTC_TALENT_AUTH_TOKEN=eyJ...         # 飞书登录态 JWT(约 2 个月有效)

# ③ 大模型(可选) —— OpenAI 兼容; 不填/填错自动降级(哈希向量+模板话术), 流程仍跑通
BRAINX_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
BRAINX_LLM_API_KEY=
```

TTC Token 抓取（过期后照此重抓）：浏览器打开人才库页面 → F12 → **Network** → 筛选 **Fetch/XHR** →  
刷新 → 点 `gateway.ttcadvisory.com/api/private-talent/.../talents?page=1` 请求 →  
**Request Headers → `Authorization: Bearer eyJhb...`** → 复制 `Bearer ` 之后那串填入 `BRAINX_TTC_TALENT_AUTH_TOKEN`。  
（认准 `gateway.ttcadvisory.com`；大量 `apmplus.volces.com` 是前端监控埋点，勿复制。）

### 3.4 前端托管相关配置（一般不用动）

```ini
BRAINX_SERVE_WEBAPP=true        # true=后端伺服 webapp/ 静态前端; false=只跑 API(另起前端)
BRAINX_WEBAPP_DIR=               # 留空=自动取项目根下 webapp/; 也可填绝对路径覆盖
```

---

## 4. 前端需要对接哪些接口

> 前端 `webapp/data/provider.js` 只认这一层 `api`，按契约调用以下后端接口。>   
> 全部接口（除 `/health`、文档、静态资源）都需带请求头 **`X-Owner-User-Id`**（数据隔离键）。

| #  | 用途            | 方法 & 路径                          | 关键参数                                                                    | 返回 / 说明                                                                                                                                          |
| -- | ------------- | -------------------------------- | ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1  | 健康检查          | `GET /health`                    | —                                                                       | `{status, app, env}`（无需隔离头）                                                                                                                      |
| 2  | 数据同步（接口拉取）    | `POST /sync/ttc`                 | Header: `X-Owner-User-Id`                                               | `{ok, synced, mode:"api"}`（需 .env 配 TTC Token）                                                                                                   |
| 3  | 数据同步（JSON 导入） | `POST /sync/ttc/ingest`          | Body: `{"talents":[...]}`                                               | `{ok, synced, mode:"ingest"}`（无需 Token，开发期备用）                                                                                                    |
| 4  | 人才列表          | `GET /talents`                   | Query: `keyword?` `limit?` `offset?`                                    | `TalentOut[]`（按 owner 隔离，可分页/搜索）                                                                                                                 |
| 5  | 人才详情          | `GET /talents/{id}`              | Path: `id`                                                              | `TalentOut`                                                                                                                                      |
| 6  | 删除人才          | `DELETE /talents/{id}`           | Path: `id`                                                              | `{ok:true}`                                                                                                                                      |
| 7  | 记录互动          | `POST /talents/{id}/interaction` | Path:`id`; Body:`{interaction_type,count?,summary?,occurred_at?}`       | `{ok:true}`（影响历史关系+活跃度）                                                                                                                          |
| 8  | 设定岗位（触发引擎）    | `POST /positions`                | Body:`{position_name, jd_text?}`                                        | `PositionOut`（同名旧岗位置失效）                                                                                                                          |
| 9  | 列出生效岗位        | `GET /positions`                 | —                                                                       | `PositionOut[]`                                                                                                                                  |
| 10 | 实时推荐          | `POST /recommend/compute`        | Query:`position_name?`（缺省用当前生效岗）                                        | `{run_id,position,total_pool,shortlisted,top3,top10,top_n}`；条目含 `talent_id/name/company/base_location/score/score_breakdown(五因子)/contact_reason` |
| 11 | 最近一次推荐        | `GET /recommend/latest`          | Query:`limit?`                                                          | `{run_id,position,items[]}`                                                                                                                      |
| 12 | 用户反馈          | `POST /recommend/feedback`       | Body:`{talent_id,action:confirm\|reject\|correct,corrected_tag?,note?}` | `{ok:true}`（写 feedback_logs，confirm/reject 同步更新推荐状态）                                                                                             |

自动文档：`GET /docs`（Swagger）、`GET /openapi.json`（可据此生成前端 client）。  
契约定义集中在 `reloop/schemas/talent.py`（`TalentOut` / `PositionOut` / `RecommendItemOut` / `FeedbackCreate` / `InteractionCreate`）。

**字段说明（前端渲染用）**

- `score_breakdown`：`{activity, match, value, relationship, tendency}` 五个 [0,1] 因子 → 雷达图 / 因子条。
- `score`：综合触达优先级（加权乘法模型）；`contact_reason`：联系话术。
- `status`：`pending` / `confirmed` / `rejected`（反馈后回写）。

**已知后端接口缺口（前端暂以本地态兜底）**

- 无「按人查互动」的 `GET` 接口（live 下人才详情互动列表为空，仅能「记一次互动」）。
- 无重算 embedding / 仪表盘聚合接口；`feedback` 不回包更新后的条目（前端本地维护状态）。

---

## 5. 一条龙跑通（PowerShell）

所有接口带请求头 `X-Owner-User-Id` 做数据隔离（开发期任意字符串；下例用已同步 358 人的 open_id）：

```powershell
$H = @{ "X-Owner-User-Id" = "ou_ff894386d0ca340dcc2f7bdc53c57a81" }

# 1) 从 TTC 网关拉取真实人才库并入库(需 .env 已配 Token)
Invoke-RestMethod "http://localhost:8000/sync/ttc" -Method Post -Headers $H
# { ok=True, synced=358, mode=api }

# 2) 查看入库人才数量
(Invoke-RestMethod "http://localhost:8000/talents" -Headers $H).Count
# 358

# 3) 设定当前岗位(触发引擎)
Invoke-RestMethod "http://localhost:8000/positions" -Method Post -Headers $H `
  -ContentType "application/json" `
  -Body '{"position_name":"商业分析师","jd_text":"数据分析 SQL Python 业务洞察"}'

# 4) 实时推荐 Top3 / Top10 / TopN
$r = Invoke-RestMethod "http://localhost:8000/recommend/compute?position_name=商业分析师" -Method Post -Headers $H
"pool=$($r.total_pool) shortlisted=$($r.shortlisted)"
$r.top3 | ForEach-Object { "  #$($_.rank) $($_.name) | $($_.company) | score=$($_.score)" }

# 5) 页面导出 JSON 直接导入(无需 TTC token, 开发期备用)
Invoke-RestMethod "http://localhost:8000/sync/ttc/ingest" -Method Post -Headers $H `
  -ContentType "application/json" -Body '{"talents":[{"id":"T001","姓名":"张三","base":"上海","经验":"8年3个月经验"}]}'
```

> 用 `Invoke-RestMethod`（PS 原生）而非 `curl`——PS 5.1 会吞掉 `curl -d '{...}'` 的 JSON 引号导致解析失败。>   
> 中文参数务必 URL 编码（如 `curl -G --data-urlencode "position_name=商业分析师"`），否则 uvicorn 报 `Invalid HTTP request`。

---

## 6. 如何测试（全流程连通性）

```bash
conda activate reloop
python tests/test_pipeline.py            # 也可 pytest tests/test_pipeline.py -v
python tests/test_sync_pipeline.py       # 真实 HTTP 同步路径闭环
python check_db.py                       # RDS 连通性自检(本地填真实外网地址后)
```

测试用 SQLite 临时库（`BRAINX_DATABASE_URL` 覆盖，不碰 RDS）、LLM 强制离线模式，  
依次验证：**字段解析 → 标准格式 → 结构化入库 → 数据隔离 → 设岗 → 引擎计算 → TopN 排序 → 结果落库**。  
全部通过打印 `=== 全流程测试通过 ===`。

---

## 7. 可选：纯前端离线预览（旧 `server.js`）

仅用于**不启后端、单独设计/调试 UI**（mock 样本），不参与合并部署：

```bash
cd webapp && npm run dev          # = node server.js，默认端口 3000
# 打开 http://localhost:3000 ，设置页 mode=mock
```

> 合并部署后日常使用 `uvicorn` 即可，无需此步骤。

---

## 8. 数据链路 / 算法（速览）

**8 环链路**：① TTC 取数 → ② 归一化 → ③ 画像结构化(补价值分/向量/倾向) →  
④ 落库 talent_profiles(按 owner 隔离) → ⑤ 用户设岗 → ⑥ 粗筛+五因子精算 → ⑦ 落库 recommendations →  
⑧ 用户反馈 confirm/reject/correct(反哺评分)。

**触达优先级 = 活跃度^0.3 × 岗位匹配^0.4 × 人才价值^0.15 × 历史关系^0.1 × 求职可能^0.05**  
（权重 `.env` 的 `BRAINX_SCORE_W_*` 可调）。乘法模型下任一关键因子趋 0 会显著压低总分，  
自然抑制「活跃但不匹配」的噪声候选人，再配合噪声阈值(0.1)剔除。

**降级策略**（无外部凭据流程仍跑通）：

- LLM 无 Key：结构化走纯规则抽取；embedding 用本地确定性哈希向量；联系理由用模板。
- TTC 无 Token：跳过接口拉取，用「页面导出 JSON 导入」方式（开发期最实用）。

---

## 9. 后续待办

- 前端接入登录态（替换 `reloop/api/deps.py::get_current_user` 解析 SSO，其余不动）。
- 真实 LLM Key 接入（`BRAINX_LLM_*` 换成 OpenAI 兼容服务，如阿里云百炼，开启真实 embedding/话术）。
- `BRAINX_SCORE_W_*` 权重按反馈调优；补齐「按人查互动 GET」与仪表盘聚合接口。
