import assert from 'node:assert/strict';

class FakeElement {
  constructor(id = '') {
    this.id = id;
    this.textContent = '';
    this.className = '';
    this.hidden = false;
    this.disabled = false;
    this.style = {};
    this.attributes = new Map();
    this.listeners = new Map();
    this.classList = {
      toggle: (name, force) => {
        const classes = new Set(this.className.split(/\s+/).filter(Boolean));
        if (force) classes.add(name); else classes.delete(name);
        this.className = Array.from(classes).join(' ');
      }
    };
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  addEventListener(name, callback) {
    this.listeners.set(name, callback);
  }
}

const ids = [
  'statusDot', 'statusTitle', 'statusMessage', 'progress', 'progressText',
  'progressBar', 'recentCard', 'candidateName', 'platformTag', 'relativeTime',
  'version', 'autoToggle', 'autoStats',
];
const elements = Object.fromEntries(ids.map(id => [id, new FakeElement(id)]));
const progressTrack = new FakeElement('progressTrack');
elements.progress.querySelector = selector =>
  selector === '[role="progressbar"]' ? progressTrack : null;

globalThis.document = {
  getElementById(id) { return elements[id] || null; },
};

const batchState = {
  running: true,
  done: 2,
  total: 10,
  errors: 0,
  current: '张三',
  platform: 'ttc',
  updatedAt: Date.now(),
  message: '正在导入张三',
};

const storageValues = new Map();
globalThis.chrome = {
  runtime: {
    lastError: null,
    getManifest() { return {version: '4.8.0'}; },
    sendMessage(message, callback) {
      queueMicrotask(() => callback(
        message.type === 'getStatus'
          ? {ok: true, state: batchState}
          : {ok: true, version: '4.8.0'}
      ));
    },
  },
  storage: {
    local: {
      async get(key) {
        const value = storageValues.get(key);
        return value === undefined ? {} : {[key]: value};
      },
      async set(values) {
        for (const [key, value] of Object.entries(values)) storageValues.set(key, value);
      },
    },
  },
};

const realSetInterval = globalThis.setInterval;
const refreshIntervals = [];
globalThis.setInterval = callback => {
  refreshIntervals.push(callback);
  return refreshIntervals.length;
};
await import(new URL('./popup.js?test=' + Date.now(), import.meta.url).href);
await new Promise(resolve => setTimeout(resolve, 10));
globalThis.setInterval = realSetInterval;

assert.equal(elements.version.textContent, 'v4.8.0');
assert.equal(elements.statusTitle.textContent, '正在导入');
assert.equal(elements.statusDot.className, 'status-dot is-running');
assert.equal(elements.statusMessage.textContent, '正在导入张三');
assert.equal(elements.progress.hidden, false);
assert.equal(elements.progressText.textContent, '2 / 10');
assert.equal(elements.progressBar.style.width, '20%');
assert.equal(progressTrack.attributes.get('aria-valuenow'), '20');
assert.equal(elements.recentCard.hidden, false);
assert.equal(elements.candidateName.textContent, '张三');
assert.equal(elements.platformTag.textContent, 'ot');
assert.equal(elements.relativeTime.textContent, '刚刚');

Object.assign(batchState, {
  running: false,
  errors: 1,
  message: '已更新云端人才库中的候选人',
});
await refreshIntervals[0]();
await new Promise(resolve => setTimeout(resolve, 0));
assert.equal(elements.statusTitle.textContent, '状态正常');
assert.equal(elements.statusMessage.textContent, '自动入库已启用');

// 推荐页自动化开关：默认未开启 → 点击后写入 enabled=true
assert.equal(elements.autoToggle.textContent, '开启自动入库');
await elements.autoToggle.listeners.get('click')();
await new Promise(resolve => setTimeout(resolve, 10));
const autoState = storageValues.get('bossRecommendAuto');
assert.equal(autoState.enabled, true);
assert.equal(elements.autoToggle.textContent, '停止自动入库');
assert.ok(elements.autoToggle.className.includes('is-on'));

// 已有运行统计时展示今日数据
storageValues.set('bossRecommendAuto', Object.assign({}, autoState, {
  importedToday: 3,
  processedToday: 7,
  failedToday: 1,
  message: '已入库：张三',
  updatedAt: Date.now(),
}));
await refreshIntervals[1]();
await new Promise(resolve => setTimeout(resolve, 10));
assert.equal(
  elements.autoStats.textContent,
  '今日入库 3 · 已处理 7 · 失败 1；已入库：张三'
);

console.log('popup runtime tests passed');
