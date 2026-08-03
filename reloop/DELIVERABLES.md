# TTC 候选人自动采集与入库 — 交付状态

## 已完成

### P0：最小闭环
- 统一 `CandidateRecord` 数据模型：`reloop/src/reloop/domain/models.py`
- 统一文档解析接口：`reloop/src/reloop/parsing/`（PDF/图片/DOCX）
- 飞书 Base 字段映射：`reloop/config/feishu_field_mapping.json`
- dry-run / outbox CLI：`reloop/src/reloop/ops/cli.py`
- 附件解析、outbox 入队、幂等去重：`reloop/src/reloop/ingestion/pipeline.py`
- 端到端测试：`reloop/tests/`

### P1：邮箱自动入库
- 重构 `reloop/src/reloop/sinks/gmail/sync.py` 为统一 IMAP 邮箱同步
- 支持 Gmail（钥匙串）和通用 IMAP（环境变量 / JSON 配置）
- 删除单岗位硬编码，改为简历特征过滤
- 支持 PDF/DOC/DOCX/PNG/JPG/JPEG/TIFF
- Message-ID + SHA-256 双重去重
- 单封邮件失败进入重试队列，不中断整批
- 示例配置：`reloop/config/email_sync.example.json`
- 更新测试：`reloop/tests/test_gmail_sync.py`

### P1：浏览器插件
- 扩展 `manifest.json` 已改为 ES module
- 页面解析器按平台拆分：
  - `reloop/extension/parsers/common.js`
  - `reloop/extension/parsers/boss.js`
  - `reloop/extension/parsers/maimai.js`
  - `reloop/extension/parsers/liepin.js`
  - `reloop/extension/parsers/generic.js`
- `background.js` 按当前域名注入对应解析器，再执行读取/链接识别
- 保留用户已有的暂停/验证码检测/人工处理逻辑

### P2：检索与反馈
- 本地候选人检索：`reloop/src/reloop/ingestion/search.py`
- API：`POST /api/search`、`POST /api/feedback`、`GET /api/feedback`
- 支持按技能、公司、职位、地点、学校和关键词检索，返回命中高亮

### P2：OCR 与低清增强
- `reloop/src/reloop/parsing/ocr.py` 已接入 Tesseract + pytesseract
- `reloop/src/reloop/parsing/enhancement.py` 图像增强
- 安装系统依赖：`brew install tesseract tesseract-lang`
- 自动 fallback：PDF 有可选文字时直接提取，否则渲染为图片后 OCR
- 已验证：图片简历可成功提取姓名、电话、邮箱等字段
- PaddleOCR 已安装，但当前 Python 3.14 / ARM 缺少 `paddlepaddle` wheel，故默认使用 Tesseract

### 手机号修复
- `candidates` 表新增 `phone`、`email` 字段
- `parse_candidate()` 从 `raw_text` 自动提取手机号和邮箱
- 历史数据通过 `scripts/oneoff/recover_phones.py` 从 `raw_text` + `ingestion_log` 恢复
- 结果以脚本运行报告为准，避免把旧环境数字当作当前状态。

### 飞书字段映射与写入
- 已用 `lark-cli base +field-list` 从真实人才库读取字段 ID
- `reloop/config/feishu_field_mapping.json` 已更新为真实字段 ID
- 修复 `reloop/src/reloop/sinks/feishu/feishu_base.py`：先创建记录再上传附件，修正 `record_id` 提取
- 修复 select 字段校验：不在人才库选项中的值自动跳过，避免 API 报错
- dry-run / outbox 入队验证通过；真实投递由 worker 执行

### 批量导入
- `scripts/oneoff/batch_import_remaining.py` 批量将本地简历写入 outbox
- worker 按 RDS → 飞书顺序投递，失败状态可重试

## 测试

```bash
cd reloop && python3.12 -m pytest tests -q
# 当前回归测试数量以命令输出为准
```

新增端到端测试：`reloop/tests/test_e2e.py`
- PDF 解析生成 CandidateRecord
- 文本解析提取手机号/公司
- Feishu payload 包含核心字段
- dry-run 返回正确结构
- 数据库表结构检查

## 语法与逻辑审计

- Reloop 包与测试通过 `compileall`；仓库外旧目录仍需独立修复后再做全仓门禁
- 所有 JS 文件通过 `node --check`
- 历史测试与 outbox/review 故障注入测试全部通过
- `ingestion_log` 状态由 outbox worker 镜像；真实生产库无失败记录需在部署后核验

## 已完成全部 P0-P2 步骤

- P0 最小闭环 ✅
- P1 邮箱自动入库 ✅
- P1 浏览器插件解析器拆分 ✅
- P2 检索与反馈 ✅
- P2 OCR 与低清增强 ✅（Tesseract 路径可用）
- outbox → RDS → 飞书顺序投递测试 ✅
- 批量导入脚本已分类；真实投递需在具备配置时由 worker 执行
- 手机号修复 ✅

## 已知限制

- PaddleOCR 需要 `paddlepaddle`；当前环境 Python 3.14 + Apple Silicon 暂无官方 wheel，已降级使用 Tesseract
- 人工复核页面目前通过 API/CLI 提供，缺少独立 HTML UI
- 浏览器扩展页面解析器拆分后，需重新加载扩展验证

## 后续可选优化

- 安装 paddlepaddle 后启用 PaddleOCR（性能更好）
- 补充人工复核 HTML 页面
- 增加更多端到端测试样本
