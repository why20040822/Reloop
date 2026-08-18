const LOCAL_IMPORT_API = 'http://127.0.0.1:8765/api/import-local-download';
const EXTENSION_VERSION = '4.8.0';
const TARGET_CLOUD = Object.freeze({
  name: '云端人才库',
  database: 'ttc_talent',
  table: 'cloud_candidates'
});
const COPILOT_USER_STATUS_PATH =
  '/api/user_service/v1/internal/user/batch/unionids';
const COPILOT_SERVICE_HOSTS = new Set([
  'app.ttcadvisory.com',
  'int.ttcadvisory.com'
]);

import { platformFromUrl, supportedHost } from './parsers/common.js';
import { isExpectedTtcDetailPayload } from './parsers/ttc.js';
import { validatePayload } from './validation.js';
import { postPluginPayload } from './cloud_client.js';
import {
  extractBossProfileFromApiResponse,
  fetchSiderProfile,
  normalizeSiderContext,
  siderProfileToCapture
} from './sider_bridge.js';

// This worker is loaded beside the upstream Copilot worker. Only claim OT
// messages so upstream requests such as `fetchData` keep their own responder.
const OT_BACKGROUND_MESSAGE_TYPES = new Set([
  'captureCurrent',
  'otUserStatusFetch',
  'importFeishu',
  'importCloud',
  'autoImportCurrentDetail',
  'autoImportCurrentPage',
  'importSiderProfile',
  'importBossApiProfile',
  'getCandidateCacheIndex',
  'startTtcBatchImport',
  'autoImportTtcSearchList',
  'ping',
  'validatePage',
  'startBatch',
  'resumeBatch',
  'testLinks',
  'startGmailBatch',
  'stopBatch',
  'getStatus'
]);

let batchPromise = null;

// 点击插件图标直接打开侧边栏（匹配界面 + 入库状态）。顶层执行一次，
// 保证未打包扩展重载（不触发 onInstalled/onStartup）后也生效。
if (chrome.sidePanel && chrome.sidePanel.setPanelBehavior) {
  chrome.sidePanel.setPanelBehavior({openPanelOnActionClick: true}).catch(() => {});
}

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

function validCopilotUserStatusRequest(message) {
  try {
    const url = new URL(String(message && message.url || ''));
    if (
      url.protocol !== 'https:' ||
      !COPILOT_SERVICE_HOSTS.has(url.hostname) ||
      url.pathname !== COPILOT_USER_STATUS_PATH ||
      url.search ||
      url.hash
    ) {
      return null;
    }
    const body = message && message.body;
    const unionIds = body && body.union_ids;
    if (
      !Array.isArray(unionIds) ||
      unionIds.length < 1 ||
      unionIds.length > 50 ||
      unionIds.some(value => typeof value !== 'string' || !value || value.length > 240)
    ) {
      return null;
    }
    return {
      url: url.origin + COPILOT_USER_STATUS_PATH,
      body: {
        union_ids: unionIds,
        third_login_platform: 1
      }
    };
  } catch (_error) {
    return null;
  }
}

async function fetchCopilotUserStatus(message) {
  const request = validCopilotUserStatusRequest(message);
  if (!request) {
    const error = '已拒绝非白名单用户状态请求';
    return {success: false, error, data: error};
  }
  try {
    const response = await fetch(request.url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(request.body),
      cache: 'no-store',
      credentials: 'omit'
    });
    return {
      success: true,
      data: await response.text(),
      status: response.status
    };
  } catch (cause) {
    const error = cause && cause.message ? cause.message : String(cause || 'Failed to fetch');
    return {success: false, error, data: error};
  }
}

const getState = () => chrome.storage.local.get('batch').then(data => {
  const state = Object.assign({
    running: false,
    queue: [],
    total: 0,
    done: 0,
    skipped: 0,
    matches: [],
    errors: 0,
    current: '',
    message: '空闲',
    platform: '',
    updatedAt: 0,
    targetCloud: TARGET_CLOUD
  }, data.batch || {}, {targetCloud: TARGET_CLOUD});
  delete state.targetBase;
  return state;
});
const setState = state => {
  const next = Object.assign({}, state, {updatedAt: Date.now()});
  return chrome.storage.local.set({batch: next}).then(() => next);
};
function waitForTab(tabId, timeoutMs = 25000) {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(listener);
      reject(new Error('页面加载超时'));
    }, timeoutMs);
    function listener(id, info) {
      if (id === tabId && info.status === 'complete') {
        clearTimeout(timeout);
        chrome.tabs.onUpdated.removeListener(listener);
        resolve();
      }
    }
    chrome.tabs.onUpdated.addListener(listener);
    chrome.tabs.get(tabId).then(tab => {
      if (tab.status === 'complete') {
        clearTimeout(timeout);
        chrome.tabs.onUpdated.removeListener(listener);
        resolve();
      }
    }).catch(() => {});
  });
}

async function waitForTabSoft(tabId, timeoutMs = 35000) {
  try {
    await waitForTab(tabId, timeoutMs);
    return {ok: true, timedOut: false};
  } catch (error) {
    const tab = await chrome.tabs.get(tabId).catch(() => null);
    if (tab && /^https?:/.test(tab.url || '')) {
      return {ok: false, timedOut: true, error: error.message};
    }
    throw error;
  }
}

async function pauseForHuman(tab, state, message) {
  if (tab && tab.id) await chrome.tabs.update(tab.id, {active: true}).catch(() => {});
  await setState(Object.assign({}, state, {
    running: false,
    paused: true,
    pausedTabId: tab && tab.id,
    message
  }));
}

chrome.runtime.onInstalled.addListener(() => {
  // 点击插件图标直接打开侧边栏（匹配界面 + 入库状态），不再只弹小窗。
  if (chrome.sidePanel && chrome.sidePanel.setPanelBehavior) {
    chrome.sidePanel.setPanelBehavior({openPanelOnActionClick: true}).catch(() => {});
  }
  chrome.storage.local.remove(['feishuTarget']).then(() => chrome.storage.local.set({
      cloudTarget: TARGET_CLOUD,
      workerStatus: {
        ok: true,
        version: EXTENSION_VERSION,
        installedAt: new Date().toISOString()
      }
    }));
});

chrome.runtime.onStartup.addListener(() => {
  if (chrome.sidePanel && chrome.sidePanel.setPanelBehavior) {
    chrome.sidePanel.setPanelBehavior({openPanelOnActionClick: true}).catch(() => {});
  }
  chrome.storage.local.remove(['feishuTarget']).then(() => chrome.storage.local.set({
      cloudTarget: TARGET_CLOUD,
      workerStatus: {
        ok: true,
        version: EXTENSION_VERSION,
        startedAt: new Date().toISOString()
      }
    }));
});

async function readTab(tabId) {
  const tab = await chrome.tabs.get(tabId).catch(() => null);
  const platform = platformFromUrl(tab && tab.url ? tab.url : '');
  const results = await chrome.scripting.executeScript({
    target: {tabId},
    func: async (platformName, parserRoot) => {
      // BOSS 候选人详情可能在 /web/chat/index 内异步渲染，等待简历分节出现。
      if (platformName === 'boss') {
        const resumeMarkers = ['个人优势', '工作经历', '经历概览', '项目经历', '教育经历', '技能专长', '求职期望'];
        const deadline = Date.now() + 5000;
        while (Date.now() < deadline) {
          const renderedText = document.body ? document.body.innerText : '';
          const markerCount = resumeMarkers.filter(marker => renderedText.includes(marker)).length;
          if (markerCount >= 2) break;
          await new Promise(resolve => setTimeout(resolve, 250));
        }
      }
      const pageText = document.body ? document.body.innerText : '';
      const title = document.title || '';
      const url = location.href;
      const common = await import(parserRoot + 'common.js?v=20260729');
      let parser = null;
      // 带版本号绕过页面 realm 的模块缓存：插件更新后即使不刷新页面也能拿到新解析器
      if (platformName === 'boss') parser = await import(parserRoot + 'boss.js?v=20260729');
      if (platformName === 'maimai') parser = await import(parserRoot + 'maimai.js?v=20260729');
      if (platformName === 'liepin') parser = await import(parserRoot + 'liepin.js?v=20260729');
      if (platformName === 'ttc') parser = await import(parserRoot + 'ttc.js?v=20260729');
      const blocked = common.detectRisk(pageText, title, url);

      let structured = null;
      if (platformName === 'boss' && parser && parser.extractBossSections) {
        structured = parser.extractBossSections();
      }
      if (platformName === 'maimai' && parser && parser.extractMaimaiSections) {
        structured = parser.extractMaimaiSections();
      }
      if (platformName === 'liepin' && parser && parser.extractLiepinSections) {
        structured = parser.extractLiepinSections();
      }
      if (platformName === 'ttc' && parser && parser.extractTtcSections) {
        structured = parser.extractTtcSections();
      }
      const text = structured && typeof structured.raw_text === 'string' && structured.raw_text.trim()
        ? structured.raw_text
        : pageText;

      // BOSS 聊天/推荐页的 h1 是页面标题或公告横幅（「全文」「招聘规范」），不是
      // 候选人姓名；姓名只认解析器从简历抽屉头部的定向提取，宁缺毋滥。
      const bossName = platformName === 'boss' && parser && parser.extractBossCandidateName
        ? parser.extractBossCandidateName()
        : '';
      // BOSS 页面开 DevTools 会被强制退出，DOM 结构只能靠插件自报诊断。
      if (platformName === 'boss' && parser && parser.collectBossNameDebug) {
        structured = structured || {};
        structured.name_debug = parser.collectBossNameDebug();
      }
      return {
        url,
        title,
        heading: platformName === 'boss'
          ? bossName
          : (document.querySelector('h1') && document.querySelector('h1').innerText) ||
            (document.querySelector('[class*=name]') && document.querySelector('[class*=name]').innerText) || '',
        text,
        structured_data: structured,
        captured_at: new Date().toISOString(),
        source_type: 'authorized_batch_browser',
        blocked,
        empty: !document.body || text.replace(/\s+/g, '').length < 30,
        ready_state: document.readyState
      };
    },
    args: [platform, chrome.runtime.getURL('parsers/')]
  });
  return results[0].result;
}

async function saveCapture(payload) {
  const data = await postPluginPayload('capture', Object.assign({}, payload, {
    dry_run: false
  }));
  return data.candidate;
}

async function captureCurrent() {
  const tabs = await chrome.tabs.query({active: true, currentWindow: true});
  const tab = tabs[0];
  if (!tab || !tab.id || !/^https?:/.test(tab.url || '')) throw new Error('当前不是可收藏网页');
  // 手动收藏时拦截明显的 BOSS 后台/列表页。BOSS 会在聊天页内异步渲染简历，
  // 因此 /chat/ 不再仅根据 URL 拦截，而是在读取后验证简历分节。
  if (/zhipin\.com/.test(new URL(tab.url).hostname)) {
    const managementPaths = /\/manage\/|\/tools\/|\/prop\/|\/vip\/|\/data\/|\/job_list\/| ka=action/;
    if (managementPaths.test(tab.url)) {
      throw new Error('当前是 BOSS 后台或列表导航页，请打开单个候选人简历页再收藏');
    }
  }
  const payload = await readTab(tab.id);
  if (payload.blocked) throw new Error('页面要求人工处理：' + payload.blocked);
  if (!payload.text || payload.text.length < 10) throw new Error('当前页面没有足够可见文本');
  if (/zhipin\.com/.test(new URL(tab.url).hostname) && !hasBossResumeEvidence(payload)) {
    throw new Error('当前 BOSS 页未检测到已展开的候选人简历，请先打开候选人详情');
  }
  payload.source_type = 'authorized_visible_page';
  return saveCapture(payload);
}

function hasBossResumeEvidence(payload) {
  const markers = ['个人优势', '工作经历', '经历概览', '项目经历', '教育经历', '技能专长', '求职期望'];
  const sections = payload && payload.structured_data && Array.isArray(payload.structured_data.sections)
    ? payload.structured_data.sections
    : [];
  const sectionHeadings = sections.map(section => String(section.heading || '').replace(/\s+/g, ''));
  const text = String(payload && payload.text || '');
  const matched = markers.filter(marker => sectionHeadings.some(heading => heading.startsWith(marker)) || text.includes(marker));
  if (text.replace(/\s+/g, '').length >= 200 && matched.length >= 2) return true;
  // 推荐页面板只有「经历概览」一个分节：用多个工作时间段作为第二证据。
  const periods = text.match(/(?:19|20)\d{2}[./-]\d{1,2}\s*[-–—~～至]\s*(?:至今|(?:19|20)\d{2})/g);
  return text.includes('经历概览') && Boolean(periods && periods.length >= 2);
}

async function importCloudCurrent(dryRun = false, sourceTabId = null) {
  const tab = sourceTabId
    ? await chrome.tabs.get(sourceTabId).catch(() => null)
    : (await chrome.tabs.query({active: true, currentWindow: true}))[0];
  if (!tab || !tab.id || !/^https?:/.test(tab.url || '')) throw new Error('当前不是可导入网页');
  const payload = await readTab(tab.id);
  if (payload.blocked) throw new Error('页面要求人工处理：' + payload.blocked);
  if (!payload.text || payload.text.length < 10) throw new Error('当前页面没有足够可见文本');
  if (/zhipin\.com/.test(new URL(tab.url).hostname) && !hasBossResumeEvidence(payload)) {
    throw new Error('当前 BOSS 页未检测到已展开的候选人简历，请先打开候选人详情');
  }
  payload.platform = platformFromUrl(tab.url);
  payload.source_type = 'browser_capture';

  return postPluginPayload('import', Object.assign({}, payload, {
    dry_run: Boolean(dryRun)
  }));
}

async function importCloudFromPayload(payload) {
  payload.platform = payload.platform || platformFromUrl(payload.url);
  payload.source_type = payload.source_type || 'browser_capture';
  return postPluginPayload('import', Object.assign({}, payload, {
    dry_run: false
  }));
}

function siderCacheHash(value) {
  let hash = 2166136261;
  const text = String(value || '');
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(16);
}

function redactSensitiveStorageValue(value) {
  try {
    return JSON.parse(JSON.stringify(value, (key, child) => {
      if (/(?:^|_)(?:access_?token|refresh_?token|authorization|cookie|credential|password|secret)(?:$|_)/i.test(key)) {
        return '[redacted]';
      }
      return child;
    }));
  } catch (_error) {
    return null;
  }
}

async function storeBridgeSnapshotLocally(profile, context, capture, sourceUrl, source) {
  const normalized = normalizeSiderContext(context);
  const key = 'ot_candidate_cache_' + siderCacheHash(normalized.id);
  const sanitizedProfile = redactSensitiveStorageValue(profile);
  const serialized = sanitizedProfile == null ? '' : JSON.stringify(sanitizedProfile);
  const rawStored = Boolean(serialized) && serialized.length <= 750_000;
  const storedAt = new Date().toISOString();
  const expiresAt = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString();
  const snapshot = {
    schemaVersion: 1,
    source,
    context: normalized,
    sourceUrl,
    storedAt,
    expiresAt,
    rawStored,
    profile: rawStored ? sanitizedProfile : null,
    capture
  };
  const indexData = await chrome.storage.local.get('ot_candidate_cache_index');
  const previous = Array.isArray(indexData.ot_candidate_cache_index)
    ? indexData.ot_candidate_cache_index
    : [];
  const now = Date.now();
  const activePrevious = previous.filter(item => {
    const expiry = Date.parse(item && item.expiresAt || '');
    return item && item.key && (!Number.isFinite(expiry) || expiry > now);
  });
  const currentEntry = {
    key,
    id: normalized.id,
    platform: normalized.platform,
    name: capture.heading || '',
    source,
    sourceUrl,
    storedAt,
    expiresAt,
    rawStored
  };
  const nextIndex = [
    currentEntry,
    ...activePrevious.filter(item => item.key !== key)
  ].slice(0, 5);
  const keep = new Set(nextIndex.map(item => item.key));
  const expiredKeys = previous
    .map(item => item && item.key)
    .filter(oldKey => oldKey && !keep.has(oldKey));

  try {
    await chrome.storage.local.set({
      [key]: snapshot,
      ot_candidate_cache_latest: currentEntry,
      ot_candidate_cache_index: nextIndex
    });
  } catch (error) {
    // A very large resume must not make the whole bridge fail. Retain a
    // bounded normalized capture and omit the raw API object on quota errors.
    snapshot.profile = null;
    snapshot.rawStored = false;
    snapshot.capture = Object.assign({}, capture, {
      text: String(capture.text || '').slice(0, 250_000)
    });
    currentEntry.rawStored = false;
    await chrome.storage.local.set({
      [key]: snapshot,
      ot_candidate_cache_latest: currentEntry,
      ot_candidate_cache_index: nextIndex
    }).catch(() => {
      throw error;
    });
  }
  if (expiredKeys.length) await chrome.storage.local.remove(expiredKeys);
  return {key, storedAt, rawStored: snapshot.rawStored, retained: nextIndex.length};
}

async function importBridgeCapture({profile, context, capture, sourceUrl, source}) {
  let localCache = null;
  try {
    localCache = await storeBridgeSnapshotLocally(
      profile,
      context,
      capture,
      sourceUrl,
      source
    );
    await setState(Object.assign({}, await getState(), {
      running: true,
      current: capture.heading || context.id,
      platform: 'boss',
      message: '候选人资料已保存本地，正在写入云端人才库',
      localCacheKey: localCache.key
    }));
    const result = await importCloudFromPayload(capture);
    const candidate = result.candidate || {};
    await setState(Object.assign({}, await getState(), {
      running: false,
      current: candidate.name || capture.heading || context.id,
      platform: 'boss',
      errors: 0,
      message: '候选人资料已保存本地并完成自动入库',
      localCacheKey: localCache.key
    }));
    return Object.assign({
      ok: Boolean(result.ok),
      source,
      localCache,
      targetCloud: TARGET_CLOUD
    }, result);
  } catch (error) {
    await setState(Object.assign({}, await getState(), {
      running: false,
      platform: 'boss',
      errors: 1,
      message: localCache
        ? '候选人资料已保存本地，但自动入库失败：' + error.message
        : '候选人资料读取失败：' + error.message,
      localCacheKey: localCache && localCache.key || ''
    }));
    throw error;
  }
}

async function importSiderProfileBridge(message, sender) {
  const tabUrl = String(sender && sender.tab && sender.tab.url || '');
  if (!/^https:\/\/(?:[^/]+\.)?zhipin\.com\//i.test(tabUrl)) {
    throw new Error('Sider 桥接仅允许从当前 BOSS 标签页读取');
  }
  const context = normalizeSiderContext(message.context);
  const state = await getState();
  await setState(Object.assign({}, state, {
    running: true,
    current: '',
    platform: 'boss',
    errors: 0,
    message: '正在读取 Sider 结构化资料'
  }));

  try {
    const profile = await fetchSiderProfile(context, message.auth);
    const capture = siderProfileToCapture(profile, context, tabUrl);
    return await importBridgeCapture({
      profile,
      context,
      capture,
      sourceUrl: tabUrl,
      source: 'sider_profile_bridge'
    });
  } catch (error) {
    const stateAfterFailure = await getState();
    if (stateAfterFailure.running) {
      await setState(Object.assign({}, stateAfterFailure, {
        running: false,
        platform: 'boss',
        errors: 1,
        message: 'Sider 兼容桥接失败：' + error.message
      }));
    }
    throw error;
  }
}

async function importBossApiProfileBridge(message, sender) {
  const tabUrl = String(sender && sender.tab && sender.tab.url || '');
  if (!/^https:\/\/(?:[^/]+\.)?zhipin\.com\//i.test(tabUrl)) {
    throw new Error('BOSS 动态数据桥接仅允许从当前 BOSS 标签页读取');
  }
  const extracted = extractBossProfileFromApiResponse(message.data, message.requestUrl);
  if (!extracted) throw new Error('当前响应不是单个 BOSS 候选人简历');
  const context = normalizeSiderContext(extracted.context);
  const capture = siderProfileToCapture(extracted.profile, context, tabUrl);
  if (!capture.structured_data || !capture.structured_data.profile_detected) {
    throw new Error('当前响应缺少可验证的候选人简历结构');
  }
  await setState(Object.assign({}, await getState(), {
    running: true,
    current: capture.heading || context.id,
    platform: 'boss',
    errors: 0,
    message: '已读取 BOSS 动态简历，正在保存本地'
  }));
  return importBridgeCapture({
    profile: extracted.profile,
    context,
    capture,
    sourceUrl: tabUrl,
    source: 'boss_dynamic_response_bridge'
  });
}

async function importVisibleBossBridge(sender, upstreamContext) {
  const tab = sender && sender.tab;
  const tabUrl = String(tab && tab.url || '');
  if (!tab || !tab.id || !/^https:\/\/(?:[^/]+\.)?zhipin\.com\//i.test(tabUrl)) {
    throw new Error('可见页面桥接仅允许从当前 BOSS 标签页读取');
  }
  const payload = await readTab(tab.id);
  if (payload.blocked) throw new Error('页面要求人工处理：' + payload.blocked);
  if (!hasBossResumeEvidence(payload)) {
    throw new Error('当前 BOSS 页未检测到已展开的候选人简历');
  }
  payload.platform = 'boss';
  payload.source_type = 'boss_visible_page_bridge';
  const upstreamId = String(upstreamContext && upstreamContext.id || '').trim();
  const context = {
    id: upstreamId && upstreamId !== '__loading__'
      ? upstreamId
      : 'visible-' + siderCacheHash(
        String(payload.heading || '') + '|' + String(payload.text || '').slice(0, 4000)
      ),
    platform: 'BOSS直聘'
  };
  await setState(Object.assign({}, await getState(), {
    running: true,
    current: payload.heading || context.id,
    platform: 'boss',
    errors: 0,
    message: '已读取当前可见简历，正在保存本地'
  }));
  return importBridgeCapture({
    profile: null,
    context,
    capture: payload,
    sourceUrl: tabUrl,
    source: 'boss_visible_page_bridge'
  });
}

async function findTtcRecords(tabId, limit) {
  const results = await chrome.scripting.executeScript({
    target: {tabId},
    func: async (maxItems, parserUrl) => {
      const parser = await import(parserUrl);
      return parser.findTtcTableRecords(maxItems);
    },
    args: [limit, chrome.runtime.getURL('parsers/ttc.js')]
  });
  return results[0].result || [];
}

async function openTtcCandidateDetail(listTabId, record) {
  const listTab = await chrome.tabs.get(listTabId);
  const detailUrl = new URL(
    '/app/talent/' + encodeURIComponent(record.person_leads_id),
    listTab.url
  ).href;
  return chrome.tabs.create({
    url: detailUrl,
    active: false,
    windowId: listTab.windowId
  });
}

async function waitForTabComplete(tabId, timeoutMs = 10000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const tab = await chrome.tabs.get(tabId).catch(() => null);
    if (!tab) return null;
    if (tab.status === 'complete') return tab;
    await sleep(200);
  }
  return null;
}

async function waitForTtcPayload(tabId, expectedRecord, timeoutMs = 8000) {
  const start = Date.now();
  let lastPayload = null;
  while (Date.now() - start < timeoutMs) {
    lastPayload = await readTab(tabId).catch(() => null);
    if (lastPayload && lastPayload.blocked) return lastPayload;
    if (isExpectedTtcDetailPayload(lastPayload, expectedRecord)) {
      return lastPayload;
    }
    await sleep(500);
  }
  return null;
}

async function clickTtcNextPage(listTabId) {
  const results = await chrome.scripting.executeScript({
    target: {tabId: listTabId},
    func: async parserUrl => {
      const parser = await import(parserUrl);
      return parser.clickTtcNextPageControl();
    },
    args: [chrome.runtime.getURL('parsers/ttc.js')]
  });
  return results[0].result;
}

async function getTtcCandidateCount(listTabId) {
  const results = await chrome.scripting.executeScript({
    target: {tabId: listTabId},
    func: () => {
      const match = document.body.innerText.match(/(\d+)\s*个候选人/);
      return match ? parseInt(match[1], 10) : 0;
    }
  });
  return results[0].result || 0;
}

async function runTtcBatchImport(limit, sourceTabId = null, currentPageOnly = false) {
  const listTab = sourceTabId
    ? await chrome.tabs.get(sourceTabId).catch(() => null)
    : (await chrome.tabs.query({active: true, currentWindow: true}))[0];
  if (!listTab || !listTab.id) throw new Error('请先打开 ot 人才搜索列表页');
  if (!/app\.ttcadvisory\.com/.test(listTab.url || '')) throw new Error('当前不是 ot 页面');

  if (!limit || limit <= 0) {
    limit = await getTtcCandidateCount(listTab.id);
    if (!limit) limit = 50;
  }
  if (currentPageOnly) limit = Math.min(Number(limit) || 10, 10);

  let currentPageRecords = null;
  if (currentPageOnly) {
    currentPageRecords = await findTtcRecords(listTab.id, limit);
    if (!currentPageRecords.length) throw new Error('ot 当前页未找到可导入的候选人');
    limit = currentPageRecords.length;
  }

  const importedIds = new Set();
  let totalImported = 0;
  let totalSkipped = 0;
  let totalErrors = 0;
  let latestCandidate = '';
  const matchedPeople = [];
  let pageNumber = 1;

  await setState({
    running: true,
    total: limit,
    done: 0,
    skipped: 0,
    matches: [],
    errors: 0,
    current: '',
    platform: 'ot',
    message: '开始自动导入 ot 候选人到云端人才库'
  });

  while (totalImported + totalSkipped + totalErrors < limit) {
    const remaining = limit - (totalImported + totalSkipped + totalErrors);
    const records = currentPageRecords || await findTtcRecords(listTab.id, remaining);
    currentPageRecords = null;
    if (!records.length) {
      // Try to go to next page.
      const next = await clickTtcNextPage(listTab.id);
      if (!next.ok) break;
      pageNumber += 1;
      await setState(Object.assign({}, await getState(), {
        current: '',
        message: '已翻到第 ' + pageNumber + ' 页'
      }));
      await sleep(2000);
      continue;
    }

    for (const record of records) {
      if (importedIds.has(record.person_leads_id)) continue;
      importedIds.add(record.person_leads_id);
      latestCandidate = record.cn_name || record.displayName || latestCandidate;

      await setState(Object.assign({}, await getState(), {
        current: record.cn_name,
        message: '正在打开 ' + record.cn_name
      }));

      let detailTab;
      try {
        detailTab = await openTtcCandidateDetail(listTab.id, record);
        if (!detailTab || !detailTab.id) throw new Error('详情页未打开');
        detailTab = await waitForTabComplete(detailTab.id, 10000);
        if (!detailTab) throw new Error('详情页加载超时');

        const payload = await waitForTtcPayload(detailTab.id, record, 8000);
        if (!payload) throw new Error('详情页内容未加载');
        if (payload.blocked) throw new Error('页面要求人工处理：' + payload.blocked);
        if (!payload.text || payload.text.length < 10) throw new Error('页面文本不足');

        await setState(Object.assign({}, await getState(), {
          message: '正在导入 ' + record.cn_name
        }));

        const result = await importCloudFromPayload(payload);
        await chrome.tabs.remove(detailTab.id).catch(() => {});

        if (result.ok) {
          totalImported += 1;
        } else {
          totalErrors += 1;
        }
      } catch (error) {
        if (detailTab && detailTab.id) await chrome.tabs.remove(detailTab.id).catch(() => {});
        totalErrors += 1;
        await setState(Object.assign({}, await getState(), {
          message: record.cn_name + ' 失败：' + error.message
        }));
      }

      await setState(Object.assign({}, await getState(), {
        done: totalImported,
        skipped: totalSkipped,
        matches: matchedPeople,
        errors: totalErrors,
        current: record.cn_name,
        message: '已导入 ' + totalImported + ' / 跳过 ' + totalSkipped + ' / 失败 ' + totalErrors
      }));

      if (totalImported + totalSkipped + totalErrors >= limit) break;
      await sleep(500 + Math.floor(Math.random() * 500));
    }

    if (totalImported + totalSkipped + totalErrors >= limit) break;
    if (currentPageOnly) break;

    // Move to next page after processing current page.
    const next = await clickTtcNextPage(listTab.id);
    if (!next.ok) break;
    pageNumber += 1;
    await setState(Object.assign({}, await getState(), {
      message: '已翻到第 ' + pageNumber + ' 页'
    }));
    await sleep(2500);
  }

  await setState({
    running: false,
    total: limit,
    done: totalImported,
    skipped: totalSkipped,
    matches: matchedPeople,
    errors: totalErrors,
    current: latestCandidate,
    platform: 'ot',
    message: '完成：导入 ' + totalImported + ' / 跳过 ' + totalSkipped + ' / 失败 ' + totalErrors
  });
  return {imported: totalImported, skipped: totalSkipped, errors: totalErrors};
}

async function startTtcBatchImport(limit, sourceTabId = null, currentPageOnly = false) {
  const state = await getState();
  if (state.running) throw new Error('已有导入任务正在运行');
  await setState(Object.assign({}, state, {
    running: true,
    total: Number(limit) || 0,
    done: 0,
    skipped: 0,
    matches: [],
    errors: 0,
    current: '',
    platform: 'ot',
    message: currentPageOnly ? '正在读取 ot 当前页' : '正在读取 ot 候选人'
  }));
  batchPromise = runTtcBatchImport(limit, sourceTabId, currentPageOnly)
    .catch(async error => {
      await setState(Object.assign({}, await getState(), {
        running: false,
        errors: 1,
        current: '',
        message: '导入失败：' + error.message
      }));
      return {error: error.message};
    })
    .finally(() => { batchPromise = null; });
  return {ok: true, message: '已开始自动导入'};
}

async function autoScrollList(tabId, maxRounds = 6) {
  // 在 BOSS/猎聘/脉脉列表页自动向下滚动，触发懒加载更多候选人卡片。
  await chrome.scripting.executeScript({
    target: {tabId},
    args: [maxRounds],
    func: async max => {
      const sleep = ms => new Promise(r => setTimeout(r, ms));
      const getScrollable = () => {
        const candidates = [
          document.querySelector('.job-recommend-result'),
          document.querySelector('.recommend-list'),
          document.querySelector('[class*="search-list"]'),
          document.querySelector('[class*="candidate-list"]'),
          document.querySelector('main'),
          document.documentElement
        ];
        return candidates.find(el => el && el.scrollHeight > el.clientHeight) || document.documentElement;
      };
      const el = getScrollable();
      for (let i = 0; i < max; i++) {
        const before = el.scrollHeight;
        el.scrollTo({top: el.scrollHeight, behavior: 'smooth'});
        await sleep(1200);
        if (el.scrollHeight === before) break;
      }
      return {scrolled: true};
    }
  });
}

async function findCandidateLinks(tabId, limit) {
  const tab = await chrome.tabs.get(tabId).catch(() => null);
  const platform = platformFromUrl(tab && tab.url ? tab.url : '');
  const parserName = platform === 'boss' || platform === 'maimai' || platform === 'liepin'
    ? platform
    : 'generic';
  const results = await chrome.scripting.executeScript({
    target: {tabId},
    func: async (maxItems, platformName, parserUrl) => {
      const parser = await import(parserUrl);
      if (platformName === 'boss' && parser.findBossCandidateLinks) {
        return parser.findBossCandidateLinks(maxItems);
      }
      if (platformName === 'maimai' && parser.findMaimaiCandidateLinks) {
        return parser.findMaimaiCandidateLinks(maxItems);
      }
      if (platformName === 'liepin' && parser.findLiepinCandidateLinks) {
        return parser.findLiepinCandidateLinks(maxItems);
      }
      if (parser.findGenericCandidateLinks) {
        return parser.findGenericCandidateLinks(maxItems);
      }
      return [];
    },
    args: [limit, platform, chrome.runtime.getURL('parsers/' + parserName + '.js')]
  });
  return results[0].result || [];
}

async function runBatch() {
  let consecutiveErrors = 0;
  while (true) {
    let state = await getState();
    if (!state.running || !state.queue.length) {
      if (state.running) {
        state = Object.assign({}, state, {
          running: false,
          message: '完成，失败 ' + (state.errors || 0) + ' 条'
        });
        await setState(state);
      }
      return;
    }
    const item = state.queue[0];
    const platform = platformFromUrl(item.url || '');
    state = Object.assign({}, state, {current: item.label || item.url, message: '打开页面'});
    await setState(state);
    let tab;
    try {
      tab = await chrome.tabs.create({url: item.url, active: false});
      const loaded = await waitForTabSoft(tab.id);
      if (loaded.timedOut) {
        await pauseForHuman(tab, state, '已暂停：页面加载超时，请在打开的页面确认是否需要登录/验证，完成后点“继续当前批次”');
        return;
      }
      // Base wait for DOM, plus extra SPA settle time for Maimai/Liepin.
      let settleMs = 3500;
      if (platform === 'maimai' || platform === 'liepin') {
        settleMs = 5000 + Math.floor(Math.random() * 2000);
      }
      await sleep(settleMs);

      const payload = await readTab(tab.id);
      if (payload.blocked) {
        await pauseForHuman(tab, state, '已暂停，需要人工处理：' + payload.blocked + '。完成后点“继续当前批次”');
        return;
      }
      if (payload.empty || !payload.text || payload.text.length < 80) {
        await pauseForHuman(tab, state, '已暂停：页面可见内容不足，请确认是否仍在加载、登录或验证页，完成后点“继续当前批次”');
        return;
      }
      const candidate = await saveCapture(payload);
      consecutiveErrors = 0;
      const latest = await getState();
      state = Object.assign({}, latest, {
        queue: latest.queue.slice(1),
        done: latest.done + 1,
        current: candidate.name,
        message: '已写入云端：' + (candidate.name || '当前候选人')
      });
      await setState(state);
      await chrome.tabs.remove(tab.id);
    } catch (error) {
      if (tab && tab.id) await chrome.tabs.remove(tab.id).catch(() => {});
      consecutiveErrors += 1;
      const latest = await getState();
      state = Object.assign({}, latest, {
        queue: latest.queue.slice(1),
        errors: (latest.errors || 0) + 1,
        current: item.label || item.url,
        message: '跳过（' + consecutiveErrors + ' 次连续失败）：' + error.message
      });
      await setState(state);
      if (consecutiveErrors >= 3) {
        await pauseForHuman(null, state, '已暂停：连续 3 次读取失败，请检查页面是否改版或触发风控');
        return;
      }
    }
    const latest = await getState();
    if (!latest.running) return;
    const jitter = Math.floor(Math.random() * 4000);
    await sleep(latest.delaySeconds * 1000 + jitter);
  }
}

async function startBatch(limit, delaySeconds) {
  const old = await getState();
  if (old.running) throw new Error('已有批量任务正在运行');
  const tabs = await chrome.tabs.query({active: true, currentWindow: true});
  const tab = tabs[0];
  if (!tab || !tab.id || !supportedHost(tab.url || '')) {
    throw new Error('请先打开受支持招聘网站的候选人列表页');
  }
  const platform = platformFromUrl(tab.url || '') || '候选人';
  const state1 = await setState({
    running: true,
    queue: [],
    total: 0,
    done: 0,
    errors: 0,
    current: '',
    platform,
    message: '正在滚动加载候选人...',
    delaySeconds
  });
  await autoScrollList(tab.id, 6);
  const links = await findCandidateLinks(tab.id, limit);
  if (!links.length) {
    await setState(Object.assign({}, state1, {running: false, message: '当前页面未识别到候选人链接'}));
    throw new Error('当前页面未识别到候选人链接；请滚动让候选人卡片加载后重试');
  }
  const state = await setState({
    running: true,
    queue: links,
    total: links.length,
    done: 0,
    errors: 0,
    current: '',
    platform,
    message: '已发现 ' + links.length + ' 个候选人',
    delaySeconds
  });
  batchPromise = runBatch().finally(() => { batchPromise = null; });
  return state;
}

async function resumeBatch() {
  const state = await getState();
  if (state.running) throw new Error('已有批量任务正在运行');
  if (!state.queue || !state.queue.length) throw new Error('没有可继续的批量队列');

  if (state.pausedTabId) {
    const tab = await chrome.tabs.get(state.pausedTabId).catch(() => null);
    if (tab && tab.id) {
      const payload = await readTab(tab.id);
      if (payload.blocked || payload.empty || !payload.text || payload.text.length < 80) {
        await pauseForHuman(tab, state, payload.blocked ?
          '仍需人工处理：' + payload.blocked :
          '仍未读到候选人内容，请确认当前页已经加载出简历详情');
        return await getState();
      }
      const candidate = await saveCapture(payload);
      await chrome.tabs.remove(tab.id).catch(() => {});
      const updated = await setState(Object.assign({}, state, {
        queue: state.queue.slice(1),
        done: (state.done || 0) + 1,
        current: candidate.name,
        paused: false,
        pausedTabId: null,
        message: '已写入云端：' + (candidate.name || '当前候选人') + '，继续当前批次'
      }));
      if (!updated.queue.length) {
        return await setState(Object.assign({}, updated, {
          running: false,
          current: '',
          message: '完成，失败 ' + (updated.errors || 0) + ' 条'
        }));
      }
      const nextRunning = await setState(Object.assign({}, updated, {running: true}));
      batchPromise = runBatch().finally(() => { batchPromise = null; });
      return nextRunning;
    }
  }

  const next = await setState(Object.assign({}, state, {
    running: true,
    paused: false,
    pausedTabId: null,
    message: '继续当前批次'
  }));
  batchPromise = runBatch().finally(() => { batchPromise = null; });
  return next;
}

async function testCandidateLinks(limit) {
  const tabs = await chrome.tabs.query({active: true, currentWindow: true});
  const tab = tabs[0];
  if (!tab || !tab.id || !supportedHost(tab.url || '')) {
    throw new Error('请先打开受支持招聘网站的候选人列表页');
  }
  const links = await findCandidateLinks(tab.id, limit);
  return links;
}

async function startGmailBatch(limit) {
  const tabs = await chrome.tabs.query({active: true, currentWindow: true});
  const tab = tabs[0];
  if (!tab || !tab.id || !/^https:\/\/mail\.google\.com\//.test(tab.url || '')) {
    throw new Error('请先在当前标签页打开并登录 Gmail');
  }
  await chrome.storage.local.set({
    gmailDownloadWindowUntil: Date.now() + 15 * 60 * 1000
  });
  const results = await chrome.scripting.executeScript({
    target: {tabId: tab.id},
    args: [Math.max(1, Math.min(10, limit))],
    func: async maxItems => {
      window.__TTC_GMAIL_STOP = false;
      const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
      const waitFor = async (test, timeout = 12000) => {
        const start = Date.now();
        while (Date.now() - start < timeout) {
          const value = test();
          if (value) return value;
          await sleep(300);
        }
        return null;
      };
      const keywords = /(简历|应聘|候选人|求职|resume|\bcv\b|curriculum)/i;
      const rowKey = row => row.getAttribute('data-legacy-thread-id') ||
        row.getAttribute('data-thread-id') || row.id || '';
      const rowSubject = row => {
        const subject = row.querySelector('.bog,.bqe,[data-thread-id] [role=link]');
        return (subject && subject.textContent || row.innerText || '').replace(/\s+/g, ' ').trim();
      };
      const initialRows = Array.from(document.querySelectorAll('tr.zA'));
      const targets = initialRows
        .map(row => ({key: rowKey(row), subject: rowSubject(row)}))
        .filter(item => keywords.test(item.subject))
        .slice(0, maxItems);
      if (!targets.length) {
        return {ok: false, message: '当前 Gmail 列表未找到包含简历关键词的邮件'};
      }
      let opened = 0;
      let downloads = 0;
      let noAttachment = 0;
      for (const target of targets) {
        if (window.__TTC_GMAIL_STOP) break;
        const rows = Array.from(document.querySelectorAll('tr.zA'));
        const row = rows.find(item => (target.key && rowKey(item) === target.key) ||
          rowSubject(item) === target.subject);
        if (!row) continue;
        row.click();
        const messageView = await waitFor(() => document.querySelector('.a3s,.adn'));
        if (!messageView) continue;
        opened += 1;
        await sleep(1200);
        const selectors = [
          '.aQH .aQw', '.aZo .aQw', '[download_url]',
          '[aria-label*="下载"]', '[aria-label*="Download"]',
          '[data-tooltip*="下载"]', '[data-tooltip*="Download"]'
        ];
        const buttons = Array.from(new Set(
          selectors.flatMap(selector => Array.from(document.querySelectorAll(selector)))
        )).filter(element => {
          const rect = element.getBoundingClientRect();
          const label = (element.getAttribute('aria-label') ||
            element.getAttribute('data-tooltip') || element.textContent || '').trim();
          return rect.width > 0 && rect.height > 0 &&
            !/(全部下载到云端硬盘|Save all to Drive)/i.test(label);
        }).slice(0, 12);
        if (!buttons.length) {
          noAttachment += 1;
        } else {
          for (const button of buttons) {
            button.click();
            downloads += 1;
            await sleep(800);
          }
        }
        await sleep(1200);
        const back = document.querySelector(
          '[aria-label*="返回收件箱"],[aria-label*="Back to Inbox"],' +
          '[data-tooltip*="返回收件箱"],[data-tooltip*="Back to Inbox"]'
        );
        if (back) back.click(); else history.back();
        await waitFor(() => document.querySelector('tr.zA'));
        await sleep(900);
      }
      return {
        ok: true,
        message: '已阅读 ' + opened + ' 封邮件，触发 ' + downloads +
          ' 个附件下载，无附件 ' + noAttachment + ' 封'
      };
    }
  });
  const result = results[0].result;
  if (!result || !result.ok) throw new Error((result && result.message) || 'Gmail 页面自动化失败');
  return result;
}

chrome.downloads.onChanged.addListener(async delta => {
  if (!delta.state || delta.state.current !== 'complete') return;
  const data = await chrome.storage.local.get('gmailDownloadWindowUntil');
  if (!data.gmailDownloadWindowUntil || Date.now() > data.gmailDownloadWindowUntil) return;
  const items = await chrome.downloads.search({id: delta.id});
  const item = items[0];
  if (!item || !/\.(pdf|doc|docx)$/i.test(item.filename || '')) return;
  try {
    await fetch(LOCAL_IMPORT_API, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        path: item.filename,
        source_url: item.referrer || item.finalUrl || 'https://mail.google.com/'
      })
    });
  } catch (_error) {
    // 本地服务状态会显示导入失败；不影响浏览器下载本身。
  }
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || !OT_BACKGROUND_MESSAGE_TYPES.has(message.type)) return false;

  (async () => {
    if (message.type === 'otUserStatusFetch') {
      return await fetchCopilotUserStatus(message);
    }
    if (message.type === 'captureCurrent') {
      const candidate = await captureCurrent();
      return {ok: true, candidate};
    }
    if (message.type === 'importFeishu' || message.type === 'importCloud') {
      const result = await importCloudCurrent(Boolean(message.dryRun), sender.tab && sender.tab.id);
      return Object.assign({ok: Boolean(result.ok)}, result);
    }
    if (message.type === 'autoImportCurrentDetail') {
      const result = await importCloudCurrent(false, sender.tab && sender.tab.id);
      return Object.assign({ok: Boolean(result.ok), targetCloud: TARGET_CLOUD}, result);
    }
    if (message.type === 'autoImportCurrentPage') {
      const senderUrl = String(sender && sender.tab && sender.tab.url || '');
      if (/^https:\/\/(?:[^/]+\.)?zhipin\.com\//i.test(senderUrl)) {
        return await importVisibleBossBridge(sender, message.upstreamContext || null);
      }
      const result = await importCloudCurrent(false, sender.tab && sender.tab.id);
      const candidate = result.candidate || {};
      await setState(Object.assign({}, await getState(), {
        current: candidate.name || '',
        errors: 0,
        message: '自动入库已启用'
      }));
      return Object.assign({ok: Boolean(result.ok), targetCloud: TARGET_CLOUD}, result);
    }
    if (message.type === 'importSiderProfile') {
      return await importSiderProfileBridge(message, sender);
    }
    if (message.type === 'importBossApiProfile') {
      return await importBossApiProfileBridge(message, sender);
    }
    if (message.type === 'getCandidateCacheIndex') {
      const data = await chrome.storage.local.get([
        'ot_candidate_cache_index',
        'ot_candidate_cache_latest'
      ]);
      return {
        ok: true,
        index: Array.isArray(data.ot_candidate_cache_index)
          ? data.ot_candidate_cache_index
          : [],
        latest: data.ot_candidate_cache_latest || null
      };
    }
    if (message.type === 'startTtcBatchImport') {
      return await startTtcBatchImport(message.limit || 50, sender.tab && sender.tab.id, false);
    }
    if (message.type === 'autoImportTtcSearchList') {
      return await startTtcBatchImport(Math.min(message.limit || 10, 10), sender.tab && sender.tab.id, true);
    }
    if (message.type === 'ping') {
      return {ok: true, version: EXTENSION_VERSION, targetCloud: TARGET_CLOUD};
    }
    if (message.type === 'validatePage') {
      const tabs = await chrome.tabs.query({active: true, currentWindow: true});
      const tab = tabs[0];
      if (!tab || !tab.id || !/^https?:/.test(tab.url || '')) throw new Error('当前不是可验证网页');
      const payload = await readTab(tab.id);
      payload.platform = platformFromUrl(tab.url);
      if (payload.platform === 'maimai' || payload.platform === 'liepin') {
        payload.links = await findCandidateLinks(tab.id, 1);
      }
      return {ok: true, checks: validatePayload(payload)};
    }
    if (message.type === 'startBatch') {
      const state = await startBatch(message.limit || 5, message.delaySeconds || 12);
      return {ok: true, state};
    }
    if (message.type === 'resumeBatch') {
      const state = await resumeBatch();
      return {ok: true, state};
    }
    if (message.type === 'testLinks') {
      const links = await testCandidateLinks(message.limit || 5);
      return {ok: true, links};
    }
    if (message.type === 'startGmailBatch') {
      const result = await startGmailBatch(message.limit || 5);
      return {ok: true, message: result.message};
    }
    if (message.type === 'stopBatch') {
      const state = await getState();
      const gmailTabs = await chrome.tabs.query({url: 'https://mail.google.com/*'});
      for (const tab of gmailTabs) {
        if (!tab.id) continue;
        await chrome.scripting.executeScript({
          target: {tabId: tab.id},
          func: () => { window.__TTC_GMAIL_STOP = true; }
        }).catch(() => {});
      }
      return {ok: true, state: await setState(Object.assign({}, state, {
        running: false,
        message: '已请求停止'
      }))};
    }
    if (message.type === 'getStatus') return {ok: true, state: await getState()};
    throw new Error('OT 后台消息尚未实现: ' + message.type);
  })().then(sendResponse).catch(error => sendResponse({ok: false, error: error.message}));
  return true;
});
