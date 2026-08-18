/** Automatic TTC/Maimai import in the extension's isolated world. */
(function () {
  'use strict';
  const STATUS_ID = 'ttc-auto-import-status';
  const states = new Map();
  const imported = new Map();
  const pdfRequests = new Map();
  const RETRY_POLICY = globalThis.__TTC_RETRY_POLICY;
  const captureChannel = new MessageChannel();
  captureChannel.port1.onmessage = handleCaptureChannelMessage;
  captureChannel.port1.start();
  window.postMessage({type: 'TTC_CAPTURE_PORT_INIT_V2'}, location.origin, [captureChannel.port2]);

  function showStatus(message, type = 'info') {
    if (!document.body) return;
    let element = document.getElementById(STATUS_ID);
    if (!element) {
      element = document.createElement('div');
      element.id = STATUS_ID;
      element.style.cssText = [
        'position:fixed', 'right:24px', 'bottom:24px', 'z-index:2147483640',
        'max-width:340px', 'padding:12px 16px', 'border-radius:10px',
        'color:#fff', 'font:13px/1.5 system-ui', 'box-shadow:0 4px 16px rgba(0,0,0,.22)'
      ].join(';');
      document.body.appendChild(element);
    }
    element.textContent = message;
    element.dataset.state = type;
    element.style.background = type === 'error' ? '#a34734' :
      type === 'success' ? '#0d6f63' : type === 'queued' ? '#8a5a00' : '#3e7bf4';
    element.style.opacity = '1';
  }

  function runtimeMessage(message) {
    return new Promise((resolve, reject) => {
      chrome.runtime.sendMessage(message, response => {
        if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
        resolve(response || {ok: false, error: '扩展后台无响应'});
      });
    });
  }

  function ttcIdFromUrl() {
    const match = location.pathname.match(/\/app\/talent\/((?:PL)?\d+)/i);
    return match ? match[1].toUpperCase() : '';
  }

  function capturePayload(state) {
    const text = document.body ? document.body.innerText : '';
    const sourceUrl = state.platform === 'ttc'
      ? `https://app.ttcadvisory.com/app/talent/${state.id}`
      : `${location.origin}${location.pathname}#candidate=${encodeURIComponent(state.id)}`;
    return {
      schema_version: '2',
      platform: state.platform,
      source_candidate_id: state.id,
      url: sourceUrl,
      title: document.title || '',
      heading: (document.querySelector('h1') && document.querySelector('h1').innerText) || '',
      text: text.length >= 10 ? text.slice(0, 600000) : `候选人 ${state.id} 的结构化资料`,
      source_type: 'browser_auto_import',
      captured_at: new Date().toISOString(),
      profile: state.profile || {},
      resume: state.resume || null,
      capture_request_url: state.requestUrl || '',
      structured_data: {sections: [{heading: '平台可见资料', text: text.slice(0, 580000)}]},
      skip_duplicates: true,
      check_feishu_exists: false
    };
  }

  function fetchAuthorizedPdf(resume) {
    return new Promise((resolve, reject) => {
      const requestId = crypto.randomUUID();
      const timer = setTimeout(() => {
        pdfRequests.delete(requestId);
        reject(new Error('浏览器获取PDF超时'));
      }, 30000);
      pdfRequests.set(requestId, {resolve, reject, timer, resume});
      captureChannel.port1.postMessage({
        type: 'TTC_FETCH_AUTHORIZED_PDF_V2',
        request_id: requestId,
        url: resume.file_url,
        file_name: resume.file_name || 'resume.pdf'
      });
    });
  }

  function base64Chunk(buffer, start, end) {
    const bytes = new Uint8Array(buffer, start, end - start);
    let binary = '';
    for (let offset = 0; offset < bytes.length; offset += 0x8000) {
      binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
    }
    return btoa(binary);
  }

  function uploadWithPdf(payload, pdf) {
    return new Promise((resolve, reject) => {
      const port = chrome.runtime.connect({name: 'ttc-pdf-upload-v2'});
      const chunkSize = 192 * 1024;
      let nextOffset = 0;
      let nextIndex = 0;
      let settled = false;
      const fail = error => {
        if (settled) return;
        settled = true;
        try { port.disconnect(); } catch (_ignored) {}
        reject(error instanceof Error ? error : new Error(String(error || 'PDF上传失败')));
      };
      const sendNext = () => {
        if (nextOffset >= pdf.buffer.byteLength) {
          port.postMessage({type: 'finish'});
          return;
        }
        const end = Math.min(nextOffset + chunkSize, pdf.buffer.byteLength);
        port.postMessage({
          type: 'chunk',
          index: nextIndex,
          data: base64Chunk(pdf.buffer, nextOffset, end)
        });
        nextOffset = end;
        nextIndex += 1;
      };
      port.onMessage.addListener(message => {
        if (!message || typeof message !== 'object') return;
        if (message.type === 'ready' || message.type === 'ack') return sendNext();
        if (message.type === 'error') return fail(new Error(message.error || 'PDF上传失败'));
        if (message.type === 'result') {
          if (settled) return;
          settled = true;
          port.disconnect();
          resolve(message.result || {ok: false, error: 'PDF上传无结果'});
        }
      });
      port.onDisconnect.addListener(() => {
        if (settled) return;
        fail(new Error(
          chrome.runtime.lastError?.message || '扩展后台已断开，PDF上传未完成'
        ));
      });
      port.postMessage({
        type: 'begin',
        payload,
        file_name: pdf.fileName,
        total_bytes: pdf.buffer.byteLength
      });
    });
  }

  async function importState(state, forceAttachment = false) {
    if (state.running) return;
    const prior = imported.get(state.key);
    if (prior && (!forceAttachment || prior.attachmentUploaded)) return;
    state.running = true;
    const payload = capturePayload(state);
    showStatus(`${state.platform === 'ttc' ? 'TTC' : '脉脉'}：正在导入 ${state.id}…`);
    try {
      let result = await runtimeMessage({type: 'autoImportPayload', payload});
      if (result.action === 'needs_browser_pdf' && state.resume && state.resume.file_url) {
        showStatus('结构化资料已就绪，正在获取PDF原件…');
        try {
          const pdf = await fetchAuthorizedPdf(state.resume);
          result = await uploadWithPdf(payload, pdf);
        } catch (error) {
          payload.pdf_fetch_failed_reason = error.message;
          result = await runtimeMessage({type: 'autoImportPayload', payload});
        }
      }
      if (!result.ok) throw new Error(result.error || result.action || '自动导入失败');
      const table = result.feishu_table_id === 'tblEHeMS9wk6g0ui' ? 'Otto2' : 'Otto1';
      const attachmentUploaded = Boolean(result.attachment_uploaded || result.action === 'attachment_uploaded');
      imported.set(state.key, {attachmentUploaded, action: result.action});
      const label = result.action && result.action.includes('duplicate') ? '已存在，跳过重复' :
        result.action === 'attachment_uploaded' ? '已补传PDF原件' : '已写入';
      showStatus(`${label} · ${table} · ${state.id}${attachmentUploaded ? ' · PDF✓' : ' · 无PDF'}`, 'success');
      state.retries = 0;
    } catch (error) {
      state.retries = (state.retries || 0) + 1;
      const shouldRetry = RETRY_POLICY.shouldKeepRetrying(error, state.retries);
      const retryMs = RETRY_POLICY.delayMs(state.retries);
      showStatus(
        shouldRetry
          ? `导入暂未完成，已保留任务，${Math.round(retryMs / 1000)}秒后重试：${error.message}`
          : `导入失败：${error.message}`,
        shouldRetry ? 'queued' : 'error'
      );
      if (shouldRetry) {
        clearTimeout(state.retryTimer);
        state.retryTimer = setTimeout(() => importState(state, forceAttachment), retryMs);
      }
    } finally {
      state.running = false;
    }
  }

  function schedule(state) {
    clearTimeout(state.timer);
    const age = Date.now() - state.firstSeen;
    const waitForResume = !state.resume && age < 8000;
    state.timer = setTimeout(() => {
      if (waitForResume) return schedule(state);
      importState(state, Boolean(state.resume));
    }, waitForResume ? Math.min(1500, 8000 - age) : 2000);
  }

  function handleCandidateMessage(message) {
    if (!message || message.type !== 'TTC_AUTHORIZED_CANDIDATE_V2' ||
        message.schema_version !== '2') return;
    if (!['ttc', 'maimai'].includes(message.platform) || !message.source_candidate_id) return;
    const id = String(message.source_candidate_id).slice(0, 200);
    const key = `${message.platform}:${id}`;
    const state = states.get(key) || {
      key, id, platform: message.platform, firstSeen: Date.now(), profile: null, resume: null
    };
    if (message.profile) state.profile = message.profile;
    if (message.resume) state.resume = message.resume;
    if (message.request_url) state.requestUrl = message.request_url;
    states.set(key, state);
    schedule(state);
  }

  function handleCaptureChannelMessage(event) {
    const message = event.data;
    if (!message || typeof message !== 'object') return;
    if (message.type === 'TTC_AUTHORIZED_CANDIDATE_V2') {
      handleCandidateMessage(message);
      return;
    }
    if (message.type !== 'TTC_AUTHORIZED_PDF_V2') return;
    const pending = pdfRequests.get(message.request_id);
    if (!pending) return;
    pdfRequests.delete(message.request_id);
    clearTimeout(pending.timer);
    if (!message.ok) {
      pending.reject(new Error(message.error || '浏览器获取PDF失败'));
      return;
    }
    pending.resolve({
      buffer: message.buffer,
      fileName: message.file_name || pending.resume.file_name || 'resume.pdf'
    });
  }

  function seedTtcRoute() {
    if (location.hostname !== 'app.ttcadvisory.com') return;
    const id = ttcIdFromUrl();
    if (!id) return;
    const key = `ttc:${id}`;
    if (!states.has(key)) {
      const state = {key, id, platform: 'ttc', firstSeen: Date.now(), profile: null, resume: null};
      states.set(key, state);
      schedule(state);
    }
  }

  let lastUrl = location.href;
  new MutationObserver(() => {
    if (location.href !== lastUrl) {
      lastUrl = location.href;
      seedTtcRoute();
    }
  }).observe(document.documentElement, {childList: true, subtree: true});
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', seedTtcRoute, {once: true});
  } else {
    seedTtcRoute();
  }
})();
