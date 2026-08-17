# Reloop - 私域人才触达优先级推荐

> **今天你最应该联系谁，以及为什么。**
> 从 TTC 私域人才库提取人才数据 -> 标准结构化 -> 统一人才画像库(RDS MySQL) ->
> 用户设定当前岗位 -> 实时触发引擎(粗筛+精算) -> Top3 / Top10 / TopN 推荐列表。

外部接口只有三类：**TTC 私域人才库(数据源)**、**大模型(OpenAI 兼容通用接口)**、**RDS MySQL(唯一数据库)**。
已移除：阿里云 OSS、外部活跃信号(飞书等)、定时推送。

---

## 1. 运行环境

- Python 3.11（**conda 环境，不装进系统 Python**）
- 依赖：FastAPI / SQLAlchemy 2.0 / PyMySQL / pydantic-settings / httpx（见 `environment.yml`）
- 数据库：阿里云 RDS MySQL（唯一数据库；测试可用 SQLite 覆盖，不碰 RDS）

```bash
# 创建并进入 conda 环境（首次）
conda env create -f environment.yml
conda activate reloop

# 依赖有更新时
conda env update -f environment.yml --prune
```

配置：`cp .env.example .env`，填 `BRAINX_MYSQL_HOST`（RDS 地址）即可；
大模型 / TTC 登录态不填时自动降级（见下），框架可独立运行。

## 2. 文件结构（按模块划分）

```
Reloop/
├── environment.yml            # conda 环境定义
├── requirements.txt           # pip 版依赖(备用)
├── .env.example               # 全部接口配置(复制为 .env)
├── sql/schema.sql             # RDS MySQL 建表脚本(生产)
├── reloop/
│   ├── config.py              # 统一配置(BRAINX_ 前缀环境变量)
│   ├── main.py                # FastAPI 入口
│   ├── db/                    # 数据层
│   │   ├── engine.py          # 引擎/会话(可被 BRAINX_DATABASE_URL 覆盖为 SQLite)
│   │   └── models.py          # ORM: 6 张表, 全部带 owner_user_id 隔离键
│   ├── modules/               # ---- 业务模块 ----
│   │   ├── sync/              # ① TTC 数据源接入
│   │   │   ├── client.py      #    拉取(带登录态)/页面JSON导入 + 隔离入库
│   │   │   └── normalizer.py  #    标准结构化格式(STANDARD_KEYS) + 字段映射
│   │   ├── profile/           # ② 人才画像
│   │   │   ├── llm.py         #    大模型通用接口(chat/embed, 离线哈希向量兜底)
│   │   │   └── structuring.py #    规则+LLM增强 -> 价值分/向量/倾向分落库
│   │   ├── scoring/           # ③ 评分算法
│   │   │   ├── factors.py     #    五因子: 牛顿冷却/余弦/价值/关系/倾向
│   │   │   └── priority.py    #    加权乘法模型 + 排序 + 噪声剔除
│   │   └── recommend/         # ④ 推荐引擎
│   │       └── engine.py      #    粗筛+精算 -> Top3/Top10/TopN + 落库
│   ├── api/                   # HTTP 接口(同步/人才/岗位/推荐)
│   ├── schemas/talent.py      # 请求/响应契约(前后端共用)
│   └── utils/isolation.py     # 数据隔离(查询过滤 + 越权校验)
└── tests/
    └── test_pipeline.py       # 全流程测试(见 §6)
```

## 3. 数据流路径

```
TTC 私域人才库 (https://app.ttcadvisory.com/app/private-talent/.../U2034543869059211264)
   │  ① 提取信息：接口拉取(需飞书登录态 Token) 或 页面导出 JSON 直接导入
   ▼
modules/sync/normalizer.py -- 标准结构化格式(STANDARD_KEYS)
   │  name / base_location / company / position / work_years("8年3个月"->8.25)
   │  education / skills / summary / last_active_at("2天前"->datetime) / tags / raw
   ▼
modules/profile/structuring.py -- 规则+LLM 增强
   │  补: company_tier / tendency_score / value_score(0~1) / resume_embedding(向量)
   ▼
db -> talent_profiles (统一人才画像库, RDS MySQL, 按 owner_user_id 隔离)
   │
   │  ② 用户设定当前岗位(POST /positions "HRBP") -- 实时触发 ↓
   ▼
modules/recommend/engine.py -- 实时触发引擎
   │  粗筛: 标签/职位/画像文本 命中岗位关键词
   │  精算: 五因子批量归一化 -> 加权乘法模型 -> 剔除噪声 -> 排序
   ▼
Top3 / Top10 / TopN 推荐列表
   ├── 返回调用方(HTTP 响应体)
   └── 落库 recommendations 表(按 run_id 一批, 带 rank/五因子明细/联系理由)
```

**降级策略**（无外部凭据时流程依然跑通）：
- LLM 无 Key：结构化走纯规则抽取；embedding 用本地确定性哈希向量（余弦匹配仍可算）；联系理由用模板
- TTC 无 Token：跳过接口拉取，用「页面导出 JSON 导入」方式（开发期最实用）

## 4. 核心算法（modules/scoring/）

**触达优先级 = 活跃度^0.3 × 岗位匹配度^0.4 × 人才价值^0.15 × 历史关系^0.1 × 求职可能性^0.05**（权重可调，`.env` 的 `BRAINX_SCORE_W_*`）

| 因子 | 算法 | 数据来源 |
|---|---|---|
| 活跃度 | 牛顿冷却定律 `Σ(事件权重×e^(-0.1×天数))` + 批量 Min-Max | TTC 平台最近活跃时间 + 站内互动记录 |
| 岗位匹配度 | JD/画像向量余弦相似度 `[-1,1]->[0,1]`（JSON 存向量，应用层计算） | jd_embedding vs resume_embedding |
| 人才价值 | 静态打分：公司等级+学历+稀缺技能 -> 归一化 | talent_profiles.value_score |
| 历史关系 | 近90天互动频次加权(面试×3/通话×2/消息×0.5) + Min-Max | interaction_records |
| 求职可能性 | LLM 文本分析输出 [0,1]，无记录 0.5 中性 | tendency_score |

乘法模型特性：任一关键因子趋 0 会显著压低总分 -> "活跃但与岗位不匹配"的噪声候选人被自然抑制，再配合噪声阈值(0.2)剔除。

## 5. 如何运行

> 以下命令在本机 PowerShell 实测可直接跑通：RDS 外网地址可达、TTC 网关拉到 358 条真实人才、引擎出推荐。
> 用 `Invoke-RestMethod`（PS 原生）而非 `curl` -- PS 5.1 会吞掉 `curl -d '{...}'` 的 JSON 引号导致解析失败。

### 5.1 准备环境

```powershell
conda env create -f environment.yml   # 首次
conda activate reloop
copy .env.example .env                # 复制模板, 再按 5.2 填真实凭据
```

### 5.2 关键配置（.env）

三个外部接口各一处必填，其余默认即可：

```ini
# ① RDS MySQL - 控制台「数据库连接」申请【外网地址】(内网地址解析到 172.x 私网, 本地连不上),
#    并在白名单放通本机公网 IP。用独立库 reloop_app(与他人应用共库会撞 recommendations 表名)
BRAINX_MYSQL_HOST=ttc-rds-public-0707.mysql.rds.aliyuncs.com
BRAINX_MYSQL_DATABASE=reloop_app
BRAINX_DATABASE_URL=                         # 留空=用上面 MySQL; 本地无 RDS 时填 sqlite:///./reloop_dev.db

# ② TTC 人才库 - 接口网关是 gateway 子域(不是 app 子域! app 子域拉数据 404)
BRAINX_TTC_TALENT_BASE_URL=https://gateway.ttcadvisory.com
BRAINX_TTC_TALENT_API_PATH=/api/private-talent/v1/all-talents
BRAINX_TTC_TALENT_AUTH_TOKEN=eyJ...         # 飞书登录态 JWT(约 2 个月有效)
```

TTC Token 抓取步骤（过期后照此重抓）：

1. 浏览器打开人才库页面 `https://app.ttcadvisory.com/app/private-talent/talents/all-talents/U2034543869059211264`
2. F12 -> **Network** -> 筛选 **Fetch/XHR**（或在过滤框输 `gateway`）-> 刷新页面
3. 点开 `gateway.ttcadvisory.com/api/private-talent/v1/all-talents/.../talents?page=1...` 这个请求
4. **Request Headers -> `Authorization: Bearer eyJhb...`** -> 复制 `Bearer ` 后面那串（**不含** `Bearer ` 前缀，代码会自动拼）填进 `BRAINX_TTC_TALENT_AUTH_TOKEN`

> 防坑：Network 里大量的 `apmplus.volces.com/monitor_web/collect` 请求是**前端监控埋点**（性能上报），不是数据接口，别从它复制任何东西。认准 `gateway.ttcadvisory.com` 域名。

```ini
# ③ 大模型(可选) - OpenAI 兼容接口; 不填/填错自动降级(哈希向量+模板话术), 流程仍跑通
BRAINX_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
BRAINX_LLM_API_KEY=
```

### 5.3 启动 API（自动建表）

```powershell
uvicorn reloop.main:app --reload --host 0.0.0.0 --port 8000
# Swagger: http://localhost:8000/docs
```

启动日志出现 `[startup] DB tables ready` 即就绪（`init_db()` 自动在 `reloop_app` 建好 6 张表，无需手动建表）；
出现 `init_db skipped` 则是 RDS 没连上（外网地址未申请 / 白名单未放通 / 库名不对），此时 API 仍启动但写库会失败。

### 5.4 在 Swagger 页面调接口（推荐新手用）

启动后浏览器打开 **http://localhost:8000/docs** ，所有接口操作三步：

1. 点开接口左侧折叠条 -> 点 **Try it out**（进入可编辑模式）
2. 填参数（每个接口要填什么见下表）
3. 拉到最底点 **Execute** -> 下方 **Response body** 就是返回结果（200 = 成功）

**`X-Owner-User-Id` 是什么、填什么？**

每个接口的参数表里都有 `X-Owner-User-Id  string | (string | null) (header)`，它是**"当前用户是谁"的标识**（数据隔离键），不是 TTC 登录 Token：

- 它决定数据归属：同步入库的人才、岗位、推荐结果全部挂在它名下；**换个值 = 换个用户，之前同步的数据就看不到了**
- 不填 -> 接口返回 401
- 开发期填任意字符串都行，但每次要用**同一个值**。本项目已同步 358 人数据的用户 ID：

  ```
  ou_ff894386d0ca340dcc2f7bdc53c57a81
  ```

- TTC 的登录 Token 在 `.env` 的 `BRAINX_TTC_TALENT_AUTH_TOKEN`，由后端自动携带，**不需要**在 Swagger 页面填
- 表单里 `string | (string | null)` 只是说"填一个字符串"，忽略即可

**各接口要填什么**（完整接口清单见 §7）：

| 接口 | X-Owner-User-Id | 其它参数 | 作用 |
|---|---|---|---|
| `POST /sync/ttc` | 上面的用户 ID | 无 | 从 TTC 网关拉取人才库并入库（需 `.env` 已配 Token） |
| `GET /talents` | 同上 | 无 | 查看入库的人才列表 |
| `POST /positions` | 同上 | Body：`{"position_name":"商业分析师","jd_text":"数据分析 SQL Python 业务洞察"}` | 设定当前岗位（触发引擎） |
| `POST /recommend/compute` | 同上 | Query：`position_name=商业分析师` | 实时推荐 Top3 / Top10 / TopN |
| `GET /recommend/latest` | 同上 | 无 | 查看最近一次推荐结果 |
| `POST /sync/ttc/ingest` | 同上 | Body：`{"talents":[{...}]}`（页面复制的 JSON） | 手动导入数据（无需 TTC Token） |

### 5.5 一条龙跑通（PowerShell）

所有接口都要带请求头 `X-Owner-User-Id` 做数据隔离（任意字符串，下例用真实 open_id，已同步过数据，直接可见 358 人）：

```powershell
$H = @{ "X-Owner-User-Id" = "ou_ff894386d0ca340dcc2f7bdc53c57a81" }

# 1) 从 TTC 网关拉取真实人才库并入库
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
```

### 5.6 其它取数 / 备注

```powershell
# 页面导出 JSON 直接导入(无需 TTC token, 开发期备用)
Invoke-RestMethod "http://localhost:8000/sync/ttc/ingest" -Method Post -Headers $H `
  -ContentType "application/json" -Body '{"talents":[{"id":"T001","姓名":"张三","base":"上海","经验":"8年3个月经验"}]}'
```

- **数据隔离**：每个用户的 TTC 人才库完全隔离（`utils/isolation.py` 按 `owner_user_id` 强制过滤）；前端接入登录态后只需替换 `api/deps.py::get_current_user` 一处。
- **LLM 未配真实 Key 时**：embedding 走本地哈希向量、联系理由走模板，推荐仍出结果（匹配度为字级 bigram 近似）。要启用真实向量/话术，把 ③ 换成真实的 OpenAI 兼容服务（如阿里云百炼 `qwen-plus` + `text-embedding-v3`）。

## 6. 如何测试（全流程连通性）

```bash
conda activate reloop
python tests/test_pipeline.py        # 也可 pytest tests/test_pipeline.py -v
```

测试用 SQLite 临时库（设置 `BRAINX_DATABASE_URL` 覆盖，不碰 RDS）、LLM 强制离线模式，
依次验证：**字段解析 -> 标准格式 -> 结构化入库 -> 数据隔离 -> 设岗 -> 引擎计算 -> TopN 排序正确性 -> 结果落库**。
全部通过会打印 `=== 全流程测试通过 ===`。

## 7. 给后期前端预留的接口与输出

前后端契约集中在两处（前端可直接复用）：

- **`reloop/schemas/talent.py`** - 所有请求/响应模型（PositionCreate / RecommendItemOut / RecommendResultOut…）
- **`reloop/api/`** - 4 组路由，Swagger 自动文档 `GET /docs`（OpenAPI JSON 可直接生成前端 client）

| 用途 | 接口 | 说明 |
|---|---|---|
| 推荐列表页 | `POST /recommend/compute?position_name=HRBP` | 返回 `top3 / top10 / top_n`，条目含 talent_id、name、company、base_location、score、score_breakdown(五因子, 可画雷达图)、contact_reason(话术) |
| 查看上次结果 | `GET /recommend/latest` | 最近一次 run 的落库结果 |
| 岗位设定页 | `POST /positions` / `GET /positions` | 设定当前岗位(触发引擎) |
| 人才库页 | `GET /talents` / `GET /talents/glm_5.2_ark_toC` / `DELETE /talents/glm_5.2_ark_toC` | 列表/详情/删除 |
| 记录互动 | `POST /talents/glm_5.2_ark_toC/interaction` | 影响"历史关系+活跃度" |
| 用户反馈 | `POST /recommend/feedback` | confirm/reject/correct，写 feedback_logs 供模型调优 |
| 数据同步 | `POST /sync/ttc` / `POST /sync/ttc/ingest` | 拉取/导入 |

鉴权：所有接口都要带请求头 `X-Owner-User-Id`（含义与填法见 §5.4；前端接登录后替换 `api/deps.py`）。
历史结果也可直接查 `recommendations` 表（按 `owner_user_id + run_id`，含 rank/明细/状态）。

## 8. 接口状态与后续

三类外部接口均已打通并实测（详见 §5）：

- **RDS MySQL**：外网地址 `ttc-rds-public-0707` 可达，`reloop_app` 库 6 张表自动建好，358 条人才已落库。
- **TTC 人才库**：网关 `gateway.ttcadvisory.com` 拉取 358 条真实人才，嵌套结构已标准化入库。
- **大模型**：当前 `.env` 填的是火山方舟 coding 端点（非 OpenAI 兼容，`/embeddings`、`/chat/completions` 均 404），故自动降级为哈希向量+模板话术。换成 OpenAI 兼容服务（如阿里云百炼）即开启真实 LLM 增强与 embedding。

后续待办：前端接入登录态（替换 `api/deps.py::get_current_user`）、真实 LLM Key 接入、`BRAINX_SCORE_W_*` 权重按反馈调优。
