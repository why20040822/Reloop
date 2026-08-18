// ==UserScript==
// @name         TTC 飞书网页助手：群消息读取与本地处理
// @namespace    https://local.ttc/candidate-collector
// @version      0.1.0
// @description  读取当前账号已授权可见的飞书/Lark 网页消息，发送到本地 candidate-collector，并把本地生成的回复填回输入框。默认只填草稿，不自动发送。
// @author       TTC + Codex
// @match        *://*.feishu.cn/*
// @match        *://*.larksuite.com/*
// @match        *://*.larkoffice.com/*
// @run-at       document-idle
// @grant        GM_addStyle
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_registerMenuCommand
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// @connect      localhost
// ==/UserScript==

(function () {
  'use strict';

  const DEFAULTS = {
    enabled: true,
    daemon: 'http://127.0.0.1:8765',
    clientId: 'default',
    autoFillDraft: true,
    autoSend: false,
    captureAll: false,
    pollSeconds: 5,
    scanSeconds: 2,
  };
  const STORAGE_KEY = 'ttc_feishu_web_bridge_v1';
  const TRIGGERS = [
    '简历', '候选人', '面试', '招聘', '猎头', 'JD', '岗位', '职位',
    'BOSS', 'boss', '猎聘', '脉脉', '帮我看', '评估', '推荐',
    '消费', '品牌', '战略', '投后', '咨询'
  ];
  const IGNORE_LINES = [
    '搜索', '消息', '通讯录', '云文档', '工作台', '日历', '会议',
    '稍后处理', '标记', '置顶', '全部已读', '表情回复'
  ];

  let config = loadConfig();
  let panel = null;
  let statusEl = null;
  let lastScanAt = 0;
  const seen = new Set(JSON.parse(sessionStorage.getItem('ttc_feishu_seen_messages') || '[]'));

  function loadConfig() {
    try {
      return { ...DEFAULTS, ...(GM_getValue ? GM_getValue(STORAGE_KEY, {}) : {}) };
    } catch {
      return { ...DEFAULTS };
    }
  }

  function saveConfig(next) {
    config = { ...config, ...next };
    try { GM_setValue(STORAGE_KEY, config); } catch {}
    updateStatus();
  }

  function log(...args) {
    console.log('[TTC飞书助手]', ...args);
  }

  function updateStatus(text) {
    if (!statusEl) return;
    statusEl.textContent = text || `状态：${config.enabled ? '监听中' : '已暂停'} · 草稿${config.autoFillDraft ? '开' : '关'} · 自动发送${config.autoSend ? '开' : '关'}`;
  }

  function hash(value) {
    let h = 2166136261;
    for (let i = 0; i < value.length; i += 1) {
      h ^= value.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return String(h >>> 0);
  }

  function normalizeText(value) {
    return String(value || '')
      .replace(/\u00a0/g, ' ')
      .replace(/\u200b/g, '')
      .split('\n')
      .map(line => line.replace(/\s+/g, ' ').trim())
      .filter(Boolean)
      .filter(line => !IGNORE_LINES.includes(line))
      .join('\n')
      .slice(0, 80000);
  }

  function hasIntent(text) {
    if (config.captureAll) return true;
    return TRIGGERS.some(word => text.includes(word));
  }

  function currentChatTitle() {
    const titleFromHeader = [
      '[class*="chat"] [class*="title"]',
      '[class*="conversation"] [class*="title"]',
      'header [class*="title"]',
      '[role="heading"]',
      'h1',
      'h2',
    ].map(sel => document.querySelector(sel)?.textContent?.trim()).find(Boolean);
    return normalizeText(titleFromHeader || document.title).slice(0, 300);
  }

  function candidateMessageNodes() {
    const selectors = [
      '[data-message-id]',
      '[data-e2e*="message"]',
      '[class*="messageItem"]',
      '[class*="MessageItem"]',
      '[class*="chat-message"]',
      '[class*="message-item"]',
      '[class*="message_content"]',
      '[class*="MessageContent"]',
    ];
    const nodes = new Set();
    selectors.forEach(sel => {
      document.querySelectorAll(sel).forEach(node => {
        if (node instanceof HTMLElement && node.offsetParent !== null) nodes.add(node);
      });
    });

    if (!nodes.size) {
      document.querySelectorAll('[role="listitem"], [class*="message"], [class*="Message"]').forEach(node => {
        if (!(node instanceof HTMLElement) || node.offsetParent === null) return;
        const text = normalizeText(node.innerText);
        if (text.length >= 8 && text.length <= 20000) nodes.add(node);
      });
    }
    return [...nodes];
  }

  function extractSender(text) {
    const first = text.split('\n')[0] || '';
    if (first.length <= 30 && !TRIGGERS.some(word => first.includes(word))) return first;
    return '';
  }

  function request(method, path, body) {
    const url = `${config.daemon.replace(/\/$/, '')}${path}`;
    return new Promise((resolve, reject) => {
      GM_xmlhttpRequest({
        method,
        url,
        headers: { 'Content-Type': 'application/json' },
        data: body ? JSON.stringify(body) : undefined,
        timeout: 15000,
        onload: res => {
          try {
            const json = JSON.parse(res.responseText || '{}');
            if (res.status >= 200 && res.status < 300) resolve(json);
            else reject(new Error(json.detail || res.statusText || `HTTP ${res.status}`));
          } catch (error) {
            reject(error);
          }
        },
        onerror: () => reject(new Error('本地 daemon 连接失败')),
        ontimeout: () => reject(new Error('本地 daemon 请求超时')),
      });
    });
  }

  async function pushMessage(node, reason = 'auto') {
    const text = normalizeText(node.innerText || node.textContent || '');
    if (text.length < 2 || text.length > 80000 || !hasIntent(text)) return;
    const key = hash(`${location.href}|${currentChatTitle()}|${text.slice(0, 2000)}`);
    if (seen.has(key)) return;
    seen.add(key);
    sessionStorage.setItem('ttc_feishu_seen_messages', JSON.stringify([...seen].slice(-1000)));

    const payload = {
      client_id: config.clientId || 'default',
      chat_title: currentChatTitle(),
      sender: extractSender(text),
      text,
      url: location.href,
      message_time: '',
      page_title: document.title,
      captured_at: new Date().toISOString(),
      auto_reply: true,
    };
    try {
      const result = await request('POST', '/api/feishu-web/message', payload);
      updateStatus(`已读取消息 #${result.message?.id || ''}${result.reply ? '，已生成草稿' : ''}`);
      log('已推送消息', reason, result);
    } catch (error) {
      updateStatus(`读取失败：${error.message}`);
      log(error);
    }
  }

  function scanVisibleMessages(reason = 'timer') {
    if (!config.enabled) return;
    const now = Date.now();
    if (now - lastScanAt < config.scanSeconds * 1000) return;
    lastScanAt = now;
    candidateMessageNodes().slice(-30).forEach(node => pushMessage(node, reason));
  }

  function findEditor() {
    const selectors = [
      '[contenteditable="true"][role="textbox"]',
      '[contenteditable="true"]',
      'textarea',
      'div[role="textbox"]',
    ];
    for (const sel of selectors) {
      const nodes = [...document.querySelectorAll(sel)].filter(node => node instanceof HTMLElement && node.offsetParent !== null);
      const node = nodes[nodes.length - 1];
      if (node) return node;
    }
    return null;
  }

  function setEditorText(editor, text) {
    editor.focus();
    if (editor.tagName === 'TEXTAREA' || editor.tagName === 'INPUT') {
      editor.value = text;
      editor.dispatchEvent(new Event('input', { bubbles: true }));
      return;
    }
    document.execCommand('selectAll', false);
    document.execCommand('insertText', false, text);
    editor.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: text }));
  }

  function trySend(editor) {
    if (!config.autoSend) return false;
    editor.focus();
    const event = new KeyboardEvent('keydown', {
      key: 'Enter',
      code: 'Enter',
      keyCode: 13,
      which: 13,
      bubbles: true,
      cancelable: true,
    });
    return editor.dispatchEvent(event);
  }

  async function pollReplies() {
    if (!config.enabled || !config.autoFillDraft) return;
    try {
      const result = await request('GET', `/api/feishu-web/pending-replies?client_id=${encodeURIComponent(config.clientId || 'default')}&limit=1`);
      const reply = result.replies?.[0];
      if (!reply) return;
      const editor = findEditor();
      if (!editor) {
        updateStatus('有待发送草稿，但没有找到飞书输入框');
        return;
      }
      setEditorText(editor, reply.reply_text);
      const sent = trySend(editor);
      await request('POST', '/api/feishu-web/reply-ack', {
        reply_id: reply.id,
        status: config.autoSend && sent ? 'sent' : 'filled',
      });
      updateStatus(config.autoSend ? '已尝试自动发送回复' : '已把回复填入输入框，等待你确认发送');
    } catch (error) {
      log('轮询草稿失败', error);
    }
  }

  function captureSelectionOrPage() {
    const selected = String(window.getSelection?.() || '').trim();
    const text = selected || normalizeText(document.body?.innerText || '');
    const fakeNode = { innerText: text, textContent: text };
    pushMessage(fakeNode, selected ? 'selection' : 'page');
  }

  function buildPanel() {
    if (panel) {
      panel.hidden = !panel.hidden;
      return;
    }
    GM_addStyle(`
      #ttc-feishu-bridge{position:fixed;right:16px;bottom:18px;z-index:2147483647;width:310px;background:#fffdf8;border:1px solid #d7d1c5;border-radius:14px;box-shadow:0 10px 32px #0002;color:#172026;font:13px/1.45 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif;padding:12px}
      #ttc-feishu-bridge h3{margin:0 0 8px;font-size:15px}
      #ttc-feishu-bridge label{display:flex;align-items:center;gap:7px;margin:7px 0}
      #ttc-feishu-bridge input[type=text]{width:100%;border:1px solid #d7d1c5;border-radius:8px;padding:7px;background:white}
      #ttc-feishu-bridge button{border:0;border-radius:8px;padding:8px 9px;background:#0d6f63;color:white;font-weight:700;cursor:pointer;margin:4px 4px 0 0}
      #ttc-feishu-bridge button.secondary{background:#ebe7dd;color:#172026}
      #ttc-feishu-bridge .muted{color:#6d746f;font-size:12px;margin-top:7px}
    `);
    panel = document.createElement('div');
    panel.id = 'ttc-feishu-bridge';
    panel.innerHTML = `
      <h3>TTC 飞书网页助手</h3>
      <label><input data-key="enabled" type="checkbox"> 启用消息读取</label>
      <label><input data-key="autoFillDraft" type="checkbox"> 自动填入回复草稿</label>
      <label><input data-key="autoSend" type="checkbox"> 自动发送（谨慎）</label>
      <label><input data-key="captureAll" type="checkbox"> 读取所有可见消息</label>
      <div class="muted">本地服务地址</div>
      <input data-key="daemon" type="text">
      <div class="muted">客户端 ID：多个飞书窗口可用不同 ID</div>
      <input data-key="clientId" type="text">
      <div>
        <button id="ttc-capture">读取选区/当前页</button>
        <button id="ttc-scan" class="secondary">扫描可见消息</button>
        <button id="ttc-close" class="secondary">隐藏</button>
      </div>
      <div id="ttc-status" class="muted"></div>
    `;
    document.body.appendChild(panel);
    statusEl = panel.querySelector('#ttc-status');
    panel.querySelectorAll('input[data-key]').forEach(input => {
      const key = input.dataset.key;
      if (input.type === 'checkbox') input.checked = Boolean(config[key]);
      else input.value = config[key] || '';
      input.addEventListener('change', () => {
        saveConfig({ [key]: input.type === 'checkbox' ? input.checked : input.value.trim() });
      });
    });
    panel.querySelector('#ttc-capture').addEventListener('click', captureSelectionOrPage);
    panel.querySelector('#ttc-scan').addEventListener('click', () => scanVisibleMessages('manual'));
    panel.querySelector('#ttc-close').addEventListener('click', () => { panel.hidden = true; });
    updateStatus();
  }

  function boot() {
    if (typeof GM_registerMenuCommand !== 'undefined') {
      GM_registerMenuCommand('TTC 飞书助手设置', buildPanel);
      GM_registerMenuCommand('TTC 读取选区/当前页', captureSelectionOrPage);
      GM_registerMenuCommand('TTC 暂停/恢复监听', () => saveConfig({ enabled: !config.enabled }));
    }
    buildPanel();
    const observer = new MutationObserver(() => scanVisibleMessages('mutation'));
    observer.observe(document.body || document.documentElement, { childList: true, subtree: true, characterData: true });
    setInterval(() => scanVisibleMessages('timer'), config.scanSeconds * 1000);
    setInterval(pollReplies, config.pollSeconds * 1000);
    setTimeout(() => scanVisibleMessages('boot'), 1500);
    log('启动完成', config);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once: true });
  } else {
    boot();
  }
})();
