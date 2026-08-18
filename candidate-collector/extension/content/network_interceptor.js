/** Observe only authorized TTC/Maimai API responses in the page's MAIN world. */
(function () {
  'use strict';
  // Authentication pages are outside candidate capture scope.  More importantly,
  // wrapping fetch/XHR there can conflict with Maimai's login SPA and leave Atlas
  // showing a blank page.  Keep this runtime guard in addition to manifest excludes
  // so an already-loaded or stale extension worker still fails closed.
  if (/(^|\/)platform\/login\/?$/.test(location.pathname)) return;
  if (window.__TTC_CAPTURE_INTERCEPTOR_V2) return;
  window.__TTC_CAPTURE_INTERCEPTOR_V2 = true;

  const EVENT = 'TTC_AUTHORIZED_CANDIDATE_V2';
  let capturePort = null;
  const pendingMessages = [];
  const platform = /(^|\.)maimai\.cn$/.test(location.hostname) ? 'maimai' :
    location.hostname === 'app.ttcadvisory.com' ? 'ttc' : '';
  if (!platform) return;

  const TTC_ENDPOINTS = [
    '/api/talent_store/v1/person_leads/basic_info',
    '/api/talent_store/v1/person_leads/resume/attachment/list'
  ];
  const MAIMAI_ENDPOINTS = [
    '/api/ent/talent/basic',
    '/sdk/jobs/anti_automation/talent/basic',
    '/api/ent/card/console/intelligence/screen',
    '/api/ent/v3/search/basic',
    '/api/ent/candidate/project/apply',
    '/api/ent/candidate/project/list'
  ];

  function interesting(url) {
    const value = String(url || '');
    const endpoints = platform === 'ttc' ? TTC_ENDPOINTS : MAIMAI_ENDPOINTS;
    return endpoints.some(endpoint => value.includes(endpoint));
  }

  function parseBody(body) {
    if (!body) return {};
    if (typeof body === 'string') {
      try { return JSON.parse(body); } catch (_error) {
        try { return Object.fromEntries(new URLSearchParams(body)); } catch (_ignored) { return {}; }
      }
    }
    return {};
  }

  function findValue(value, keys, depth = 0) {
    if (depth > 6 || value == null) return null;
    if (Array.isArray(value)) {
      for (const item of value.slice(0, 30)) {
        const found = findValue(item, keys, depth + 1);
        if (found != null && found !== '') return found;
      }
      return null;
    }
    if (typeof value !== 'object') return null;
    for (const [key, item] of Object.entries(value)) {
      if (keys.has(key.toLowerCase()) && item != null && item !== '') return item;
    }
    for (const item of Object.values(value)) {
      const found = findValue(item, keys, depth + 1);
      if (found != null && found !== '') return found;
    }
    return null;
  }

  function candidateId(data, body, url) {
    if (platform === 'ttc') {
      const value = findValue(body, new Set(['person_leads_id'])) ||
        findValue(data, new Set(['person_leads_id']));
      if (value) return String(value).toUpperCase();
      const match = String(url || location.href).match(/\/talent\/((?:PL)?\d+)/i);
      return match ? match[1].toUpperCase() : '';
    }
    const strongKeys = new Set(['to_uid', 'talent_id', 'candidate_id', 'user_id', 'uid']);
    const value = findValue(body, strongKeys) || findValue(data, strongKeys);
    return value == null ? '' : String(value);
  }

  function resumeMetadata(data) {
    const objects = [];
    const visit = (value, depth = 0) => {
      if (depth > 7 || value == null) return;
      if (Array.isArray(value)) {
        value.slice(0, 50).forEach(item => visit(item, depth + 1));
        return;
      }
      if (typeof value !== 'object') return;
      objects.push(value);
      Object.values(value).forEach(item => visit(item, depth + 1));
    };
    visit(data);
    for (const item of objects) {
      const url = item.file_url || item.link || item.preview_url || item.download_url;
      if (!url || typeof url !== 'string') continue;
      let absolute = '';
      try { absolute = new URL(url, location.origin).href; } catch (_error) { continue; }
      if (!absolute.startsWith('https://')) continue;
      return {
        file_url: absolute,
        file_name: String(item.file_name || item.attach_filename || item.name || 'resume.pdf')
      };
    }
    return null;
  }

  function compact(value) {
    try {
      const text = JSON.stringify(value);
      if (text.length <= 500000) return JSON.parse(text);
    } catch (_error) {}
    return {};
  }

  function postToExtension(message, transfer = []) {
    if (!capturePort) {
      if (pendingMessages.length < 20) pendingMessages.push([message, transfer]);
      return;
    }
    capturePort.postMessage(message, transfer);
  }

  function emit(url, body, response) {
    const data = response && Object.prototype.hasOwnProperty.call(response, 'data')
      ? response.data : response;
    const id = candidateId(data, body, url);
    if (!id) return;
    const isDetail = platform === 'ttc'
      ? String(url).includes('/person_leads/basic_info')
      : /talent\/basic/.test(String(url));
    const resume = resumeMetadata(data);
    if (!isDetail && !resume) return;
    postToExtension({
      type: EVENT,
      schema_version: '2',
      platform,
      source_candidate_id: id,
      request_url: String(url),
      profile: isDetail ? compact(data) : null,
      resume,
      captured_at: new Date().toISOString()
    });
  }

  async function inspectResponse(url, body, response) {
    if (!interesting(url)) return;
    try { emit(url, body, await response.clone().json()); } catch (_error) {}
  }

  const originalFetch = window.fetch;
  window.fetch = async function (input, init) {
    const url = typeof input === 'string' ? input : input && input.url;
    const body = parseBody(init && init.body);
    const response = await originalFetch.apply(this, arguments);
    void inspectResponse(url, body, response);
    return response;
  };

  const originalOpen = XMLHttpRequest.prototype.open;
  const originalSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (_method, url) {
    this.__ttcCaptureUrl = String(url || '');
    return originalOpen.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function (body) {
    const parsedBody = parseBody(body);
    if (interesting(this.__ttcCaptureUrl)) {
      this.addEventListener('load', () => {
        try { emit(this.__ttcCaptureUrl, parsedBody, JSON.parse(this.responseText)); } catch (_error) {}
      }, {once: true});
    }
    return originalSend.apply(this, arguments);
  };

  async function handlePortMessage(event) {
    const message = event.data;
    if (!message || message.type !== 'TTC_FETCH_AUTHORIZED_PDF_V2') return;
    try {
      const url = new URL(message.url);
      if (url.protocol !== 'https:' || /^(localhost|127\.)/.test(url.hostname)) {
        throw new Error('invalid PDF URL');
      }
      const response = await originalFetch(url.href, {credentials: 'include'});
      if (!response.ok) throw new Error('HTTP ' + response.status);
      const buffer = await response.arrayBuffer();
      if (buffer.byteLength > 50 * 1024 * 1024) throw new Error('PDF exceeds 50 MiB');
      const magic = new TextDecoder().decode(buffer.slice(0, 5));
      if (magic !== '%PDF-') throw new Error('response is not PDF');
      postToExtension({
        type: 'TTC_AUTHORIZED_PDF_V2',
        request_id: message.request_id,
        ok: true,
        buffer,
        file_name: message.file_name || 'resume.pdf'
      }, [buffer]);
    } catch (error) {
      postToExtension({
        type: 'TTC_AUTHORIZED_PDF_V2',
        request_id: message.request_id,
        ok: false,
        error: error && error.message || 'PDF download failed'
      });
    }
  }

  window.addEventListener('message', event => {
    if (
      capturePort
      || event.source !== window
      || event.origin !== location.origin
      || !event.data
      || event.data.type !== 'TTC_CAPTURE_PORT_INIT_V2'
      || !event.ports
      || !event.ports[0]
    ) return;
    capturePort = event.ports[0];
    capturePort.onmessage = handlePortMessage;
    capturePort.start();
    for (const [message, transfer] of pendingMessages.splice(0)) {
      capturePort.postMessage(message, transfer);
    }
  }, {once: false});
})();
