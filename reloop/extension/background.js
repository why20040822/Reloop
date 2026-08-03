const API = 'http://127.0.0.1:8765/api/capture';
const LOCAL_IMPORT_API = 'http://127.0.0.1:8765/api/import-local-download';
const EXTENSION_VERSION = '0.3.1';

import { detectRisk, platformFromUrl, supportedHost as importedSupportedHost } from './parsers/common.js';
import { validatePayload } from './validation.js';


const SUPPORTED = [
  'zhipin.com', 'liepin.com', 'maimai.cn',
  'linkedin.com', '51job.com', 'zhaopin.com'
];
let batchPromise = null;

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const getState = () => chrome.storage.local.get('batch').then(data => data.batch || {
  running: false, queue: [], total: 0, done: 0, errors: 0, current: '', message: '空闲'
});
const setState = state => chrome.storage.local.set({batch: state}).then(() => state);
const RISK_WORDS = [
  '安全验证', '请输入验证码', '访问过于频繁', '操作过于频繁',
  '异常访问', '请完成验证', '登录后查看', '账号登录', '登录后使用',
  '请登录', '滑块验证', '人机验证', '验证身份', '访问验证',
  'captcha', 'verify you are human'
];
const NON_CANDIDATE_LABELS = [
  '桌面客户端', '下载APP', '下载 App', '下载客户端', '手机扫码',
  '打开APP', '打开 App', '登录', '注册', '帮助中心', '隐私政策',
  '用户协议', '职位管理', '招聘者', '企业服务'
];

function supportedHost(url) {
  return importedSupportedHost(url);
}

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

function looksLikeNonCandidateLabel(label) {
  const text = (label || '').replace(/\s+/g, '');
  return !text || NON_CANDIDATE_LABELS.some(word => text.includes(word.replace(/\s+/g, '')));
}

function looksLikeCandidateText(text) {
  return /(\d+\s*岁|\d+\s*年|本科|硕士|博士|大专|统招|在职|离职|求职|期望|工作经历|教育经历|咨询|战略|品牌|产品|渠道|运营|市场|经理|总监|负责人)/.test(text || '');
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
  chrome.storage.local.set({
    workerStatus: {
      ok: true,
      version: EXTENSION_VERSION,
      installedAt: new Date().toISOString()
    }
  });
});

chrome.runtime.onStartup.addListener(() => {
  chrome.storage.local.set({
    workerStatus: {
      ok: true,
      version: EXTENSION_VERSION,
      startedAt: new Date().toISOString()
    }
  });
});

async function readTab(tabId) {
  const tab = await chrome.tabs.get(tabId).catch(() => null);
  const platform = platformFromUrl(tab && tab.url ? tab.url : '');
  const parserFiles = ['parsers/common.js'];
  if (platform === 'boss') parserFiles.push('parsers/boss.js');
  if (platform === 'maimai') parserFiles.push('parsers/maimai.js');
  if (platform === 'liepin') parserFiles.push('parsers/liepin.js');

  const results = await chrome.scripting.executeScript({
    target: {tabId},
    files: parserFiles,
    func: (platformName) => {
      const text = document.body ? document.body.innerText : '';
      const title = document.title || '';
      const url = location.href;
      const parsers = window.__TTC_PARSERS || {};
      const common = parsers.common || {};
      const detectRisk = common.detectRisk || function(t, ti, u) {
        const words = [
          '安全验证', '请输入验证码', '访问过于频繁', '操作过于频繁',
          '异常访问', '请完成验证', '登录后查看', '账号登录', '登录后使用',
          '请登录', '滑块验证', '人机验证', '验证身份', '访问验证',
          'captcha', 'verify you are human'
        ];
        return words.find(w => (t + ti + u).toLowerCase().includes(w.toLowerCase())) || '';
      };
      const blocked = detectRisk(text, title, url);

      // Wait helper for SPA platforms.
      const waitForStable = (ms = 1500) => new Promise(r => setTimeout(r, ms));
      if (platformName === 'maimai' || platformName === 'liepin') {
        // We cannot truly block here because executeScript func is synchronous,
        // but we can read document.readyState and rely on the caller's sleep.
      }

      let structured = null;
      if (platformName === 'boss' && parsers.boss && parsers.boss.extractBossSections) {
        structured = parsers.boss.extractBossSections();
      }
      if (platformName === 'maimai' && parsers.maimai && parsers.maimai.extractMaimaiSections) {
        structured = parsers.maimai.extractMaimaiSections();
      }
      if (platformName === 'liepin' && parsers.liepin && parsers.liepin.extractLiepinSections) {
        structured = parsers.liepin.extractLiepinSections();
      }

      return {
        url,
        title,
        heading: (document.querySelector('h1') && document.querySelector('h1').innerText) ||
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
    args: [platform]
  });
  return results[0].result;
}

async function saveCapture(payload) {
  const response = await fetch(API, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload)
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || '本地入库失败');
  return data.candidate;
}

async function captureCurrent() {
  const tabs = await chrome.tabs.query({active: true, currentWindow: true});
  const tab = tabs[0];
  if (!tab || !tab.id || !/^https?:/.test(tab.url || '')) throw new Error('当前不是可收藏网页');
  // 手动收藏时拦截明显的 BOSS 后台/列表页，避免误入库
  if (/zhipin\.com/.test(new URL(tab.url).hostname)) {
    const managementPaths = /\/chat\/|\/manage\/|\/tools\/|\/prop\/|\/vip\/|\/data\/|\/job_list\/| ka=action/;
    if (managementPaths.test(tab.url)) {
      throw new Error('当前是 BOSS 后台或列表导航页，请打开单个候选人简历页再收藏');
    }
  }
  const payload = await readTab(tab.id);
  if (payload.blocked) throw new Error('页面要求人工处理：' + payload.blocked);
  if (!payload.text || payload.text.length < 10) throw new Error('当前页面没有足够可见文本');
  payload.source_type = 'authorized_visible_page';
  return saveCapture(payload);
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
  const parserFiles = ['parsers/common.js'];
  if (platform === 'boss') parserFiles.push('parsers/boss.js');
  else if (platform === 'maimai') parserFiles.push('parsers/maimai.js');
  else if (platform === 'liepin') parserFiles.push('parsers/liepin.js');
  else parserFiles.push('parsers/generic.js');

  const results = await chrome.scripting.executeScript({
    target: {tabId},
    files: parserFiles,
    func: (maxItems, platformName) => {
      const parsers = window.__TTC_PARSERS || {};
      if (platformName === 'boss' && parsers.boss && parsers.boss.findBossCandidateLinks) {
        return parsers.boss.findBossCandidateLinks(maxItems);
      }
      if (platformName === 'maimai' && parsers.maimai && parsers.maimai.findMaimaiCandidateLinks) {
        return parsers.maimai.findMaimaiCandidateLinks(maxItems);
      }
      if (platformName === 'liepin' && parsers.liepin && parsers.liepin.findLiepinCandidateLinks) {
        return parsers.liepin.findLiepinCandidateLinks(maxItems);
      }
      if (parsers.generic && parsers.generic.findGenericCandidateLinks) {
        return parsers.generic.findGenericCandidateLinks(maxItems);
      }
      return [];
    },
    args: [limit, platform]
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
          current: '',
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
        message: '已收藏 ' + candidate.name + '（' + candidate.score + '分）'
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
  const state1 = await setState({
    running: true,
    queue: [],
    total: 0,
    done: 0,
    errors: 0,
    current: '',
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
        message: '已收藏 ' + candidate.name + '（' + candidate.score + '分），继续当前批次'
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

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  (async () => {
    if (message.type === 'captureCurrent') {
      const candidate = await captureCurrent();
      return {ok: true, candidate};
    }
    if (message.type === 'ping') {
      return {ok: true, version: EXTENSION_VERSION};
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
    return {ok: false, error: '未知操作'};
  })().then(sendResponse).catch(error => sendResponse({ok: false, error: error.message}));
  return true;
});
