# MarkSnip → ot小插件 云端人才库（Webhook 接入）

整页剪藏（Readability + Turndown → Markdown）直接 POST 到 ot小插件的云端入库接口，
与浏览器插件走同一个 `cloud_candidates` 表、同一套解析与指纹判重。

## 链路

```
当前页面 → MarkSnip 剪藏为 Markdown
        → Webhook POST https://yorkteam.cn/api/ot-plugin/import-browser-capture
        → cloud_gateway 校验 X-OT-Token
        → unified_parser 解析 + 指纹判重
        → upsert ttc_talent.cloud_candidates（source_type = marksnip_webhook）
```

MarkSnip 的 `host_permissions` 含 `<all_urls>`，其 Service Worker 直连网关不受 CORS 限制。

## MarkSnip 配置（一次性）

MarkSnip 选项页 → Webhook Targets → Add Webhook Target：

| 字段 | 值 |
|---|---|
| Target Name | `ot小插件云端人才库` |
| URL | `https://yorkteam.cn/api/ot-plugin/import-browser-capture` |
| Method | `POST` |
| Header 1 | `Content-Type: application/json` |
| Header 2 | `X-OT-Token: <取 candidate-collector/extension/cloud_runtime.json 的 apiToken>` |

Body Template (JSON)：

```json
{
  "url": "{pageURL}",
  "title": "{title}",
  "heading": "{title}",
  "text": "{content}",
  "platform": "",
  "source_type": "marksnip_webhook"
}
```

保存后，在任意页面打开 MarkSnip 弹窗 → 选择该 Webhook 目标发送，即完成整页入库。

> Token 不要写进任何会提交 git 的文件；以 `cloud_runtime.json`（已 gitignore）为准。

## 字段契约

- `text` 必填，10–600000 字符（对应 `BrowserCapturePayload.text`）
- `platform` 留空时网关用 `source_type` 兜底
- 可用模板变量：`{content}` `{title}` `{pageURL}` `{excerpt}` `{byline}` `{keywords}` `{publishedTime}`
- 判重幂等：同一页面重复发送只会更新同一条记录（fingerprint 不变）

## 已知限制

- 网关解析目前是正则版 `unified_parser`：整页噪声较多时姓名/公司可能误识别，
  此类记录会标 `needs_review`，在审核页人工确认即可。
- 网关暂不支持 `dry_run`（字段会被忽略，发送即真实 upsert）。
- 后续要把「整页 Markdown → AI 精读 → 结构化字段」接进来时，
  在 `cloud_gateway.py` 增加一路 AI 解析即可，webhook 配置不变。
