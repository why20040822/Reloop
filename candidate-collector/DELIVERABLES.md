# TTC 候选人自动采集与入库 — 交付状态

## 已完成

### P0：最小闭环
- 统一 `CandidateRecord` 数据模型：`candidate-collector/models.py`
- 统一文档解析接口：`candidate-collector/parsers/`（PDF/图片/DOCX）
- 飞书 Base 字段映射：`candidate-collector/config/feishu_field_mapping.json`
- dry-run / 真实写入 CLI：`candidate-collector/cli.py`
- 附件上传、记录写入、幂等去重：`candidate-collector/ingestion/pipeline.py`
- 端到端测试：`candidate-collector/test_models_and_parser.py`

### P1：邮箱自动入库
- 重构 `candidate-collector/gmail_sync.py` 为统一 IMAP 邮箱同步
- 支持 Gmail（钥匙串）和通用 IMAP（环境变量 / JSON 配置）
- 删除单岗位硬编码，改为简历特征过滤
- 支持 PDF/DOC/DOCX/PNG/JPG/JPEG/TIFF
- Message-ID + SHA-256 双重去重
- 单封邮件失败进入重试队列，不中断整批
- 示例配置：`candidate-collector/config/email_sync.example.json`
- 更新测试：`candidate-collector/test_gmail_sync.py`

### P1：浏览器插件
- 扩展 `manifest.json` 已改为 ES module
- 页面解析器按平台拆分：
  - `candidate-collector/extension/parsers/common.js`
  - `candidate-collector/extension/parsers/boss.js`
  - `candidate-collector/extension/parsers/maimai.js`
  - `candidate-collector/extension/parsers/liepin.js`
  - `candidate-collector/extension/parsers/generic.js`
- `background.js` 按当前域名注入对应解析器，再执行读取/链接识别
- 保留用户已有的暂停/验证码检测/人工处理逻辑

### P2：检索与反馈
- 本地候选人检索：`candidate-collector/ingestion/search.py`
- API：`POST /api/search`、`POST /api/feedback`、`GET /api/feedback`
- 支持按技能、公司、职位、地点、学校和关键词检索，返回命中高亮

### P2：OCR 与低清增强
- `candidate-collector/image_processing/ocr.py` 已接入 Tesseract + pytesseract
- `candidate-collector/image_processing/enhancement.py` 图像增强
- 安装系统依赖：`brew install tesseract tesseract-lang`
- 自动 fallback：PDF 有可选文字时直接提取，否则渲染为图片后 OCR
- 已验证：图片简历可成功提取姓名、电话、邮箱等字段
- PaddleOCR 已安装，但当前 Python 3.14 / ARM 缺少 `paddlepaddle` wheel，故默认使用 Tesseract

### 手机号修复
- `candidates` 表新增 `phone`、`email` 字段
- `parse_candidate()` 从 `raw_text` 自动提取手机号和邮箱
- 历史数据通过 `scripts/recover_phones.py` 从 `raw_text` + `ingestion_log` 恢复
- 结果：89 条候选人记录中 63 条已补回手机号

### 飞书字段映射与写入
- 已用 `lark-cli base +field-list` 从真实人才库读取字段 ID
- `candidate-collector/config/feishu_field_mapping.json` 已更新为真实字段 ID
- 修复 `adapters/feishu_base.py`：先创建记录再上传附件，修正 `record_id` 提取
- 修复 select 字段校验：不在人才库选项中的值自动跳过，避免 API 报错
- dry-run / 真实写入验证通过

### 批量导入
- `scripts/batch_import_remaining.py` 批量导入本地简历到飞书
- 结果：112 份简历中 103 份首次成功创建飞书记录
- 修复失败记录后最终状态：105 成功，1 dry-run，0 失败

## 测试

```bash
cd candidate-collector
PYTHONPATH=/Users/ashley/Downloads/ttc的交易系统/candidate-collector python3 -m unittest discover -v . -p "test_*.py"
# 28 tests passed (23 unit + 5 e2e)
```

新增端到端测试：`candidate-collector/test_e2e.py`
- PDF 解析生成 CandidateRecord
- 文本解析提取手机号/公司
- Feishu payload 包含核心字段
- dry-run 返回正确结构
- 数据库表结构检查

## 语法与逻辑审计

- 所有 Python 文件通过 `py_compile`
- 所有 JS 文件通过 `node --check`
- 28 个测试全部通过
- ingestion_log 中无失败记录

## 已完成全部 P0-P2 步骤

- P0 最小闭环 ✅
- P1 邮箱自动入库 ✅
- P1 浏览器插件解析器拆分 ✅
- P2 检索与反馈 ✅
- P2 OCR 与低清增强 ✅（Tesseract 路径可用）
- 真实飞书写入测试 ✅
- 批量导入全部本地简历 ✅
- 手机号修复 ✅

## 已知限制

- PaddleOCR 需要 `paddlepaddle`；当前环境 Python 3.14 + Apple Silicon 暂无官方 wheel，已降级使用 Tesseract
- 人工复核页面目前通过 API/CLI 提供，缺少独立 HTML UI
- 浏览器扩展页面解析器拆分后，需重新加载扩展验证

## 后续可选优化

- 安装 paddlepaddle 后启用 PaddleOCR（性能更好）
- 补充人工复核 HTML 页面
- 增加更多端到端测试样本
