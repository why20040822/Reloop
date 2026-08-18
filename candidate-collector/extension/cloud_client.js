const LOCAL_CAPTURE_API = 'http://127.0.0.1:8765/api/capture';
const LOCAL_IMPORT_API = 'http://127.0.0.1:8765/api/import-browser-capture';

let runtimePromise = null;

function errorMessage(data, fallback) {
  if (typeof data === 'string' && data) return data;
  if (data && typeof data.detail === 'string') return data.detail;
  if (data && typeof data.error === 'string') return data.error;
  return fallback;
}

export async function loadCloudRuntime(options = {}) {
  const fetchImpl = options.fetchImpl || globalThis.fetch;
  const runtimeUrl = options.runtimeUrl ||
    globalThis.chrome && chrome.runtime && chrome.runtime.getURL('cloud_runtime.json');
  if (!runtimeUrl) return null;
  try {
    const response = await fetchImpl(runtimeUrl, {cache: 'no-store'});
    if (!response.ok) return null;
    const config = await response.json();
    const baseUrl = String(config.baseUrl || '').replace(/\/+$/, '');
    const apiToken = String(config.apiToken || '');
    if (!baseUrl.startsWith('https://') || apiToken.length < 32) return null;
    return {baseUrl, apiToken};
  } catch (_error) {
    return null;
  }
}

async function runtimeConfig() {
  if (!runtimePromise) runtimePromise = loadCloudRuntime();
  return runtimePromise;
}

async function parseResponse(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.ok === false) {
    const error = new Error(errorMessage(data, '导入失败'));
    error.status = response.status;
    throw error;
  }
  return data;
}

async function postLocal(localUrl, payload, fetchImpl) {
  const response = await fetchImpl(localUrl, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload)
  });
  const data = await parseResponse(response);
  return {...data, runtime: 'local'};
}

export async function postPluginPayload(kind, payload, options = {}) {
  const fetchImpl = options.fetchImpl || globalThis.fetch;
  const config = options.runtimeConfig === undefined
    ? await runtimeConfig()
    : options.runtimeConfig;
  const cloudPath = kind === 'capture' ? '/capture' : '/import-browser-capture';
  const localUrl = kind === 'capture' ? LOCAL_CAPTURE_API : LOCAL_IMPORT_API;

  let cloudError = null;
  if (config) {
    try {
      const response = await fetchImpl(config.baseUrl + cloudPath, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-OT-Token': config.apiToken
        },
        body: JSON.stringify(payload)
      });
      const data = await parseResponse(response);
      return {...data, runtime: 'cloud'};
    } catch (error) {
      // 云端不可达、鉴权失效或写库失败都回退本机服务——本机路径同样会
      // upsert cloud_candidates，采集量优先，错误在两路都失败时才抛出。
      cloudError = error;
    }
  }

  try {
    return await postLocal(localUrl, payload, fetchImpl);
  } catch (localError) {
    if (cloudError) {
      throw new Error(
        '云端导入失败（' + cloudError.message + '），本机服务也不可用（' + localError.message + '）'
      );
    }
    throw localError;
  }
}
