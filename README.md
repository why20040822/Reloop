# Reloop — 私域人才触达工作台

> 今天你最应该联系谁,以及为什么。

## 项目结构

```
Reloop/
├── reloop/                    # 后端 (Python FastAPI)
│   ├── main.py                # 应用入口, 路由挂载, 静态前端伺服
│   ├── config.py              # 统一配置 (pydantic-settings, 读 .env)
│   ├── api/                   # API 路由层
│   │   ├── auth.py            # 飞书扫码登录 + 用户信息
│   │   ├── deps.py            # 依赖注入 (DB会话, 用户识别, 数据隔离)
│   │   ├── talents.py         # 人才库 CRUD + 关注/取消关注 + 互动记录
│   │   ├── positions.py       # 岗位设定 (增删查)
│   │   ├── recommend.py       # 推荐触发 + 结果轮询 + 反馈
│   │   └── sync.py            # TTC 人才库同步 (异步进度)
│   ├── db/                    # 数据库层
│   │   ├── engine.py          # SQLAlchemy 引擎 + 会话工厂 + 幂等补列
│   │   └── models.py          # ORM 模型 (User, TalentProfile, Position, ...)
│   ├── modules/               # 业务逻辑层
│   │   ├── auth/              # 飞书 OAuth + 会话Token + 凭证管理
│   │   ├── profile/           # 画像结构化 + LLM 增强
│   │   ├── recommend/         # 两阶段推荐引擎 (初筛秒出 + 后台LLM精算)
│   │   ├── scoring/           # 双因子评分 (活跃度 + 岗位匹配度)
│   │   └── sync/              # TTC 数据源客户端 + 归一化 + 同步编排
│   ├── schemas/               # Pydantic 请求/响应 schema
│   └── utils/                 # 工具 (数据隔离断言等)
├── webapp/                    # 前端 (原生 JS SPA, hash 路由)
│   ├── index.html             # 入口 HTML (侧边栏 + 搜索 + 主内容)
│   ├── app.js                 # 路由 + 视图 (Home/Talents/Detail/Positions/Settings)
│   ├── styles.css             # 全局样式 (深色/浅色主题)
│   ├── i18n.js                # 国际化 (zh-CN / en-US)
│   └── data/
│       ├── provider.js        # API 客户端 (live/mock 切换, 前端缓存)
│       └── mock.js            # 样本数据 (离线演示)
├── sql/                       # DDL 脚本
├── .env                       # 环境变量 (不入库)
├── requirements.txt           # Python 依赖
└── package.json               # Node 依赖 (仅前端构建工具)
```

## 数据流

```
TTC 人才库 (app.ttcadvisory.com)
    │  Bearer Token 认证
    ▼
TTCClient.fetch_talents()     ← 带重试 + 多格式兼容
    │
    ▼
normalizer.normalize_batch()  ← 字段归一化 (中英文别名映射)
    │
    ▼
structuring_service           ← LLM 增强抽取 (可选) + embedding
    │
    ▼
MySQL (talent_profiles 表)    ← 按 owner_user_id 隔离
    │
    ▼
recommend_engine              ← 两阶段: 初筛秒出 + 后台LLM精算
    │
    ▼
前端 SPA                      ← 排序切换 + 滑块权重 + 关注/互动
```

## 算法逻辑

### 双因子评分模型 (A1 独立原则)

```
综合分 = 活跃度^w1 × 岗位匹配度^w2
```

- **活跃度**: 半衰期牛顿冷却 + 绝对/相对混合归一化, 来源包括平台最近活跃时间、简历更新时间、站内互动记录
- **岗位匹配度**: LLM 批量推理(主通道60%) + 结构化多维降级(40%), 含职位语义相似度、技能重叠、经验年限、学历等

两个因子完全独立计算, 互不参透 (A1)。

### 排序模式 (A2/A4)

| 模式 | 排序权重 | 说明 |
|------|---------|------|
| 按匹配度 | 100% 匹配度 | 另一指标仅展示 (A3) |
| 按活跃度 | 100% 活跃度 | 另一指标仅展示 (A3) |
| 自定义 | 滑块控制 | 两滑块联动, 权重和恒为1 (A4) |

### 两阶段推荐 (缓存优化)

1. **缓存命中** → 秒返回最终结果, 零 LLM 调用
2. **未命中** → 立即返回快速初筛(纯本地, 不调LLM), 后台线程执行 LLM 精算
3. 前端每 2.5s 轮询, 精算完成后原地更新列表
4. 同一 (岗位+JD+数据版本+排序模式+权重) 不重复计算

### 分数分布校准 (A5)

LLM 批量匹配分数经分位校准映射到 [0.1, 0.9], 避免因 JD 长短导致全员偏高/偏低。

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/auth/feishu/url` | 获取飞书授权页 URL |
| GET | `/auth/feishu/qrcode` | 登录二维码 SVG |
| POST | `/auth/feishu/login` | 授权码换登录态 |
| GET | `/auth/me` | 当前用户信息 |
| GET | `/talents` | 人才库列表 (支持 keyword) |
| GET | `/talents/followed/list` | 已关注人才列表 |
| GET | `/talents/{id}` | 人才详情 |
| POST | `/talents/{id}/follow` | 关注/取消关注 (toggle) |
| POST | `/talents/{id}/interaction` | 记录互动 |
| GET | `/positions` | 生效岗位列表 |
| POST | `/positions` | 设定岗位 |
| DELETE | `/positions/{id}` | 删除岗位 |
| POST | `/recommend/compute` | 触发推荐 |
| GET | `/recommend/result` | 轮询推荐结果 |
| POST | `/recommend/feedback` | 用户反馈 |
| POST | `/sync/ttc` | 同步 TTC 人才库 |
| GET | `/sync/ttc/status` | 查询同步进度 |

## 如何运行

### 环境要求

- Python 3.11+
- MySQL 8.0+ (或 SQLite 测试)
- Node.js 18+ (仅前端开发)

### 安装

```bash
# 后端
pip install -r requirements.txt

# 前端 (无需构建, 直接由后端伺服)
# 开发期可单独起: npx serve webapp -p 3000
```

### 配置

```bash
cp .env.example .env
# 编辑 .env, 填入:
#   BRAINX_MYSQL_*      — RDS MySQL 连接信息
#   BRAINX_LLM_*        — 大模型 API (智谱/百炼/DeepSeek)
#   BRAINX_TTC_*        — TTC 人才库 Token + Space ID
#   BRAINX_FEISHU_*     — 飞书应用 App ID/Secret
```

### 启动

```bash
# 开发模式 (热重载)
uvicorn reloop.main:app --reload --host 0.0.0.0 --port 8000

# 生产模式
uvicorn reloop.main:app --host 0.0.0.0 --port 8000 --workers 2
```

打开浏览器访问 `http://localhost:8000` 即可使用。

### 本地运行 (不连服务器)

本地 `.env` 保持不动, 直接:

```bash
cd F:\ttc\Reloop
uvicorn reloop.main:app --reload --port 8000
```

前端由后端自动伺服 (`webapp/` 目录), 无需额外启动前端服务。
