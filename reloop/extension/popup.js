const statusBox = document.getElementById('status');
const debugBox = document.getElementById('debug');
const batchButton = document.getElementById('batch');
const resumeButton = document.getElementById('resume');

function send(message) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(message, response => {
      if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError));
      if (!response || !response.ok) return reject(new Error((response && response.error) || '操作失败'));
      resolve(response);
    });
  });
}

function showState(state) {
  if (!state || (!state.running && !state.total)) {
    statusBox.textContent = (state && state.message) || '空闲';
    batchButton.disabled = false;
    return;
  }
  const prefix = state.running ? '自动阅读中' : '本批已结束';
  statusBox.textContent = prefix + '：' + (state.done || 0) + '/' + (state.total || 0) +
    (state.current ? ' · ' + state.current : '') +
    (state.message ? ' · ' + state.message : '');
  batchButton.disabled = Boolean(state.running);
  resumeButton.disabled = Boolean(state.running) || !(state.queue && state.queue.length);
}

document.getElementById('capture').addEventListener('click', async () => {
  statusBox.textContent = '正在读取当前页面...';
  debugBox.textContent = '';
  try {
    const response = await send({type: 'captureCurrent'});
    statusBox.textContent = '已收藏：' + response.candidate.name + '（' + response.candidate.score + '分）';
  } catch (error) {
    statusBox.textContent = '失败：' + error.message;
  }
});

document.getElementById('validate').addEventListener('click', async () => {
  statusBox.textContent = '正在验证当前页面...';
  debugBox.textContent = '';
  try {
    const response = await send({type: 'validatePage'});
    const checks = response.checks || {};
    const parts = [
      checks.ok ? '✅ 验证通过' : '⚠️ 验证未通过',
      `平台：${checks.platform || '未知'}`,
      `文本：${checks.hasText ? '足够' : '不足'}`,
      `结构化：${checks.hasStructuredData ? '已提取' : '未提取'}`,
    ];
    if (checks.hasWorkExperience !== undefined) parts.push(`工作经历：${checks.hasWorkExperience ? '有' : '无'}`);
    if (checks.hasEducationExperience !== undefined) parts.push(`教育经历：${checks.hasEducationExperience ? '有' : '无'}`);
    if (checks.hasCandidateLinks !== undefined) parts.push(`候选人链接：${checks.hasCandidateLinks ? '有' : '无'}`);
    statusBox.textContent = parts.join(' · ');
    debugBox.textContent = JSON.stringify(checks, null, 2);
  } catch (error) {
    statusBox.textContent = '验证失败：' + error.message;
  }
});

document.getElementById('testLinks').addEventListener('click', async () => {
  statusBox.textContent = '正在识别当前列表的候选人链接...';
  debugBox.textContent = '';
  try {
    const limit = Math.max(1, Math.min(10, Number(document.getElementById('limit').value) || 5));
    const response = await send({type: 'testLinks', limit});
    statusBox.textContent = '识别到 ' + response.links.length + ' 个候选人链接';
    debugBox.textContent = response.links.map((l, i) => (i + 1) + '. ' + l.label + '\n' + l.url).join('\n\n');
  } catch (error) {
    statusBox.textContent = '识别失败：' + error.message;
  }
});

document.getElementById('batch').addEventListener('click', async () => {
  statusBox.textContent = '正在识别当前列表的候选人链接...';
  debugBox.textContent = '';
  try {
    const limit = Math.max(1, Math.min(10, Number(document.getElementById('limit').value) || 5));
    const delaySeconds = Math.max(8, Math.min(30, Number(document.getElementById('delay').value) || 12));
    const response = await send({type: 'startBatch', limit, delaySeconds});
    showState(response.state);
  } catch (error) {
    statusBox.textContent = '无法启动：' + error.message;
  }
});

document.getElementById('resume').addEventListener('click', async () => {
  statusBox.textContent = '正在继续当前批次...';
  debugBox.textContent = '';
  try {
    const response = await send({type: 'resumeBatch'});
    showState(response.state);
  } catch (error) {
    statusBox.textContent = '无法继续：' + error.message;
  }
});

document.getElementById('gmail').addEventListener('click', async () => {
  statusBox.textContent = '正在识别 Gmail 当前列表中的简历邮件...';
  debugBox.textContent = '';
  try {
    const limit = Math.max(1, Math.min(10, Number(document.getElementById('limit').value) || 5));
    const response = await send({type: 'startGmailBatch', limit});
    statusBox.textContent = response.message;
  } catch (error) {
    statusBox.textContent = 'Gmail 自动阅读失败：' + error.message;
  }
});

document.getElementById('stop').addEventListener('click', async () => {
  try {
    const response = await send({type: 'stopBatch'});
    showState(response.state);
  } catch (error) {
    statusBox.textContent = '停止失败：' + error.message;
  }
});

async function refresh() {
  try {
    const response = await send({type: 'getStatus'});
    showState(response.state);
  } catch (error) {
    statusBox.textContent = '状态读取失败：' + error.message;
  }
}

send({type: 'ping'})
  .then(response => {
    debugBox.textContent = '后台已连接 v' + response.version;
    return refresh();
  })
  .catch(error => {
    statusBox.textContent = '后台未启动：请在 chrome://extensions 刷新 TTC 扩展。' + error.message;
  });
setInterval(refresh, 1200);
