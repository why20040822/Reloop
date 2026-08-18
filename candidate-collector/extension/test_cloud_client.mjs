import assert from 'node:assert/strict';

import {loadCloudRuntime, postPluginPayload} from './cloud_client.js';

function response(status, data) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => data
  };
}

const loaded = await loadCloudRuntime({
  runtimeUrl: 'chrome-extension://id/cloud_runtime.json',
  fetchImpl: async () => response(200, {
    baseUrl: 'https://yorkteam.cn/api/ot-plugin/',
    apiToken: 'x'.repeat(32)
  })
});
assert.equal(loaded.baseUrl, 'https://yorkteam.cn/api/ot-plugin');

const calls = [];
const cloudResult = await postPluginPayload('import', {text: 'x'.repeat(20)}, {
  runtimeConfig: loaded,
  fetchImpl: async (url, options) => {
    calls.push({url, options});
    return response(200, {ok: true, action: 'created'});
  }
});
assert.equal(cloudResult.runtime, 'cloud');
assert.equal(calls[0].url, 'https://yorkteam.cn/api/ot-plugin/import-browser-capture');
assert.equal(calls[0].options.headers['X-OT-Token'], 'x'.repeat(32));

await assert.rejects(
  postPluginPayload('import', {text: 'x'.repeat(20)}, {
    runtimeConfig: loaded,
    fetchImpl: async () => response(401, {detail: '插件授权无效'})
  }),
  /插件授权无效/
);

// 云端 HTTP 401（鉴权失效）也必须回退本机：采集量优先。
const authFallback = await postPluginPayload('import', {text: 'x'.repeat(20)}, {
  runtimeConfig: loaded,
  fetchImpl: async url => {
    if (url.startsWith('https://yorkteam.cn')) return response(401, {detail: {code: 'login_required'}});
    assert.equal(url, 'http://127.0.0.1:8765/api/import-browser-capture');
    return response(200, {ok: true, action: 'created'});
  }
});
assert.equal(authFallback.runtime, 'local');

// 云端和本机都失败时，错误信息要同时包含两路原因。
await assert.rejects(
  postPluginPayload('import', {text: 'x'.repeat(20)}, {
    runtimeConfig: loaded,
    fetchImpl: async url => {
      if (url.startsWith('https://yorkteam.cn')) return response(502, {detail: '云数据库写入失败'});
      return response(500, {detail: '本地解析失败'});
    }
  }),
  /云端导入失败.*本机服务也不可用/
);

let attempt = 0;
const fallback = await postPluginPayload('capture', {text: 'x'.repeat(20)}, {
  runtimeConfig: loaded,
  fetchImpl: async url => {
    attempt += 1;
    if (attempt === 1) throw new TypeError('network unavailable');
    assert.equal(url, 'http://127.0.0.1:8765/api/capture');
    return response(200, {ok: true, candidate: {name: '测试'}});
  }
});
assert.equal(fallback.runtime, 'local');

console.log('cloud client tests passed');
