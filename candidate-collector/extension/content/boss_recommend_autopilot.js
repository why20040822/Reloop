/**
 * BOSS 推荐页（/web/chat/recommend）全天自动入库链路。
 *
 * 职责边界：只负责“在推荐列表里逐个打开候选人”。识别、解析、本地缓存与
 * 云端入库仍由 content/auto_import.js + background.js 的既有桥接完成——
 * 点击卡片后 BOSS 会拉取详情（动态响应桥接）并渲染简历抽屉（可见页面桥接），
 * 两条既有链路会自动接力，本模块通过 batch 状态观察入库结果并推进队列。
 */
(function () {
  'use strict';

  const STATE_KEY = 'bossRecommendAuto';
  const LOCK_KEY = 'bossRecommendAutoLock';
  const PROFILE_MARKERS = [
    '个人优势', '工作经历', '经历概览', '项目经历', '教育经历', '技能专长',
    '求职期望', '求职意向', '个人简介', '基本信息'
  ];
  const PERSON_ATTRIBUTE_RE = /(\d+\s*岁|本科|硕士|博士|大专|MBA|EMBA)/;
  const COMPANY_RE = /(有限公司|有限责任公司|股份有限公司|集团|分公司|工作室)/;
  const NON_CANDIDATE_RE = /(桌面客户端|下载App|下载APP|登录|注册|隐私|协议|职位管理|招聘者|企业服务|帮助中心)/;
  const RISK_RE = /(安全验证|人机验证|滑动验证|拖动滑块|访问过于频繁|操作过于频繁|网络异常|请稍后再试|captcha|异常流量)/i;
  const SUCCESS_MESSAGE_RE = /(完成自动入库|已写入云端|已更新|已保存本地)/;
  const FAILURE_MESSAGE_RE = /(失败|拒绝|异常)/;

  const CLICK_SETTLE_MS = 2500;
  const IMPORT_WAIT_MS = 30000;
  const BETWEEN_CANDIDATES_MS = [7000, 15000];
  const RESCAN_IDLE_MS = [90000, 180000];
  const MAX_PROCESSED_KEYS = 1500;
  const MAX_CARD_TEXT = 800;

  function isRecommendPage(pathname) {
    return /^\/web\/chat\/recommend/.test(String(pathname || ''));
  }

  function simpleHash(value) {
    let hash = 2166136261;
    const text = String(value || '');
    for (let index = 0; index < text.length; index += 1) {
      hash ^= text.charCodeAt(index);
      hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0).toString(16);
  }

  function markerCount(text) {
    return PROFILE_MARKERS.filter(marker => text.includes(marker)).length;
  }

  /**
   * 推荐卡片：必须有“年龄或学历”这类个人属性（公司卡片只有成立年限），
   * 不能是公司名，且不是已经展开的简历抽屉（抽屉含 2 个以上分节标题）。
   */
  function isCandidateCardText(text) {
    const value = String(text || '').replace(/\s+/g, ' ').trim();
    if (value.length < 8 || value.length > MAX_CARD_TEXT) return false;
    if (NON_CANDIDATE_RE.test(value) || COMPANY_RE.test(value)) return false;
    if (markerCount(value) >= 2) return false;
    if (!PERSON_ATTRIBUTE_RE.test(value)) return false;
    return true;
  }

  function detectRiskControl(text) {
    return RISK_RE.test(String(text || ''));
  }

  function cardKey(href, text) {
    if (href) return 'href|' + String(href).split('#')[0];
    const compact = String(text || '').replace(/\s+/g, '').slice(0, 120);
    return 'text|' + simpleHash(compact);
  }

  function todayKey(now) {
    const date = now ? new Date(now) : new Date();
    return date.getFullYear() + '-' +
      String(date.getMonth() + 1).padStart(2, '0') + '-' +
      String(date.getDate()).padStart(2, '0');
  }

  function defaultState() {
    return {
      enabled: false,
      day: todayKey(),
      processedToday: 0,
      importedToday: 0,
      failedToday: 0,
      totalProcessed: 0,
      processedKeys: [],
      lastName: '',
      message: '未开启',
      updatedAt: 0
    };
  }

  function normalizeState(value) {
    const state = Object.assign(defaultState(), value || {});
    if (!Array.isArray(state.processedKeys)) state.processedKeys = [];
    const today = todayKey();
    if (state.day !== today) {
      state.day = today;
      state.processedToday = 0;
      state.importedToday = 0;
      state.failedToday = 0;
    }
    return state;
  }

  function classifyImportMessage(message) {
    const text = String(message || '');
    if (FAILURE_MESSAGE_RE.test(text)) return 'failed';
    if (SUCCESS_MESSAGE_RE.test(text)) return 'imported';
    return '';
  }

  function randomBetween(range) {
    const [min, max] = range;
    return min + Math.floor(Math.random() * Math.max(1, max - min));
  }

  const api = {
    isRecommendPage,
    isCandidateCardText,
    detectRiskControl,
    cardKey,
    markerCount,
    classifyImportMessage,
    normalizeState,
    defaultState,
    STATE_KEY
  };
  globalThis.__OT_BOSS_RECOMMEND_AUTOPILOT__ = api;

  const hasRuntime = typeof chrome !== 'undefined' && chrome.storage && chrome.storage.local;
  const hasDocument = typeof document !== 'undefined' && typeof location !== 'undefined';
  if (!hasRuntime || !hasDocument || !isRecommendPage(location.pathname)) return;
  if (globalThis.__OT_RUNTIME_RECOVERY__ && globalThis.__OT_RUNTIME_RECOVERY__.invalidated) return;

  let state = defaultState();
  let running = false;
  let stopped = false;
  let loopPromise = null;
  let lockToken = simpleHash(String(Math.random()) + String(Date.now())) + '-' + Date.now();
  let lockHeartbeat = null;

  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

  async function loadState() {
    const data = await chrome.storage.local.get(STATE_KEY).catch(() => ({}));
    state = normalizeState(data && data[STATE_KEY]);
    return state;
  }

  async function saveState(patch) {
    state = normalizeState(Object.assign({}, state, patch || {}, {updatedAt: Date.now()}));
    await chrome.storage.local.set({[STATE_KEY]: state}).catch(() => {});
    return state;
  }

  async function acquireLock() {
    const data = await chrome.storage.local.get(LOCK_KEY).catch(() => ({}));
    const lock = data && data[LOCK_KEY];
    const now = Date.now();
    if (lock && lock.token !== lockToken && now - Number(lock.at || 0) < 45000) {
      return false;
    }
    await chrome.storage.local.set({[LOCK_KEY]: {token: lockToken, at: now}}).catch(() => {});
    return true;
  }

  function startLockHeartbeat() {
    stopLockHeartbeat();
    lockHeartbeat = setInterval(() => {
      if (stopped || !running) return;
      chrome.storage.local.set({[LOCK_KEY]: {token: lockToken, at: Date.now()}}).catch(() => {});
    }, 20000);
  }

  function stopLockHeartbeat() {
    if (lockHeartbeat) clearInterval(lockHeartbeat);
    lockHeartbeat = null;
  }

  async function holdsLock() {
    const data = await chrome.storage.local.get(LOCK_KEY).catch(() => ({}));
    const lock = data && data[LOCK_KEY];
    return Boolean(lock && lock.token === lockToken);
  }

  function visible(element) {
    if (!element || !element.getBoundingClientRect) return false;
    const rect = element.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  function collectCards() {
    const found = new Map();
    const add = (element, href, text, score) => {
      if (!element || !visible(element)) return;
      const key = cardKey(href, text);
      const old = found.get(key);
      if (!old || score > old.score) found.set(key, {element, key, text, score});
    };

    for (const anchor of document.querySelectorAll('a[href*="/geek/"], a[href*="/jobhunter/"]')) {
      const card = anchor.closest('[class*="card"], [class*="item"], [class*="geek"], li') || anchor;
      const text = (card.innerText || anchor.innerText || '').trim();
      if (!isCandidateCardText(text)) continue;
      add(card, anchor.href, text, 10);
    }

    const candidates = document.querySelectorAll(
      '[class*="card"], [class*="geek"], [class*="candidate"], [class*="recommend"] li, [class*="list"] li'
    );
    for (const node of candidates) {
      const text = (node.innerText || '').trim();
      if (!isCandidateCardText(text)) continue;
      add(node, '', text, 4);
    }
    return Array.from(found.values());
  }

  function clickCard(card) {
    const target = card.element.querySelector('a, button, [role="button"]') || card.element;
    card.element.scrollIntoView({block: 'center', behavior: 'smooth'});
    target.click();
  }

  function cardDisplayName(text) {
    const line = String(text || '').split('\n').map(item => item.trim()).filter(Boolean)[0] || '';
    return line.slice(0, 30);
  }

  async function readBatchState() {
    const data = await chrome.storage.local.get('batch').catch(() => ({}));
    return (data && data.batch) || null;
  }

  async function waitImportOutcome(startedAt) {
    const deadline = Date.now() + IMPORT_WAIT_MS;
    let sawRunning = false;
    while (Date.now() < deadline) {
      if (stopped || !running) return 'stopped';
      if (detectRiskControl(document.body ? document.body.innerText : '')) return 'risk';
      const batch = await readBatchState();
      if (batch && Number(batch.updatedAt || 0) >= startedAt - 1000) {
        if (batch.running && batch.platform === 'boss') sawRunning = true;
        if (sawRunning && !batch.running) {
          return classifyImportMessage(batch.message) || 'imported';
        }
        if (!batch.running && !sawRunning) {
          const outcome = classifyImportMessage(batch.message);
          if (outcome) return outcome;
        }
      }
      await sleep(1000);
    }
    return 'timeout';
  }

  function scrollList() {
    const scrollables = [
      document.querySelector('[class*="recommend"]'),
      document.querySelector('[class*="chat-list"]'),
      document.querySelector('[class*="list"]'),
      document.querySelector('main')
    ].filter(element => element && element.scrollHeight > element.clientHeight + 50);
    for (const element of scrollables.slice(0, 2)) {
      element.scrollTop = element.scrollHeight;
    }
    window.scrollTo({top: document.documentElement.scrollHeight, behavior: 'smooth'});
  }

  function unprocessed(cards) {
    const seen = new Set(state.processedKeys);
    return cards.filter(card => !seen.has(card.key));
  }

  function rememberKey(key) {
    const next = state.processedKeys.concat(key);
    return next.slice(Math.max(0, next.length - MAX_PROCESSED_KEYS));
  }

  async function runLoop() {
    if (loopPromise) return loopPromise;
    loopPromise = (async () => {
      startLockHeartbeat();
      let idleRounds = 0;
      while (running && !stopped) {
        if (!await holdsLock()) {
          running = false;
          break;
        }
        const bodyText = document.body ? document.body.innerText : '';
        if (detectRiskControl(bodyText)) {
          await saveState({message: '检测到风控/验证页面，已暂停 5 分钟'});
          await sleep(5 * 60 * 1000);
          continue;
        }

        const cards = collectCards();
        const queue = unprocessed(cards);
        if (!queue.length) {
          idleRounds += 1;
          scrollList();
          if (idleRounds <= 3) {
            await saveState({message: '正在加载更多推荐候选人（第 ' + idleRounds + ' 轮）'});
            await sleep(3000);
          } else {
            await saveState({message: '推荐已读完，等待新推荐刷新'});
            await sleep(randomBetween(RESCAN_IDLE_MS));
          }
          continue;
        }
        idleRounds = 0;

        const card = queue[0];
        const name = cardDisplayName(card.text);
        await saveState({message: '正在打开推荐候选人：' + name, lastName: name});
        const startedAt = Date.now();
        clickCard(card);
        await sleep(CLICK_SETTLE_MS);
        const outcome = await waitImportOutcome(startedAt);
        if (outcome === 'stopped') break;
        if (outcome === 'risk') {
          await saveState({message: '检测到风控/验证页面，已暂停 5 分钟'});
          await sleep(5 * 60 * 1000);
          continue;
        }

        const patch = {
          processedKeys: rememberKey(card.key),
          processedToday: state.processedToday + 1,
          totalProcessed: state.totalProcessed + 1,
          lastName: name
        };
        if (outcome === 'imported') {
          patch.importedToday = state.importedToday + 1;
          patch.message = '已入库：' + name;
        } else if (outcome === 'failed') {
          patch.failedToday = state.failedToday + 1;
          patch.message = '入库失败：' + name;
        } else {
          patch.failedToday = state.failedToday + 1;
          patch.message = '未识别到完整简历：' + name;
        }
        await saveState(patch);
        await sleep(randomBetween(BETWEEN_CANDIDATES_MS));
      }
      stopLockHeartbeat();
      if (!stopped && !running) {
        await saveState({message: state.enabled ? '已在其他标签页运行' : '已停止'});
      }
    })().finally(() => { loopPromise = null; });
    return loopPromise;
  }

  async function setEnabled(enabled) {
    if (enabled && running) return;
    if (enabled) {
      if (!await acquireLock()) {
        await saveState({enabled: true, message: '另一个推荐页标签页正在运行'});
        return;
      }
      running = true;
      await saveState({enabled: true, message: '推荐页自动入库已开启'});
      void runLoop();
      return;
    }
    running = false;
    await saveState({enabled: false, message: '已手动停止'});
  }

  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== 'local' || !changes || !changes[STATE_KEY]) return;
    const next = normalizeState(changes[STATE_KEY].newValue);
    const wasEnabled = state.enabled;
    state = next;
    if (next.enabled && !wasEnabled) void setEnabled(true);
    if (!next.enabled && wasEnabled) { running = false; }
  });

  const invalidatedEvent = globalThis.__OT_RUNTIME_RECOVERY__ &&
    globalThis.__OT_RUNTIME_RECOVERY__.invalidatedEvent ||
    'ot:extension-context-invalidated';
  window.addEventListener(invalidatedEvent, () => {
    stopped = true;
    running = false;
    stopLockHeartbeat();
  });

  void loadState().then(async () => {
    if (state.enabled) {
      // 页面刷新后自动恢复全天任务；锁已被其他标签页持有时静默退出。
      if (await acquireLock()) {
        running = true;
        await saveState({message: '推荐页自动入库已恢复'});
        void runLoop();
      }
    }
  });
})();
