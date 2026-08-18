const IMPORT_API_V2 = 'http://127.0.0.1:8765/api/import-browser-capture-v2';
const HEALTH_API = 'http://127.0.0.1:8765/api/health';
const EXTENSION_VERSION = '0.7.3';
const MAX_PDF_BYTES = 50 * 1024 * 1024;

const ENDPOINTS = {
  ttc: [
    '/api/talent_store/v1/person_leads/basic_info',
    '/api/talent_store/v1/person_leads/resume/attachment/list'
  ],
  maimai: [
    '/api/ent/talent/basic',
    '/sdk/jobs/anti_automation/talent/basic',
    '/api/ent/card/console/intelligence/screen',
    '/api/ent/v3/search/basic',
    '/api/ent/candidate/project/apply',
    '/api/ent/candidate/project/list'
  ]
};

const getState = () => chrome.storage.local.get('batch').then(data => data.batch || {
  running: false,
  current: '',
  message: '空闲',
  lastResult: null
});

const setState = state => chrome.storage.local.set({batch: state}).then(() => state);

function isMaimaiHost(hostname) {
  return hostname === 'maimai.cn' || hostname.endsWith('.maimai.cn');
}

function senderContext(sender) {
  const rawUrl = sender && (sender.url || (sender.tab && sender.tab.url));
  if (!rawUrl) throw new Error('缺少扩展消息来源');
  const url = new URL(rawUrl);
  if (url.protocol !== 'https:') throw new Error('只接受 HTTPS 候选人页面');
  if (url.hostname === 'app.ttcadvisory.com') return {platform: 'ttc', url};
  if (isMaimaiHost(url.hostname)) {
    return {platform: 'maimai', url};
  }
  throw new Error('消息不是来自已授权的 TTC/脉脉页面');
}

function validateCapturePayload(rawPayload, sender) {
  if (!rawPayload || typeof rawPayload !== 'object' || Array.isArray(rawPayload)) {
    throw new Error('候选人 capture 必须是对象');
  }
  const context = senderContext(sender);
  if (rawPayload.platform !== context.platform) throw new Error('候选人平台与页面不匹配');

  const id = String(rawPayload.source_candidate_id || '').trim().slice(0, 200);
  if (!id) throw new Error('缺少稳定候选人 ID');
  if (context.platform === 'ttc') {
    if (!/^(?:PL)?\d+$/i.test(id)) throw new Error('TTC 候选人 ID 格式无效');
    const routeId = context.url.pathname.match(/\/app\/talent\/((?:PL)?\d+)/i);
    if (!routeId || routeId[1].toUpperCase() !== id.toUpperCase()) {
      throw new Error('TTC 候选人 ID 与详情页不匹配');
    }
  } else {
    if (!/^[0-9A-Za-z:_-]+$/.test(id)) throw new Error('脉脉候选人 ID 格式无效');
    const requestUrl = new URL(String(rawPayload.capture_request_url || ''), context.url.origin);
    if (
      requestUrl.protocol !== 'https:'
      || !isMaimaiHost(requestUrl.hostname)
      || !ENDPOINTS.maimai.some(endpoint => requestUrl.pathname.includes(endpoint))
    ) {
      throw new Error('脉脉 capture 不来自候选人白名单接口');
    }
  }

  const text = String(rawPayload.text || '');
  if (text.length < 10 || text.length > 600000) throw new Error('候选人文本长度无效');
  const resume = rawPayload.resume && typeof rawPayload.resume === 'object'
    ? Object.assign({}, rawPayload.resume) : null;
  if (resume && resume.file_url) {
    const pdfUrl = new URL(String(resume.file_url));
    if (pdfUrl.protocol !== 'https:') throw new Error('PDF 地址必须使用 HTTPS');
    resume.file_url = pdfUrl.href;
    resume.file_name = String(resume.file_name || 'resume.pdf').slice(0, 180);
  }

  const payload = Object.assign({}, rawPayload, {
    schema_version: '2',
    platform: context.platform,
    source_candidate_id: context.platform === 'ttc' ? id.toUpperCase() : id,
    url: context.platform === 'ttc'
      ? `https://app.ttcadvisory.com/app/talent/${id.toUpperCase()}`
      : `${context.url.origin}${context.url.pathname}#candidate=${encodeURIComponent(id)}`,
    text,
    resume,
    source_type: 'browser_auto_import',
    dry_run: false,
    skip_duplicates: true,
    check_feishu_exists: false
  });
  delete payload.capture_request_url;
  return payload;
}

function compactResult(data, payload) {
  return {
    action: data.action || (data.ok ? 'created' : 'failed'),
    feishu_record_id: data.feishu_record_id || null,
    feishu_table_id: data.feishu_table_id || null,
    attachment_uploaded: Boolean(data.attachment_uploaded),
    fallback_reason: data.fallback_reason || null,
    source_candidate_id: payload.source_candidate_id
  };
}

async function saveStatus(data, payload) {
  const result = compactResult(data, payload);
  await setState({
    running: false,
    current: payload.source_candidate_id,
    message: result.action,
    lastResult: result,
    updatedAt: new Date().toISOString()
  });
}

async function importFeishuV2FromPayload(payload, pdfBlob = null, fileName = 'resume.pdf') {
  const form = new FormData();
  form.append('capture', JSON.stringify(payload));
  if (pdfBlob) form.append('resume_pdf', pdfBlob, String(fileName || 'resume.pdf').slice(0, 180));
  const response = await fetch(IMPORT_API_V2, {method: 'POST', body: form});
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || data.error || '飞书自动导入失败');
  await saveStatus(data, payload);
  return data;
}

async function checkBackendHealth() {
  const response = await fetch(HEALTH_API);
  const data = await response.json().catch(() => ({}));
  if (!response.ok || !data.ok) throw new Error(data.detail || '本地服务不可用');
  return data;
}

function decodeBase64(value) {
  if (typeof value !== 'string' || value.length > 400000) throw new Error('PDF 分片无效');
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes;
}

chrome.runtime.onConnect.addListener(port => {
  if (port.name !== 'ttc-pdf-upload-v2') return;
  let upload = null;

  const fail = error => {
    upload = null;
    port.postMessage({type: 'error', error: error && error.message || 'PDF 上传失败'});
  };

  port.onMessage.addListener(message => {
    void (async () => {
      if (!message || typeof message !== 'object') throw new Error('PDF 上传消息无效');
      if (message.type === 'begin') {
        const totalBytes = Number(message.total_bytes);
        if (!Number.isInteger(totalBytes) || totalBytes <= 0 || totalBytes > MAX_PDF_BYTES) {
          throw new Error('PDF 大小无效');
        }
        upload = {
          payload: validateCapturePayload(message.payload, port.sender),
          fileName: String(message.file_name || 'resume.pdf').slice(0, 180),
          totalBytes,
          received: 0,
          chunks: []
        };
        port.postMessage({type: 'ready'});
        return;
      }
      if (!upload) throw new Error('PDF 上传尚未初始化');
      if (message.type === 'chunk') {
        if (message.index !== upload.chunks.length) throw new Error('PDF 分片顺序无效');
        const bytes = decodeBase64(message.data);
        upload.received += bytes.byteLength;
        if (upload.received > upload.totalBytes || upload.received > MAX_PDF_BYTES) {
          throw new Error('PDF 分片超过声明大小');
        }
        upload.chunks.push(bytes);
        port.postMessage({type: 'ack', index: message.index});
        return;
      }
      if (message.type === 'finish') {
        if (upload.received !== upload.totalBytes) throw new Error('PDF 分片不完整');
        const current = upload;
        upload = null;
        const result = await importFeishuV2FromPayload(
          current.payload,
          new Blob(current.chunks, {type: 'application/pdf'}),
          current.fileName
        );
        port.postMessage({type: 'result', result});
        return;
      }
      throw new Error('未知 PDF 上传操作');
    })().catch(fail);
  });

  port.onDisconnect.addListener(() => { upload = null; });
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  void (async () => {
    if (!message || typeof message !== 'object') return {ok: false, error: '消息无效'};
    if (message.type === 'autoImportPayload') {
      const payload = validateCapturePayload(message.payload, sender);
      const result = await importFeishuV2FromPayload(payload);
      return Object.assign({ok: Boolean(result.ok)}, result);
    }
    if (message.type === 'checkBackend') {
      return {ok: true, health: await checkBackendHealth()};
    }
    if (message.type === 'ping') return {ok: true, version: EXTENSION_VERSION};
    if (message.type === 'getStatus') return {ok: true, state: await getState()};
    return {ok: false, error: '未知操作'};
  })().then(sendResponse).catch(error => sendResponse({ok: false, error: error.message}));
  return true;
});

chrome.runtime.onInstalled.addListener(() => {
  setState({running: false, current: '', message: '空闲', lastResult: null});
});
