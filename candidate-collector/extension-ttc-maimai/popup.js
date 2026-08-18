const statusBox = document.getElementById('status');
const lastBox = document.getElementById('last');
const diagnoseButton = document.getElementById('diagnose');
const reloadButton = document.getElementById('reload');
const EXPECTED_BACKGROUND_VERSION = '0.7.3';
let statusOverrideUntil = 0;

function send(message) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(message, response => {
      if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
      resolve(response || {ok: false, error: '无响应'});
    });
  });
}

async function refresh() {
  if (Date.now() < statusOverrideUntil) return;
  try {
    const response = await send({type: 'getStatus'});
    const state = response.state || {};
    statusBox.textContent = state.message || '空闲';
    if (state.current) {
      const result = state.lastResult || {};
      const table = result.feishu_table_id === 'tblEHeMS9wk6g0ui' ? 'Otto2' : 'Otto1';
      const label = document.createElement('span');
      label.className = 'ok';
      label.textContent = '最近处理：';
      lastBox.replaceChildren(
        label,
        document.createTextNode(String(state.current)),
        document.createElement('br'),
        document.createTextNode(
          '结果：' + String(result.action || state.message || '完成') + ' · ' + table
        )
      );
    }
  } catch (error) {
    statusBox.textContent = '状态读取失败：' + error.message;
  }
}

diagnoseButton.addEventListener('click', async () => {
  diagnoseButton.disabled = true;
  statusOverrideUntil = Date.now() + 10000;
  statusBox.textContent = '正在检查本地服务…';
  try {
    const response = await send({type: 'checkBackend'});
    if (!response.ok) {
      if (String(response.error || '').includes('未知操作')) {
        throw new Error('扩展后台版本过旧，请点击“重载扩展后台”');
      }
      throw new Error(response.error || '检查失败');
    }
    statusBox.textContent = '本地服务正常 · 127.0.0.1:8765';
  } catch (error) {
    statusBox.textContent = '本地服务不可用：' + error.message;
  } finally {
    diagnoseButton.disabled = false;
  }
});

reloadButton.addEventListener('click', () => {
  statusBox.textContent = '正在重载扩展后台…';
  setTimeout(() => chrome.runtime.reload(), 100);
});

send({type: 'ping'})
  .then(response => {
    if (!response.ok || response.version !== EXPECTED_BACKGROUND_VERSION) {
      statusBox.textContent = '扩展后台版本过旧，请点击“重载扩展后台”';
      return;
    }
    return refresh();
  })
  .catch(error => {
    statusBox.textContent = '后台未启动：' + error.message;
  });

setInterval(refresh, 1500);
