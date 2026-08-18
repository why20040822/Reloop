# TTC 候选人数据收藏器

本地收藏、清洗和初评公开或已授权的候选人资料。数据保存在 `data/candidates.db`，默认不发送到外部服务。

## 启动

推荐使用 Python 3.12（PaddleOCR 在 Apple Silicon 上需要 Python <3.13）：

```bash
cd candidate-collector

# 如果使用 pyenv
pyenv install 3.12.9
pyenv local 3.12.9

python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
./run.sh
```

或指定其他 Python 解释器：

```bash
TTC_PYTHON=python3.11 ./run.sh
```

打开 <http://127.0.0.1:8765>。

### PaddleOCR 启用说明

当前环境如果是 Python 3.14，`paddlepaddle` 暂无官方 wheel，会自动 fallback 到 Tesseract。要启用 PaddleOCR：

1. 安装 Python 3.11 或 3.12。
2. 安装系统 Tesseract（用于 fallback）：
   ```bash
   brew install tesseract tesseract-lang
   ```
3. 在 Python 3.12 环境下安装依赖，`requirements.txt` 会自动安装 `paddlepaddle` 和 `paddleocr`。
4. `image_processing/ocr.py` 的 `engine="auto"` 会优先尝试 PaddleOCR，失败时 fallback 到 Tesseract。

## 安装 Chrome 自动导入扩展

1. 打开 `chrome://extensions/`。
2. 开启右上角“开发者模式”。
3. 点击“加载已解压的扩展程序”。
4. 选择本项目下的 `extension` 目录。
5. 在 TTC 或脉脉正常登录，打开你有权查看的单个候选人详情。
6. 页面资料稳定后会自动写入飞书；扩展弹窗可检查本地服务和最近结果。

扩展观察已授权页面自身返回的候选人资料与简历附件，不读取 Cookie、密码、JWT、localStorage 或浏览器历史，也不绕过登录和验证码。

### 飞书写入策略

- 主表：`Otto1`（`tblpNAH9tV1pqulm`）。
- 备用表：`Otto2`（`tblEHeMS9wk6g0ui`）；仅在 Otto1 同步锁被占用或返回表级并发冲突 `1254291` 时使用。
- 有 PDF 时保留原始字节、计算 SHA-256，并在创建记录后上传“简历附件”。
- 没有 PDF 时仍写入平台结构化资料，并在“备注信息”记录降级原因。
- 去重优先使用平台 + 来源候选人 ID，其次使用人才库链接和 PDF SHA-256。

## 支持的导入

- TTC / 脉脉已授权候选人详情：Chrome 扩展自动导入。
- 公开 HTML：仪表盘粘贴 URL。
- 本地 PDF：仪表盘选择文件，限 12MB。
- 其他资料：直接粘贴文本。
- 个人 Gmail：只读搜索简历邮件，自动下载并解析 PDF/Word 附件。

## 新版统一入库流水线（v2）

`candidate-collector` 现在提供一条统一的简历解析与飞书多维表格入库流水线：

- 输入：本地 PDF/DOC/DOCX、图片、浏览器扩展抓取的文本。
- 输出：结构化的 `CandidateRecord`，最终写入指定的飞书人才库。
- 默认 dry-run，先预览再真正写入。
- 按附件 SHA-256、手机号、姓名+公司组合去重。

### 命令行 dry-run

```bash
cd candidate-collector

# 预览一份 PDF 会写入哪些字段（不修改飞书）
python3 cli.py ingest-file ../简历数据/个人简历_张佩柔.pdf --dry-run

# 真正写入飞书（请确认后再执行）
python3 cli.py ingest-file ../简历数据/个人简历_张佩柔.pdf --write

# 从文本写入
python3 cli.py ingest-text --text "王小明 13812345678 ..." --dry-run
```

### HTTP API

```bash
# 解析本地文件并预览飞书 payload
curl -X POST http://127.0.0.1:8765/api/ingest-v2/file \
  -H 'Content-Type: application/json' \
  -d '{"path":"/absolute/path/to/resume.pdf","dry_run":true}'

# 解析文本
curl -X POST http://127.0.0.1:8765/api/ingest-v2/text \
  -H 'Content-Type: application/json' \
  -d '{"text":"王小明 13812345678 ...","dry_run":true}'

# 查看最近入库日志
curl http://127.0.0.1:8765/api/ingest-v2/log
```

### 飞书字段映射

字段 ID 和选项通过 `lark-cli base +field-list` 从真实人才库读取，写入前还会按字段名进行 schema 预检。配置保存在：

```text
candidate-collector/config/feishu_field_mapping_candidate.json
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
3. 在本机运行 `python3 gmail_setup.py`。
4. 运行 `python3 gmail_sync.py --limit 100` 立即同步。

### 通用 IMAP 邮箱

通过环境变量配置：

```bash
export TTC_EMAIL_IMAP_SERVER=imap.example.com
export TTC_EMAIL_IMAP_PORT=993
export TTC_EMAIL_USERNAME=your@email.com
export TTC_EMAIL_PASSWORD=your-app-password
export TTC_EMAIL_QUERY="UNSEEN"
python3 gmail_sync.py --limit 100
```

或使用 JSON 配置文件：

```bash
cp config/email_sync.example.json config/email_sync.json
# 编辑 config/email_sync.json（不写入密码）
python3 gmail_sync.py --config config/email_sync.json --limit 100
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

扩展的页面解析逻辑分为经典 DOM 解析器与 TTC / 脉脉授权 API 响应观察器：

```text
candidate-collector/extension/parsers/
├── common.js    # 共享工具：风险词检测、URL 归一化、平台识别
├── ttc.js       # TTC 数字 / PL... 候选人 ID
├── maimai.js    # 脉脉候选人链接识别
└── generic.js   # 通用回退识别
```

`parsers/*.js` 是可重复注入的经典脚本，不包含 `import/export`。`content/network_interceptor.js` 在 MAIN world 只观察 TTC/脉脉白名单接口，通过专用 `MessageChannel` 传给隔离世界。`content/auto_import.js` 负责稳定等待、自动写入、PDF补传和页面状态提示。PDF 由扩展后台分块上传至本机，扩展存储只保留最近状态，不保存候选人原始资料。

## 边界

- 不自动登录，不保存账号密码。
- 不绕过验证码、付费墙、访问控制或平台限制。
- 不从头像推断年龄。年龄不明时只生成待验证项，不自动淘汰。
- 启承匹配分是简历证据完整度初评，不代替人工招聘决策。

## 测试

```bash
cd candidate-collector
.venv/bin/python -m unittest -v
node extension/test_validation.mjs
node extension/test_runtime.mjs
```
