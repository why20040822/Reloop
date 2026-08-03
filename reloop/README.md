# TTC 候选人数据收藏器

本地收藏、清洗和初评公开或已授权的候选人资料。数据保存在 `data/candidates.db`，默认不发送到外部服务。

## 启动

推荐使用 Python 3.12（PaddleOCR 在 Apple Silicon 上需要 Python <3.13）：

```bash
cd reloop

# 如果使用 pyenv
pyenv install 3.12.9
pyenv local 3.12.9

python3.12 -m pip install -e '.[dev]'
./run.sh
```

也可以通过 `TTC_PYTHON` 指定已安装项目依赖的 Python 3.12 解释器：

```bash
TTC_PYTHON=python3.12 ./run.sh
```

打开 <http://127.0.0.1:8765>。

### API 安全配置

本地回环开发可不设置 token；只要通过反向代理、局域网或公网访问，必须设置
`RELOOP_API_TOKEN`，请求使用 `Authorization: Bearer <token>`。跨源访问仅在
`RELOOP_CORS_ORIGINS` 明确列出来源时开启。不要把 token 写入映射 JSON、日志或 dry-run 输出。

### PaddleOCR 启用说明

当前环境如果是 Python 3.14，`paddlepaddle` 暂无官方 wheel，会自动 fallback 到 Tesseract。要启用 PaddleOCR：

1. 安装 Python 3.11 或 3.12。
2. 安装系统 Tesseract（用于 fallback）：
   ```bash
   brew install tesseract tesseract-lang
   ```
3. 在 Python 3.12 环境下运行 `python -m pip install -e '.[ocr]'` 安装可选 PaddleOCR 依赖。
4. `src/reloop/parsing/ocr.py` 的 `engine="auto"` 会优先尝试 PaddleOCR，失败时 fallback 到 Tesseract。

## 安装 Chrome 收藏扩展

1. 打开 `chrome://extensions/`。
2. 开启右上角“开发者模式”。
3. 点击“加载已解压的扩展程序”。
4. 选择本项目下的 `extension` 目录。
5. 在 BOSS、猎聘、脉脉等网站正常登录，打开你有权查看的候选人页面。
6. 点击扩展图标和“收藏当前页面”。

扩展只读取当前页面可见文本，不读取 Cookie、密码或浏览器历史。

### BOSS 在线简历高效入库

新版扩展对 BOSS 简历页做了结构化提取：
- 自动识别“基础信息 / 个人优势 / 工作经历 / 项目经历 / 教育经历 / 技能专长”。
- 过滤导航栏、聊天按钮等无关 UI 噪声。
- 后端同时计算两套分数：
  - **画像分**：启承资本硬性规则（咨询+甲方+学历+年龄等）。
  - **JD 对齐分**：针对“新消费品牌策略顾问（投后）”岗位的关键词加权评分，含大厂背景惩罚。

### 自动阅读列表

1. 打开 BOSS、猎聘、脉脉等已支持网站的候选人列表页。
2. 打开扩展，选择本批数量（最多 10 人）和阅读间隔（至少 8 秒）。
3. 点击“自动阅读当前列表”。
4. 扩展会先自动向下滚动列表加载更多候选人卡片，再逐个打开识别到的候选人链接、等待页面渲染、收藏可见文本并关闭页面。
5. 可随时点击“停止自动阅读”。遇到登录失效、验证码、异常访问或频率限制时，系统会暂停并将对应页面切到前台，由用户决定是否继续。

批量模式只做阅读与收藏，不会自动打招呼、发送消息、申请职位或修改平台数据。不同网站改版后，列表链接识别规则可能需要调整。

## 支持的导入

- 登录后候选人页：Chrome 扩展手动收藏当前可见页面（推荐 BOSS）。
- 公开 HTML：仪表盘粘贴 URL。
- 本地 PDF：仪表盘选择文件，限 12MB。
- 其他资料：直接粘贴文本。
- 个人 Gmail：只读搜索简历邮件，自动下载并解析 PDF/Word 附件。

## 新版统一入库流水线（v2）

`reloop` 现在提供一条统一的简历解析与飞书多维表格入库流水线：

- 输入：本地 PDF/DOC/DOCX、图片、浏览器扩展抓取的文本。
- 输出：结构化的 `CandidateRecord`，先写入 SQLite outbox，再由 worker 按 RDS → 飞书顺序投递。
- 默认 dry-run；`--write` 只会持久化 outbox，不会在 API 进程中旁路写外部系统。
- 按附件 SHA-256、手机号、姓名+公司组合去重。

### 命令行 dry-run

```bash
cd reloop

# 预览一份 PDF 会写入哪些字段（不修改飞书）
python -m reloop.ops.cli ingest-file ../简历数据/个人简历_张佩柔.pdf --dry-run

# 进入 outbox，稍后由 worker 投递到 RDS，再投影到飞书
python -m reloop.ops.cli ingest-file ../简历数据/个人简历_张佩柔.pdf --write

# 从文本写入
python -m reloop.ops.cli ingest-text --text "王小明 13812345678 ..." --dry-run
```

### HTTP API

```bash
# 解析本地文件并预览飞书 payload
curl -X POST http://127.0.0.1:8765/api/ingest-v2/file \
  -H 'Content-Type: application/json' \
  -d '{"path":"/Users/ashley/Downloads/ttc的交易系统/简历数据/个人简历_张佩柔.pdf","dry_run":true}'

# 解析文本
curl -X POST http://127.0.0.1:8765/api/ingest-v2/text \
  -H 'Content-Type: application/json' \
  -d '{"text":"王小明 13812345678 ...","dry_run":true}'

# 查看最近入库日志
curl http://127.0.0.1:8765/api/ingest-v2/log
```

### 飞书字段映射

字段 ID 和选项通过 `lark-cli base +field-list` 从真实人才库读取，配置保存在：

```text
reloop/config/feishu_field_mapping.json
```

写入时只写存储字段；`查重值` 等公式字段、系统字段、`lookup` 字段会自动跳过。

## 批量推人导出

仪表盘点击“导出 JD 排序”或调用接口：

```bash
curl 'http://127.0.0.1:8765/api/export-jd?min_score=50' | python3 -m json.tool
```

返回按 JD 对齐分排序的候选人列表，含推荐结论、证据摘要、来源链接，可直接用于向客户推人。

## 连接邮箱

支持 Gmail（应用专用密码 + macOS 钥匙串）以及任意支持 IMAP 的邮箱。

### Gmail

1. Google 账户开启两步验证。
2. 打开 <https://myaccount.google.com/apppasswords>，创建一个应用专用密码。
3. 在本机运行 `python3 -m reloop.sinks.gmail.setup`。
4. 运行 `python3 -m reloop.sinks.gmail.sync --limit 100` 立即同步。

### 通用 IMAP 邮箱

通过环境变量配置：

```bash
export TTC_EMAIL_IMAP_SERVER=imap.example.com
export TTC_EMAIL_IMAP_PORT=993
export TTC_EMAIL_USERNAME=your@email.com
export TTC_EMAIL_PASSWORD=your-app-password
export TTC_EMAIL_QUERY="UNSEEN"
python3 -m reloop.sinks.gmail.sync --limit 100
```

或使用 JSON 配置文件：

```bash
cp config/email_sync.example.json config/email_sync.json
# 编辑 config/email_sync.json（不写入密码）
python3 -m reloop.sinks.gmail.sync --config config/email_sync.json --limit 100
```

### 同步行为

- 默认每 5 分钟自动检查一次。
- 只读取收件箱，使用 `BODY.PEEK` 不改变已读状态。
- 下载 PDF、DOC、DOCX 和常见图片附件。
- 通过邮件 Message-ID + 附件 SHA-256 双重去重。
- 不再按具体岗位过滤；只要附件/主题看起来像简历就会入库，岗位分类交给解析后处理。
- 单封邮件失败会进入重试队列，不会中断整批同步。
- 密码和令牌不写入源码、日志或 Git。

### 浏览器扩展平台解析器

扩展的页面解析逻辑已按平台拆分：

```text
reloop/extension/parsers/
├── common.js    # 共享工具：风险词检测、URL 归一化、平台识别
├── boss.js      # BOSS 直聘结构化提取 + 候选人链接识别
├── maimai.js    # 脉脉候选人链接识别
├── liepin.js    # 猎聘候选人链接识别
└── generic.js   # 通用回退识别
```

`background.js` 现在根据当前标签页域名注入对应的解析器文件，再执行页面读取/链接识别。新增平台时只需新增 `parsers/<platform>.js` 并在 `background.js` 的 `platformFromUrl` 映射中注册。

## 边界

- 不自动登录，不保存账号密码。
- 不绕过验证码、付费墙、访问控制或平台限制。
- 不从头像推断年龄。年龄不明时只生成待验证项，不自动淘汰。
- 启承匹配分是简历证据完整度初评，不代替人工招聘决策。

## 测试

```bash
cd reloop
python3.12 -m pytest tests -q
```

### Outbox worker

```bash
cd ..
python3.12 -m pip install -e reloop
reloop-worker --limit 10
```

The worker fails closed when RDS is not configured. Feishu remains `blocked`
until RDS reports success; a Feishu-only retry never repeats the RDS upsert.
