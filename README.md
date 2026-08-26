# Reloop — 私域人才触达工作台

> 今天你最应该联系谁,以及为什么。

Reloop 从 TTC 私域人才库拉取人才数据，结构化入库（阿里云 RDS MySQL），通过「活跃度 × 岗位匹配度」双指标为候选人排序，帮助顾问找出最值得优先触达的人。

---

## 一、文件结构

```
Reloop/
├── reloop/                    # 后端 (Python FastAPI)
│   ├── main.py                # 应用入口, 路由挂载, 静态前端伺服
│   ├── config.py              # 统一配置 (pydantic-settings, 读 .env, BRAINX_ 前缀)
│   ├── api/                   # API 路由层
│   │   ├── auth.py            # 飞书扫码登录 + 用户信息
│   │   ├── deps.py            # 依赖注入 (DB会话, 用户识别, 数据隔离)
│   │   ├── talents.py         # 人才库 CRUD + 关注/取消关注 + 互动记录
│   │   ├── positions.py       # 岗位设定 (增删查, 上限 10)
│   │   ├── recommend.py       # 推荐触发 + 结果轮询 + 反馈
│   │   └── sync.py            # TTC 人才库同步 (异步进度)
│   ├── db/                    # 数据库层
│   │   ├── engine.py          # SQLAlchemy 引擎 + 会话工厂 + init_db 幂等补列
│   │   └── models.py          # ORM 模型 (User, TalentProfile, Position, ...)
│   ├── modules/               # 业务逻辑层
│   │   ├── auth/              # 飞书 OAuth + 会话Token + 凭证管理
│   │   ├── profile/           # 画像结构化 (structuring.py) + LLM 服务 (llm.py, 含熔断)
│   │   ├── recommend/         # 两阶段推荐引擎 (engine.py: 初筛秒出 + 后台LLM精算)
│   │   ├── scoring/           # 双因子评分 (factors.py + priority.py)
│   │   └── sync/              # TTC 客户端 (client.py) + 归一化 (normalizer.py) + 同步编排
│   ├── schemas/               # Pydantic 请求/响应 schema
│   └── utils/                 # 工具 (数据隔离断言等)
├── frontend/                  # React/Vite 源码 (Hash Router)
├── webapp/                    # 构建产物，由 `npm run build:web` 生成
│   ├── index.html             # 入口 HTML (侧边栏 + 主内容)
│   ├── app.js                 # 路由 + 视图 (Home/Talents/Detail/Positions/Settings)
│   ├── styles.css             # 全局样式 (深色/浅色主题)
│   ├── i18n.js                # 国际化 (zh-CN / en-US)
│   └── data/
│       ├── provider.js        # API 客户端 (live/mock 切换, 前端缓存)
│       └── mock.js            # 样本数据 (离线演示)
├── sql/                       # DDL 脚本
├── _migrate_linda.py          # 生产数据归属迁移脚本 (孤儿 open_id -> 飞书身份, 默认 dry-run)
├── tests/                     # 测试 (test_pipeline.py: SQLite 覆盖 + LLM 离线)
├── .env                       # 环境变量 (本地/服务器各自维护, 不入库不被覆盖)
├── requirements.txt           # Python 依赖
└── package.json               # Node 依赖 (仅前端构建工具)
```

---

## 二、数据流逻辑（参考《Hayden.md 数据流总文档》）

```
【第一部分 读取数据】TTC 私域人才库 (app.ttcadvisory.com, 需飞书登录)
    │  服务端全局 Token (BRAINX_TTC_TALENT_AUTH_TOKEN) 认证
    ▼
TTCClient.fetch_talents()  ── 分页拉取 (page/page_size=100, 重试+退避)
    │
【第二部分 提取字段与数据库】
    ▼
normalizer.normalize_batch()  ── 对齐 TTC 真实 XHR 字段, 归一化为标准格式:
    │   • 基本信息: 姓名/联系方式(电话/邮箱)/地点/经验/学历
    │   • 职业发展: 工作经历多段(起止时间/公司/业务线/岗位·职级/职责/管理规模)、
    │              稳定性指标(平均/最长/最近任期、公司数)、公司类别、业务领域
    │   • 教育背景: 教育经历明细(学校/专业/学历/时间/院校层次)
    │   • 项目经验: 项目名/公司/角色/行业赛道/业务场景/技术栈/时间/描述/成果
    │   • 目标与动机: 求职状态/当前薪资/期望薪资/目标岗位/离职原因
    │   • 人才库备注: 关注原因(concern_reason)+关注标签(concern_tags)
    │   • 简历更新时间: dynamic.macro.last_updated_at (活跃度核心参考维度)
    ▼
structuring_service.enrich_and_save()  ── LLM 增强(可选) + embedding 向量
    │  (LLM 不可用自动降级: 本地哈希向量 + 模板理由, 全流程离线可跑)
    ▼
RDS MySQL (reloop_app.talent_profiles)  ── 按 owner_user_id 隔离
    │  自动补列(engine.init_db): 新字段幂等 ALTER, 兼容旧库
    │  去重: 同 source_id 且 source_payload 未变 -> 跳过, 不重复上传
    ▼
【第三部分 岗位设置】positions 表 (岗位名 + JD, 最多 10 个, 同名同JD幂等)
    ▼
【第四部分 指标计算】recommend_engine (两阶段, 见「核心算法」)
    │  ① 缓存命中 -> 秒回最终结果 (recommend_runs 表持久缓存)
    │  ② 未命中 -> 快速初筛秒出(纯本地) + 后台 LLM 精算
    │  前端轮询 GET /recommend/result, 精算完成后原地更新
    ▼
【第五部分 前端】webapp SPA
    • 首页: 推荐列表(双因子数值同屏展示) + 排序切换(匹配度/活跃度/自定义滑块)
    • 人才库: 列表 + 搜索 + 特别关注
    • 人才详情: 数据库全字段展示(工作经历多段/教育/项目/备注/联系方式/求职状态等)
    • 设置: 数据源切换/登录/手动同步(进度提示)
```

### 数据隔离

- 所有业务表带 `owner_user_id` 隔离键；生产强制飞书登录态 `X-Auth-Token`（`auth_require_token=True`），`X-Owner-User-Id` 仅开发期 fallback。
- 未登录访客走 `guest_shared` 共享池。

### 数据库表

| 表 | 说明 |
|----|------|
| users | 用户（隔离键归属） |
| talent_profiles | 统一人才画像库（TTC 同步 + LLM 结构化落库，含新格式工作经历/教育/备注/联系状态等） |
| positions | 用户设定的招聘岗位 |
| interaction_records | 站内互动记录（历史关系 + 活跃度信号来源） |
| recommendations | 推荐结果（TopN 全量落库） |
| recommend_runs | 推荐运行缓存栈（两阶段计算核心） |
| feedback_logs | 用户反馈 |

`talent_profiles` 关键字段（v4.1 新增对齐 TTC 真实字段）：

```
contact_phone / contact_email   联系方式
seek_status                     求职状态 (已离职找工作/在职看机会...)
current_salary / expected_salary 当前/期望薪资
target_positions                目标岗位
contact_status                  联系状态 (运营备注: 未联系/已联系...)
notes                           人才库备注 (关注原因+关注标签)
stability                       {avg_tenure, max_tenure, recent_tenure, company_count,
                                 has_big_company_exp, has_management_exp, max_management_scale}
work_history                    [{company, business_line, position, job_level,
                                  start_date, end_date, tenure_months, description(职责),
                                  management_scale, has_management, ...}]
projects                        [{name, company, role, industry, scenario, tech_stack,
                                  start_date, end_date, description, core_achievement, ...}]
education_history               [{school, major, degree, start_date, end_date, school_tier, ...}]
delivery_records                [{position, company, date, status, source}]
resume_updated_at               简历更新时间 (活跃度核心参考维度)
```

---

## 三、核心算法

### 1. 活跃度（独立计算，不掺匹配度）

```
活跃度 = 混合归一化( 绝对分, 相对分 )
绝对分 = 1 - 最近事件天数 / 180        (最近事件越近越高, 下限 0.05)
相对分 = min-max( 各人才原始活跃能量 )  (批内相对排序)
最终   = α × 绝对分 + (1-α) × 相对分    (α = BRAINX_ACTIVITY_ABSOLUTE_WEIGHT = 0.4)
```

原始活跃能量 = Σ 事件权重 × e^(-λ × 距今天数)，按事件类型加权并随时间半衰期衰减：

| 事件 | 权重 | 半衰期(天) |
|------|------|-----------|
| profile_update(简历更新) | 10.0 | 21 |
| platform_active(平台活跃) | 6.0 | 14 |
| interview | 8.0 | 30 |
| call | 5.0 | 45 |
| message | 2.0 | 45 |

> **简历更新时间是活跃度核心参考维度**（Hayden.md 2.1.2）：`dynamic.macro.last_updated_at` 即人才在 TTC 平台最近一次更新简历的时间，数据获取成本低、准确性高。同步时已从 TTC 真实 XHR 采集。

### 2. 岗位匹配度（独立计算，不掺活跃度）

```
主通道(LLM):  match = 0.6 × LLM分 + 0.4 × 结构化分    (精算时, 仅 Top30 调 LLM 控耗时)
降级通道:     match = 结构化五维分                      (快速初筛/LLM 不可用时)
```

**结构化五维**（权重缺失自动重归一，base=0.3 防止整体过低）：

| 维度 | 权重 | 算法 |
|------|------|------|
| title | 0.25 | LLM 职位语义相似度优先（`llm.title_similarity`，解决"AI研发工程师↔算法工程师"跨词面匹配），离线降级 bigram |
| skill | 0.30 | Jaccard 双向覆盖率（避免长 JD 惩罚，JD 越长不再分母越大） |
| semantic | 0.35 | JD 向量 × 简历向量余弦（embedding） |
| years | 0.05 | 经验年限是否满足 JD 要求 |
| edu | 0.05 | 学历是否满足 JD 要求 |

**分数校准（规则 B）**：LLM 批量分按分位线性映射到 [0.1, 0.9]，保证：
- 长 JD 不导致分数普遍偏低，短 JD 不导致全员 0.99（B1）
- 分数在 0-1 合理分布，结果贴近大模型/人工直觉（B2/B3）

### 3. 综合排序（双因子，独立原则 A1）

```
综合分 = 活跃度^w1 × 岗位匹配度^w2        (w1=0.3, w2=0.4, 可 .env 调)
按匹配度排序: 100% 匹配度; 按活跃度排序: 100% 活跃度
自定义排序:   滑块联动, 权重和恒为 1
```

### 4. LLM 计算位置一览

| 环节 | 调用点 | 说明 |
|------|--------|------|
| 同步时画像增强 | `llm_service.structure_talent()` | 抽 company_tier/技能，失败降级 |
| 同步时向量 | `llm_service.embed()` | JD/简历向量，失败本地哈希向量 |
| 推荐精算 | `llm_service.title_similarity()` | 岗位名语义相似度（去重分批+缓存） |
| 推荐精算 | `llm_service.batch_match_scores()` | JD vs 简历批量评分（Top30，分位校准） |
| 推荐精算 | `llm_service.generate_contact_reason()` | TopN 逐人联系理由（并发 8） |

> LLM 服务不可用（key 失效/网络异常）：**连续 3 次失败自动熔断**进入离线模式，后续直接走降级，不逐次等待网络超时。

### 5. 两阶段推荐 + 缓存（性能约束）

1. **缓存命中**（recommend_runs 表，cache_key = sha256(owner|岗位|JD|池版本)）→ 秒回最终结果，零 LLM 调用
2. **未命中** → 立即返回快速初筛（纯本地、无 LLM、模板理由），后台线程跑 LLM 精算
3. 前端 2.5s 轮询 `/recommend/result`，算完原地更新（不出现长时间"加载中"）
4. 「重新计算」按钮 → `force=true` 清缓存重算
5. 人才库/互动变化 → 池版本号变化 → 缓存自动失效

---

## 四、如何运行

### 环境要求

- Python 3.11+（建议 conda 环境 `reloop`）
- MySQL 8.0+（生产 RDS；本地测试可用 SQLite）
- Node.js 18+（构建 React/Vite 前端时需要）

### 安装

```bash
# conda 环境（推荐）
conda env create -f environment.yml
conda activate reloop

# 或 pip
pip install -r requirements.txt

# 安装锁定的前端依赖并生成由 FastAPI 伺服的静态资源
npm ci
npm run build:web
```

`frontend/` 是 React/Vite 的唯一源码；`npm run build:web` 会将可复现的生产资源写入
`webapp/`。日常前端开发可运行 `npm run dev:web`，发布前应运行
`npm run check:web`、`npm run test:web` 和 `npm run build:web`。

### 配置

```bash
cp .env.example .env
# 编辑 .env:
#   BRAINX_MYSQL_*    — RDS MySQL 连接（生产 reloop_app 库）
#   BRAINX_LLM_*      — 推荐引擎的 OpenAI 兼容模型与 embedding 配置
#   BRAINX_DEEPSEEK_* — 仅后端的 JD 结构化解析配置
#   BRAINX_TTC_*      — 访客共享池的可选服务端配置
#   BRAINX_FEISHU_*   — 飞书应用 App ID/Secret（扫码登录）
```

飞书和 TTC 回调固定使用 `BRAINX_AUTH_PUBLIC_BASE_URL`：填写已在提供方登记的公网
HTTPS 工作台根地址，例如 `https://reloop.example.com`。服务端据此生成
`/auth/feishu/callback` 与 `/auth/ttc/callback`，浏览器不会提交任意 `redirect_uri`。
用户登录飞书后，可在“设置”中连接个人 TTC 人才库；个人 TTC 登录态由后端加密保存，
不返回给浏览器，也不会回退到访客共享凭据。示例文件只保留占位符，不能填写或提交真实
Token、会话密钥或数据库密码。

### JD 解析与岗位匹配

`POST /positions/parse-jd` 接受非空且不超过 50,000 个字符的 `jd_text`，仅返回可编辑的
结构化预览，不会创建或更新岗位。确认后再通过 `POST /positions` 原子保存原始 `jd_text`
和可选 `jd_analysis`；结构化字段包括岗位名称、摘要、职责、必备/加分技能、经验、学历、
地点、行业关键词、薪资、团队规模、汇报对象和语言要求。带有 `jd_analysis` 的岗位可直接
进入匹配，未解析岗位会先打开 JD 审阅抽屉。

该能力只读取后端环境变量：

```bash
BRAINX_DEEPSEEK_API_KEY=
BRAINX_DEEPSEEK_BASE_URL=https://api.deepseek.com
BRAINX_DEEPSEEK_MODEL=deepseek-chat
BRAINX_DEEPSEEK_TIMEOUT_SECONDS=30
```

DeepSeek 在这里仅用于严格 JSON 的 JD 解析，不提供本项目推荐引擎使用的 embedding
接口。Embedding 仍由独立的 `BRAINX_LLM_*` 配置提供；DeepSeek 密钥不会写入前端、
浏览器存储、接口响应或构建产物。

### 启动（本地）

```bash
uvicorn reloop.main:app --reload --host 127.0.0.1 --port 8000
```

打开 `http://127.0.0.1:8000`，FastAPI 会同源伺服已构建的 `webapp/`。仅修改前端时，可
另开终端运行 `npm run dev:web`，再由 Vite 的开发服务器预览；合并部署仍以构建后的
`webapp/` 为准。

本地开发默认以访客身份（`guest_shared`）访问共享人才池；登录后自动按飞书身份隔离。

### 同步人才库

```bash
# 前端「设置 → 同步 TTC」按钮，或直接调接口
curl -X POST http://localhost:8000/sync/ttc
curl "http://localhost:8000/sync/ttc/status?sync_id=xxx"
```

### 测试

```bash
pytest -q
npm run test:web
npm run check:web
npm run build:web
```

### 代码变更流程（遵守 Hayden.md 第六部分）

1. 从服务器拉取最新代码到本地（本地 `.env` 不动）
2. 本地修改 → 本地自测通过
3. 上传 GitHub fork → 协作者同意后合入 main
4. 全部协作者同意后才允许部署云服务器

---

> 敏感信息（数据库/飞书/服务器账号密码）见《Hayden.md》，不写入本仓库。
