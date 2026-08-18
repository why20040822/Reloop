const statusDot = document.getElementById('statusDot');
const statusTitle = document.getElementById('statusTitle');
const statusMessage = document.getElementById('statusMessage');
const progress = document.getElementById('progress');
const progressTrack = progress.querySelector('[role="progressbar"]');
const progressText = document.getElementById('progressText');
const progressBar = document.getElementById('progressBar');
const recentCard = document.getElementById('recentCard');
const candidateName = document.getElementById('candidateName');
const platformTag = document.getElementById('platformTag');
const relativeTime = document.getElementById('relativeTime');
const autoToggle = document.getElementById('autoToggle');
const autoStats = document.getElementById('autoStats');
const AUTO_STATE_KEY = 'bossRecommendAuto';

document.getElementById('version').textContent =
  'v' + chrome.runtime.getManifest().version;

function send(message) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(message, response => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      resolve(response || {ok: false, error: '无响应'});
    });
  });
}

function formatRelativeTime(value) {
  const timestamp = Number(value) || Date.now();
  const seconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
  if (seconds < 60) return '刚刚';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return minutes + '分钟前';
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return hours + '小时前';
  return Math.floor(hours / 24) + '天前';
}

function platformLabel(value) {
  const labels = {
    ot: 'ot',
    ttc: 'ot',
    boss: 'BOSS直聘',
    maimai: '脉脉',
    liepin: '猎聘',
    linkedin: '领英',
    dhunting: '递航'
  };
  const key = String(value || '').toLowerCase();
  return labels[key] || value || '候选人';
}

function statusKind(state) {
  if (state.running) return 'running';
  const message = String(state.message || '');
  if (/导入失败|状态读取失败|后台未启动|已暂停|异常/.test(message)) return 'error';
  if (Number(state.errors) > 0 && /失败\s*[1-9]\d*|失败[:：]/.test(message)) return 'error';
  return 'normal';
}

function displayMessage(state) {
  const message = String(state.message || '').trim();
  if (/^已(?:更新|写入)云端人才库/.test(message)) return '自动入库已启用';
  if (!message || message === '空闲') return '等待打开 BOSS 候选人详情';
  return message || '等待候选人页面';
}

function render(state) {
  const kind = statusKind(state);
  statusDot.className = 'status-dot' +
    (kind === 'running' ? ' is-running' : kind === 'error' ? ' is-error' : '');
  statusTitle.textContent = kind === 'running' ? '正在导入' :
    kind === 'error' ? '导入异常' : '状态正常';
  statusMessage.textContent = displayMessage(state);

  const done = Math.max(0, Number(state.done) || 0);
  const total = Math.max(0, Number(state.total) || 0);
  const percent = total ? Math.min(100, Math.round(done / total * 100)) : 0;
  progress.hidden = !(state.running && total > 0);
  progressText.textContent = done + ' / ' + total;
  progressBar.style.width = percent + '%';
  progressTrack.setAttribute('aria-valuenow', String(percent));

  const current = String(state.current || '').trim();
  recentCard.hidden = !current;
  if (current) {
    candidateName.textContent = current;
    platformTag.textContent = platformLabel(state.platform);
    relativeTime.textContent = formatRelativeTime(state.updatedAt);
  }
}

function renderError(message) {
  render({running: false, errors: 1, message});
}

function renderAuto(state) {
  const enabled = Boolean(state && state.enabled);
  autoToggle.textContent = enabled ? '停止自动入库' : '开启自动入库';
  autoToggle.classList.toggle('is-on', enabled);
  if (!state || !state.updatedAt) {
    autoStats.textContent = '在 /web/chat/recommend 页面自动逐个读取推荐候选人。';
    return;
  }
  const parts = [
    '今日入库 ' + (state.importedToday || 0),
    '已处理 ' + (state.processedToday || 0),
    '失败 ' + (state.failedToday || 0)
  ];
  const message = String(state.message || '').trim();
  autoStats.textContent = parts.join(' · ') + (message ? '；' + message : '');
}

async function refreshAuto() {
  try {
    const data = await chrome.storage.local.get(AUTO_STATE_KEY);
    renderAuto(data[AUTO_STATE_KEY]);
  } catch (_error) {
    // 存储不可读时保留默认文案，不影响主状态卡片。
  }
}

autoToggle.addEventListener('click', async () => {
  autoToggle.disabled = true;
  try {
    const data = await chrome.storage.local.get(AUTO_STATE_KEY);
    const current = data[AUTO_STATE_KEY] || {};
    await chrome.storage.local.set({
      [AUTO_STATE_KEY]: Object.assign({}, current, {
        enabled: !current.enabled,
        message: current.enabled ? '已手动停止' : '等待推荐页开始运行',
        updatedAt: Date.now()
      })
    });
  } finally {
    autoToggle.disabled = false;
    refreshAuto();
  }
});

async function refresh() {
  try {
    const response = await send({type: 'getStatus'});
    render(response.state || {});
  } catch (error) {
    renderError('状态读取失败：' + error.message);
  }
}

send({type: 'ping'})
  .then(refresh)
  .catch(error => renderError('后台未启动：' + error.message));

refreshAuto();
setInterval(refresh, 1500);
setInterval(refreshAuto, 3000);
