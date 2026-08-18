/**
 * Automatically imports a visible, authorized candidate profile into the
 * configured cloud candidate table. The upstream assistant runtime remains responsible
 * for its original profile/resume/conversation features; this layer only adds
 * the candidate-collector -> cloud workflow.
 */
(function () {
  'use strict';

  const STATUS_ID = 'ttc-auto-import-status';
  const CONTEXT_EVENT = '__copilot.sidepanel.page_context_update';
  const XHR_EVENT = '__copilot.proxy.xhr';
  const MIN_TEXT_LENGTH = 160;
  const PROFILE_MARKERS = [
    '个人优势', '工作经历', '经历概览', '项目经历', '教育经历', '技能专长',
    '求职期望', '求职意向', '个人简介', '基本信息'
  ];

  function bossOverviewEvidence(text) {
    if (!text.includes('经历概览')) return false;
    const periods = text.match(/(?:19|20)\d{2}[./-]\d{1,2}\s*[-–—~～至]\s*(?:至今|(?:19|20)\d{2})/g);
    return Boolean(periods && periods.length >= 2);
  }

  let inFlight = false;
  let timer = null;
  let lastUrl = location.href;
  let lastContext = null;
  let lastAttemptKey = '';
  let lastMutationProbeAt = 0;
  let bossProfileCache = '';
  let bossProfileCacheAt = 0;
  let bridgeModulePromise = null;
  let observer = null;
  let runtimeDisabled = Boolean(
    globalThis.__OT_RUNTIME_RECOVERY__ &&
    globalThis.__OT_RUNTIME_RECOVERY__.invalidated
  );

  function platform() {
    const host = location.hostname;
    if (host.endsWith('zhipin.com')) return 'boss';
    if (host.endsWith('liepin.com')) return 'liepin';
    if (host === 'maimai.cn' || host.endsWith('.maimai.cn')) return 'maimai';
    if (host.endsWith('linkedin.com')) return 'linkedin';
    if (host === 'h.dhunting.com') return 'dhunting';
    if (host === 'app.ttcadvisory.com') return 'ttc';
    return '';
  }

  function bossProfileText() {
    if (platform() !== 'boss' || !document.body) return '';
    const now = Date.now();
    if (now - bossProfileCacheAt < 500) return bossProfileCache;
    const markerElements = [];
    const elements = document.body.querySelectorAll('h1,h2,h3,h4,h5,h6,div,section,span,p');
    for (const element of elements) {
      if (markerElements.length >= 80) break;
      const text = String(element.innerText || '').trim();
      if (!text || text.length > 30) continue;
      const rect = element.getBoundingClientRect();
      if (!rect.width || !rect.height) continue;
      const normalized = text.replace(/\s+/g, '').replace(/[：:（(]\d+[）)]?$/, '');
      if (PROFILE_MARKERS.some(marker => normalized === marker || normalized.startsWith(marker))) {
        markerElements.push(element);
      }
    }

    let best = null;
    for (const markerElement of markerElements) {
      let candidate = markerElement.parentElement;
      for (let depth = 0; candidate && candidate !== document.body && depth < 10; depth += 1) {
        const text = String(candidate.innerText || '').trim();
        if (text.length >= MIN_TEXT_LENGTH && text.length <= 60_000) {
          const rect = candidate.getBoundingClientRect();
          const markerCount = PROFILE_MARKERS.filter(marker => text.includes(marker)).length;
          const identityEvidence = /(\d+\s*岁|\d+\s*年|本科|硕士|博士|大专|在职|离职|经理|总监|负责人)/.test(text);
          if (rect.width && rect.height && (markerCount >= 2 || bossOverviewEvidence(text)) && identityEvidence) {
            const score = markerCount * 100_000 - text.length;
            if (!best || score > best.score) best = {text, score};
          }
        }
        candidate = candidate.parentElement;
      }
    }
    bossProfileCache = best ? best.text : '';
    bossProfileCacheAt = now;
    return bossProfileCache;
  }

  function compactText() {
    const source = platform() === 'boss'
      ? bossProfileText()
      : (document.body && document.body.innerText || '');
    return source
      .replace(/\s+/g, ' ')
      .trim();
  }

  function hasProfileEvidence(text) {
    if (!text || text.length < MIN_TEXT_LENGTH) return false;
    const markerCount = PROFILE_MARKERS.filter(marker => text.includes(marker)).length;
    const identityEvidence = /(\d+\s*岁|\d+\s*年|本科|硕士|博士|大专|在职|离职|经理|总监|负责人)/.test(text);
    return (markerCount >= 2 || bossOverviewEvidence(text)) && identityEvidence;
  }

  function urlLooksLikeProfile(name) {
    const value = location.href;
    if (name === 'ttc') return /\/app\/talent\/[A-Za-z0-9_-]+/.test(value);
    if (name === 'linkedin') return /\/in\/[^/?#]+\/?/.test(value);
    if (name === 'liepin') return /(showresumedetail|resume|candidate|profile|jobhunter)/i.test(value);
    if (name === 'maimai') return /(talent|candidate|resume|profile|detail\?dstu=)/i.test(value);
    if (name === 'boss') return /(geek|jobhunter|candidate|resume)/i.test(value);
    return false;
  }

  function shouldImport(context) {
    const name = platform();
    if (!name) return false;
    if (isTtcSearchList()) return false;
    const text = compactText();
    const validContext = context && context.id &&
      context.id !== '__loading__' && context.id !== '';
    if (name === 'linkedin') {
      return urlLooksLikeProfile(name) && text.length >= MIN_TEXT_LENGTH;
    }
    if (name === 'dhunting') {
      return Boolean(validContext) && text.length >= MIN_TEXT_LENGTH;
    }
    if (name === 'boss') {
      // BOSS renders candidate drawers inside /web/chat/index without changing
      // the URL or always publishing the upstream side-panel context event.
      return hasProfileEvidence(text);
    }
    return (validContext || urlLooksLikeProfile(name)) && hasProfileEvidence(text);
  }

  function simpleHash(value) {
    let hash = 2166136261;
    for (let i = 0; i < value.length; i += 1) {
      hash ^= value.charCodeAt(i);
      hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0).toString(16);
  }

  function importKey(context) {
    const contextId = context && context.id && context.id !== '__loading__'
      ? String(context.id)
      : '';
    const text = compactText();
    return [platform(), contextId || location.href, simpleHash(text.slice(0, 1200))].join('|');
  }

  function siderImportKey(context) {
    const id = context && context.id && context.id !== '__loading__'
      ? String(context.id)
      : '';
    return id ? ['sider', platform(), id].join('|') : '';
  }

  function imported(key) {
    try {
      return sessionStorage.getItem('ot_cloud_imported_' + key) === '1';
    } catch (_error) {
      return key === lastAttemptKey;
    }
  }

  function markImported(key) {
    lastAttemptKey = key;
    try {
      sessionStorage.setItem('ot_cloud_imported_' + key, '1');
    } catch (_error) {
      // Some recruiting pages disable storage; the in-memory key still works.
    }
  }

  function clearImported(key) {
    try {
      sessionStorage.removeItem('ot_cloud_imported_' + key);
    } catch (_error) {
      if (lastAttemptKey === key) lastAttemptKey = '';
    }
  }

  function showStatus(message, type, persistent, targetUrl) {
    if (!document.body) return;
    let element = document.getElementById(STATUS_ID);
    if (!element) {
      element = document.createElement('div');
      element.id = STATUS_ID;
      element.style.cssText = [
        'position:fixed', 'right:24px', 'bottom:24px', 'z-index:2147483640',
        'box-sizing:border-box', 'max-width:360px', 'min-width:260px',
        'padding:12px 16px', 'border:1px solid #e7e7ea',
        'border-left-width:4px', 'border-radius:12px', 'background:#fff',
        'color:#18181b', 'font:13px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif',
        'box-shadow:0 1px 2px rgba(0,0,0,.04),0 8px 24px rgba(0,0,0,.08)',
        'transition:opacity .3s ease,transform .3s ease', 'overflow-wrap:anywhere'
      ].join(';');
      element.setAttribute('role', 'status');
      element.setAttribute('aria-live', 'polite');
      document.body.appendChild(element);
    }
    if (element._otHideTimer) clearTimeout(element._otHideTimer);
    element.replaceChildren();
    const messageNode = document.createElement('span');
    messageNode.textContent = message;
    element.appendChild(messageNode);
    const link = /^https?:\/\//.test(targetUrl || '') ? targetUrl : '';
    if (type === 'success' && link) {
      const action = document.createElement('span');
      action.textContent = '查看记录 →';
      action.style.cssText = 'display:inline-block;margin-left:10px;color:#2563eb;font-weight:600;white-space:nowrap';
      element.appendChild(action);
    }
    element.title = link ? '点击查看云端记录' : '';
    element.style.cursor = link ? 'pointer' : 'default';
    element.onclick = link ? () => window.open(link, '_blank', 'noopener') : null;
    element.style.borderLeftColor = type === 'error' ? '#dc2626' :
      type === 'success' ? '#16a34a' : '#2563eb';
    element.style.opacity = '1';
    element.style.transform = 'translateY(0)';
    if (!persistent) {
      element._otHideTimer = setTimeout(() => {
        element.style.opacity = '0';
        element.style.transform = 'translateY(6px)';
      }, 12000);
    }
  }

  function isTtcSearchList() {
    return platform() === 'ttc' && location.pathname.replace(/\/+$/, '') === '/app/talent/search/list';
  }

  function currentOtListKey() {
    const ids = Array.from(document.querySelectorAll(
      'table tbody tr.ant-table-row, .ant-table-row[data-row-key]'
    ))
      .map(row => row.getAttribute('data-row-key') || '')
      .filter(Boolean);
    const uniqueIds = Array.from(new Set(ids)).slice(0, 10);
    return 'ot-list|' + location.href + '|' + simpleHash(uniqueIds.join('|'));
  }

  function targetLabel(target) {
    const name = target && target.name || '云端人才库';
    const tableName = target && target.table || 'cloud_candidates';
    return '「' + name + ' / ' + tableName + '」';
  }

  function showImportResult(result) {
    const candidate = result.candidate || {};
    const name = candidate.name || '当前候选人';
    const target = result.target || null;
    const verb = result.action === 'updated' ? '已更新' : '已写入';
    showStatus(
      verb + targetLabel(target) + '：' + name,
      'success',
      false,
      result.record_url || result.recordUrl || candidate.source_url || ''
    );
  }

  function send(message) {
    return new Promise((resolve, reject) => {
      chrome.runtime.sendMessage(message, response => {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message));
          return;
        }
        if (!response || !response.ok) {
          reject(new Error(response && response.error || '自动导入失败'));
          return;
        }
        resolve(response);
      });
    });
  }

  function disableRuntimeAutomation() {
    runtimeDisabled = true;
    clearTimeout(timer);
    timer = null;
    if (observer) observer.disconnect();
  }

  function recoverRuntimeContext(error) {
    const recovery = globalThis.__OT_RUNTIME_RECOVERY__;
    if (!recovery || !recovery.isRecoverableError(error)) return false;
    disableRuntimeAutomation();
    if (recovery.instance) recovery.instance.recover(error);
    return true;
  }

  async function waitForStableProfile(context) {
    let previous = '';
    let stableRounds = 0;
    for (let round = 0; round < 8; round += 1) {
      const text = compactText();
      if (text === previous && shouldImport(context)) stableRounds += 1;
      else stableRounds = 0;
      if (stableRounds >= 1) return true;
      previous = text;
      await new Promise(resolve => setTimeout(resolve, 900));
    }
    return shouldImport(context);
  }

  async function autoImport(context) {
    if (runtimeDisabled || inFlight || !shouldImport(context)) return;
    const siderKey = siderImportKey(context);
    if (platform() === 'boss' && siderKey && imported(siderKey)) return;
    if (platform() === 'ttc') {
      const status = await send({type: 'getStatus'}).catch(() => null);
      if (status && status.state && status.state.running) return;
    }
    if (!await waitForStableProfile(context)) return;
    const key = importKey(context);
    if (imported(key)) return;

    inFlight = true;
    showStatus('正在写入云端人才库…', 'info', true);
    try {
      const result = await send({
        type: 'autoImportCurrentPage',
        upstreamContext: context || null
      });
      markImported(key);
      showImportResult(result);
    } catch (error) {
      if (recoverRuntimeContext(error)) return;
      showStatus('自动导入失败：' + error.message + '。云端不可达时插件才会尝试本机服务。', 'error');
    } finally {
      inFlight = false;
    }
  }

  function bridgeModule() {
    if (!bridgeModulePromise) {
      bridgeModulePromise = import(chrome.runtime.getURL('sider_bridge.js'));
    }
    return bridgeModulePromise;
  }

  function bossRequestUrl(value) {
    try {
      const url = new URL(String(value || ''), location.href);
      if (url.protocol !== 'https:' || !/(?:^|\.)zhipin\.com$/i.test(url.hostname)) return '';
      return url.href;
    } catch (_error) {
      return '';
    }
  }

  async function responseJson(response) {
    if (!response || typeof response.text !== 'function') return null;
    if (Number(response.size || 0) > 2_000_000) return null;
    const text = await response.text();
    if (!text || text.length > 2_000_000 || !/^\s*[\[{]/.test(text)) return null;
    try {
      return JSON.parse(text);
    } catch (_error) {
      return null;
    }
  }

  async function autoImportBossResponse(eventData) {
    if (runtimeDisabled || platform() !== 'boss' || inFlight) return;
    const requestUrl = bossRequestUrl(eventData && eventData.url);
    if (!requestUrl) return;
    const data = await responseJson(eventData.response);
    if (!data) return;
    const bridge = await bridgeModule();
    const extracted = bridge.extractBossProfileFromApiResponse(data, requestUrl);
    if (!extracted) return;
    const key = siderImportKey(extracted.context);
    if (!key || imported(key)) return;

    inFlight = true;
    showStatus('已识别 BOSS 动态简历，正在保存本地并自动入库…', 'info', true);
    try {
      const result = await send({
        type: 'importBossApiProfile',
        requestUrl,
        data
      });
      markImported(key);
      showImportResult(result);
    } catch (error) {
      if (recoverRuntimeContext(error)) return;
      clearImported(key);
      showStatus('动态简历桥接失败：' + error.message + '。将继续尝试读取当前可见简历。', 'error');
      schedule(lastContext, 700);
    } finally {
      inFlight = false;
    }
  }

  async function waitForTtcRows() {
    for (let round = 0; round < 120; round += 1) {
      if (document.querySelector('table tbody tr.ant-table-row, .ant-table-row[data-row-key]')) return true;
      if (round > 0 && round % 10 === 0) {
        showStatus('ot小插件正在等待 ot 搜索结果…', 'info', true);
      }
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
    return false;
  }

  async function autoImportTtcSearchList() {
    if (runtimeDisabled || inFlight || !isTtcSearchList()) return;
    inFlight = true;
    showStatus('ot小插件正在读取 ot 当前页（最多 10 人）…', 'info', true);
    let key = '';
    try {
      if (!await waitForTtcRows()) throw new Error('当前页未读取到候选人列表');
      key = currentOtListKey();
      if (imported(key)) return;
      await send({type: 'autoImportTtcSearchList', limit: 10});
      markImported(key);
      let state = null;
      for (let round = 0; round < 180; round += 1) {
        await new Promise(resolve => setTimeout(resolve, 1000));
        const response = await send({type: 'getStatus'});
        state = response.state || null;
        if (state && state.running) {
          showStatus(state.message || 'ot小插件正在导入当前页…', 'info', true);
          continue;
        }
        if (state && !state.running) break;
      }
      if (!state || state.running) throw new Error('导入超时，请查看插件状态');
      const type = state.errors ? 'error' : 'success';
      if (state.errors && !state.done && !state.skipped) clearImported(key);
      const matches = Array.isArray(state.matches) ? state.matches : [];
      const matchedText = matches.length
        ? '；匹配跳过：' + matches.map(item => item.name + '（按' + item.matchedBy + '）').join('、')
        : '';
      showStatus(
        (state.message || 'ot 当前页导入完成') + matchedText,
        type,
        false
      );
    } catch (error) {
      if (recoverRuntimeContext(error)) return;
      if (key) clearImported(key);
      showStatus('ot 列表自动导入失败：' + error.message, 'error');
    } finally {
      inFlight = false;
    }
  }

  function schedule(context, delay) {
    if (runtimeDisabled) return;
    if (context) lastContext = context;
    clearTimeout(timer);
    timer = setTimeout(
      () => isTtcSearchList() ? autoImportTtcSearchList() : autoImport(lastContext),
      delay || 1400
    );
  }

  window.addEventListener('message', event => {
    if (runtimeDisabled) return;
    if (event.source !== window || !event.data) return;
    if (event.data.type === XHR_EVENT) {
      void autoImportBossResponse(event.data).catch(error => {
        if (recoverRuntimeContext(error)) return;
        showStatus('动态简历读取失败：' + error.message + '。将尝试读取当前可见简历。', 'error');
        schedule(lastContext, 700);
      });
      return;
    }
    if (event.data.type !== CONTEXT_EVENT) return;
    const context = event.data.context || null;
    if (!context || !context.id || context.id === '__loading__') return;
    lastContext = context;
    schedule(context, 1100);
  });

  const invalidatedEvent = globalThis.__OT_RUNTIME_RECOVERY__ &&
    globalThis.__OT_RUNTIME_RECOVERY__.invalidatedEvent ||
    'ot:extension-context-invalidated';
  window.addEventListener(invalidatedEvent, disableRuntimeAutomation);

  observer = new MutationObserver(() => {
    if (runtimeDisabled) return;
    if (location.href !== lastUrl) {
      lastUrl = location.href;
      lastContext = null;
      schedule(null, 1800);
      return;
    }
    if (platform() === 'boss' && !inFlight) {
      const now = Date.now();
      if (now - lastMutationProbeAt >= 1500) {
        bossProfileCacheAt = 0;
        lastMutationProbeAt = now;
        schedule(lastContext, 700);
      }
      return;
    }
    if (
      isTtcSearchList() &&
      !inFlight &&
      document.querySelector('table tbody tr.ant-table-row, .ant-table-row[data-row-key]') &&
      !imported(currentOtListKey())
    ) {
      schedule(null, 300);
    }
  });
  observer.observe(document.documentElement, {childList: true, subtree: true});

  if (!runtimeDisabled) schedule(null, 1800);
})();
