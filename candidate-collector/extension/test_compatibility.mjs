import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {dirname, join} from 'node:path';
import {fileURLToPath} from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const read = path => readFileSync(join(root, path));
const manifest = JSON.parse(read('manifest.json').toString('utf8'));
const upstreamKey = 'MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAqVn6j3VLpiBKapg7/pZoCxf0Bz2N/94a9qsZUZKU5B51avu/T13xTl86+zk4bf+FhxNssX1ZzXOsSKBxi9SusZbTD/t3PJA6DPZ5+SUcVLwL8hYncU47+gIANas4Trlc5xXYOnVLlNqNrPvx1CzkIY8NeitFvWQd9RBzHtUgY9KsBRRnQFzQMSfO8YTcp5OAPpSYoTFyG+9mmxFrj1DiQc9las4obz4W9303f1yI/LWTychY/Pf+o0ASZJzuFWdFPJc8sfQ6plhoSHuEUTXSk86iuliYOEVgRCZQpleUGOMXtE8qz3Jl6q7kOJgW3jVHLAgfr5WbqDa6K7nMWo31/QIDAQAB';

const upstreamFiles = {
  'copilot-inpage.95769368.js': '1fe93071e8d926c47dfe54e1bfa009e66ab3444246351c7ca511646ee380d6c2',
  'copilot-inpage.d67e3dfd.css': 'f89a81b8d1f023c768c0fb786368aefa4be31c1844fc3853080c0d4c8e069443',
  'copilot-liepin.5fe2c85d.js': '31c25d049d3c1d4b52d970191901fd369b0df914f1d19a4506d7339358235db9',
  'copilot-linkedin.4878332f.js': '2d05f9cccc8c72b008a0e89c1f9109d686366f3e8b52f3fe0b73162179e55c62',
  'copilot.aae3e1ab.js': 'd22b082497603701e58a6d69581f186270b19d9d0b2f2d22c7782f63c9188bfd',
  'icon.c766bb78.png': '6ae73cf472caa7325ff64e6895a7a0234d7e9e10100be0d8e0eba2fc7551cfa6',
  'icon16.plasmo.6c567d50.png': '96f35b8f89092d74f6a4898a348c397a27306dca6e598e79aec7e8de358bef52',
  'icon32.plasmo.76b92899.png': '00ae4a56908f3ad24358b7e16dd01a90f295137205a055b528c447cda63e0964',
  'icon48.plasmo.aced7582.png': '7cd6cf27ec87bd111a26d19edfffb7a541f601bfe125f583f4be1c617d8046bf',
  'icon64.plasmo.8bb5e6e0.png': '261f6979571e905cb7d65119e17c8fa493afb0b4ba7df72cae4da6609510e8a4',
  'icon128.plasmo.3c1ed2d2.png': '54094857782f08df8fde7b8d88e9c760168e14635b26ab419962991957bd3c38',
  'options.95eda3f3.js': '2f55f86ce23ebd7db1ffb0af842bbcef85a5237a8d47c1fcf2de1c13c6343262',
  'options.html': '88b738223268b0e776d391c8e357ec01662fe5c27048dc8ec059cc55718600eb',
  'sidepanel.b7741352.js': 'c34053e0292665406eb2b2c21b351380307b585311ce3159c5fdc0478070f5e6',
  'sidepanel.html': 'c5e9656cd5f9ab29a9ea7aca08931fa21b482c3463e7ae3823ea4001a53455d0',
  'src/inject/copilot.bundle.js': '5a4bc88399b4f3935ea075d35d92bb413b980e120a56784e06809161374368c2',
  'src/inject/injector.js': 'a5fcb95831975a566e696cef3bf016c458a8ad95188fa60482bd5cb4bc10f116',
  'src/inject/injector_bridge.js': 'a1d608fe0268a3cf5e309dd6f6023ab5832dc8856c3ac9ef5b0165b8454facbf',
  'static/background/index.js': '860cc3384b7950a290d97d5fef8cdad9100d3a22b3198c0274501d2fe5c39fc1',
};

const allowedBrandingChanges = {
  'options.html': ['ot小插件', 'tt智能助手'],
  'sidepanel.html': ['ot小插件', 'tt智能助手'],
  'options.95eda3f3.js': ['ot小插件', 'TTC Copilot Plugin'],
  'sidepanel.b7741352.js': ['ot小插件', 'TTC Copilot Plugin'],
  'copilot-inpage.95769368.js': ['ot小插件', 'TTC Copilot Plugin'],
  'static/background/index.js': [
    'chrome.sidePanel.setPanelBehavior({openPanelOnActionClick:!1}),chrome.sidePanel.setOptions({tabId:t,path:"ot-sidepanel.html",enabled:!0})',
    'chrome.sidePanel.setPanelBehavior({openPanelOnActionClick:!0}),chrome.sidePanel.setOptions({tabId:t,path:"sidepanel.html",enabled:!0})',
  ],
};

for (const [path, expected] of Object.entries(upstreamFiles)) {
  let contents = read(path);
  if (allowedBrandingChanges[path]) {
    const [replacement, original] = allowedBrandingChanges[path];
    const text = contents.toString('utf8');
    assert.ok(text.includes(replacement), `visible brand was not replaced: ${path}`);
    assert.ok(!text.includes(original), `old visible brand remains: ${path}`);
    contents = Buffer.from(text.replaceAll(replacement, original));
  }
  const actual = createHash('sha256').update(contents).digest('hex');
  assert.equal(actual, expected, `upstream asset changed: ${path}`);
}

for (const permission of ['scripting', 'sidePanel', 'webRequest', 'activeTab', 'webNavigation', 'tabs', 'storage']) {
  assert.ok(manifest.permissions.includes(permission), `missing upstream permission: ${permission}`);
}

assert.equal(manifest.name, 'ot小插件');
assert.equal(manifest.version, '4.8.0');
assert.equal(manifest.action.default_popup, 'popup.html');
assert.equal(manifest.side_panel.default_path, 'ot-sidepanel.html');
assert.equal(manifest.options_ui.page, 'ot-options.html');
assert.equal(manifest.background.service_worker, 'background-entry.js');
assert.equal(manifest.key, upstreamKey, 'upstream extension identity changed');
assert.ok(manifest.host_permissions.includes('<all_urls>'));

const backgroundEntry = read('background-entry.js').toString('utf8');
assert.ok(backgroundEntry.includes("import './static/background/index.js'"), 'upstream worker is not loaded');
assert.ok(backgroundEntry.includes("import './background.js'"), 'candidate-collector worker is not loaded');

const background = read('background.js').toString('utf8');
assert.ok(background.includes("from './cloud_client.js'"), 'cloud-first client is not loaded');
assert.ok(background.includes("from './sider_bridge.js'"), 'BOSS/Sider bridge module is not loaded');
const cloudRuntimeExample = JSON.parse(read('cloud_runtime.example.json').toString('utf8'));
assert.equal(cloudRuntimeExample.baseUrl, 'https://yorkteam.cn/api/ot-plugin');

const scripts = manifest.content_scripts.flatMap(item => item.js || []);
for (const script of [
  'content/runtime_recovery.js',
  'copilot.aae3e1ab.js',
  'copilot-inpage.95769368.js',
  'content/auto_import.js',
  'content/ot_iframe_branding.js'
]) {
  assert.ok(scripts.includes(script), `missing content script: ${script}`);
}
const runtimeRecoveryEntry = manifest.content_scripts.find(item =>
  (item.js || []).includes('content/runtime_recovery.js')
);
assert.equal(runtimeRecoveryEntry.run_at, 'document_start');
assert.equal(runtimeRecoveryEntry.all_frames, false);
assert.ok(
  runtimeRecoveryEntry.matches.every(pattern => pattern.includes('zhipin.com')),
  'runtime recovery must stay scoped to BOSS'
);
const iframeBrandingEntry = manifest.content_scripts.find(item =>
  (item.js || []).includes('content/ot_iframe_branding.js')
);
assert.equal(iframeBrandingEntry.all_frames, true, 'remote plugin frame branding must run in subframes');

const autoImport = read('content/auto_import.js').toString('utf8');
assert.ok(autoImport.includes('autoImportTtcSearchList'), 'TTC search-list automatic import is missing');
assert.ok(autoImport.includes("'/app/talent/search/list'"), 'exact TTC search-list route is missing');
assert.ok(autoImport.includes('云端人才库'), 'cloud target name is missing from feedback');
assert.ok(autoImport.includes('cloud_candidates'), 'cloud table name is missing from feedback');
assert.ok(!autoImport.includes('jxog8b3tny.feishu.cn'), 'obsolete Feishu Base target remains');
assert.ok(autoImport.includes('bossProfileText'), 'BOSS drawer-scoped profile reader is missing');
assert.ok(autoImport.includes("platform() === 'boss' && !inFlight"), 'BOSS same-URL mutation trigger is missing');
assert.ok(autoImport.includes('__copilot.proxy.xhr'), 'BOSS dynamic response bridge is missing');
assert.ok(autoImport.includes('extractBossProfileFromApiResponse'), 'BOSS response validation is missing');
assert.ok(
  autoImport.includes('autoImportBossResponse(event.data).catch'),
  'BOSS response bridge can leak an unhandled rejection'
);
assert.ok(
  autoImport.includes('recoverRuntimeContext(error)'),
  'content script does not hand invalid runtime errors to recovery'
);
const runtimeRecovery = read('content/runtime_recovery.js').toString('utf8');
assert.ok(
  runtimeRecovery.includes('Extension context invalidated'),
  'extension reload recovery is missing'
);
assert.ok(
  runtimeRecovery.includes('Attempting to use a disconnected port object'),
  'disconnected port recovery is missing'
);
assert.ok(runtimeRecovery.includes('state.attempts >= 1'), 'reload-loop guard is missing');
assert.ok(runtimeRecovery.includes('HEALTHY_RESET_MS'), 'healthy-context latch reset is missing');
assert.ok(
  runtimeRecovery.includes('installConsoleRecovery'),
  'React-caught runtime errors are not handed to recovery'
);
assert.ok(
  runtimeRecovery.includes("type: 'otUserStatusFetch'"),
  'BOSS user-status request is not isolated from the shared fetchData channel'
);
assert.ok(
  runtimeRecovery.includes('stopImmediatePropagation'),
  'upstream fetchData listener can still race the dedicated user-status route'
);
assert.ok(background.includes('findTtcRecords'), 'TTC list record reader is missing');
assert.ok(background.includes('importCloudFromPayload'), 'TTC records are not routed to cloud import');
assert.ok(background.includes('storeBridgeSnapshotLocally'), 'local candidate cache is missing');
assert.ok(background.includes('ot_candidate_cache_index'), 'local candidate cache index is missing');
assert.ok(
  background.includes('OT_BACKGROUND_MESSAGE_TYPES.has(message.type)'),
  'OT background listener does not scope the messages it claims'
);
assert.ok(
  background.includes("'otUserStatusFetch'"),
  'dedicated BOSS user-status background route is missing'
);
assert.ok(
  background.includes('COPILOT_SERVICE_HOSTS.has(url.hostname)'),
  'user-status background route is not host allowlisted'
);
assert.ok(
  !background.includes("return {ok: false, error: '未知操作'}"),
  'OT background listener still races upstream listeners on unknown messages'
);
assert.ok(
  manifest.web_accessible_resources.some(item => (item.resources || []).includes('sider_bridge.js')),
  'bridge module is not exposed to the scoped content script'
);

const bossParser = read('parsers/boss.js').toString('utf8');
assert.ok(bossParser.includes('findBossProfileRoot'), 'BOSS profile drawer scoping is missing');
assert.ok(bossParser.includes('profile_detected'), 'BOSS parser does not report profile detection');
assert.ok(bossParser.includes('raw_text'), 'BOSS parser does not return scoped profile text');

const popup = read('popup.html').toString('utf8');
const popupScript = read('popup.js').toString('utf8');
assert.ok(popup.includes('width: 320px'), 'popup width is not the 320px white design');
assert.ok(popup.includes('--background: #ffffff'), 'popup white design token is missing');
assert.ok(popup.includes('--accent: #2563eb'), 'popup indigo accent is missing');
assert.ok(popupScript.includes("chrome.runtime.getManifest().version"), 'popup version is not read from manifest');
assert.ok(popupScript.includes('state.done'), 'popup does not render completed count');
assert.ok(popupScript.includes('state.total'), 'popup does not render total count');
assert.ok(popupScript.includes('state.running'), 'popup does not render running state');
assert.ok(popupScript.includes('state.current'), 'popup does not render the current candidate');
assert.ok(popup.includes('icon32.plasmo.76b92899.png'), 'popup does not show the ot icon');
assert.ok(!popupScript.includes('需要检查'), 'legacy ambiguous status title remains');
assert.ok(!background.includes('已更新云端人才库中的候选人'), 'legacy update prompt remains');
assert.ok(autoImport.includes("'background:#fff'"), 'toast white background is missing');
assert.ok(autoImport.includes("'border-left-width:4px'"), 'toast status stripe is missing');
assert.ok(autoImport.includes('查看记录 →'), 'toast record action is missing');

const options = read('ot-options.html').toString('utf8');
assert.ok(options.includes('<title>ot小插件</title>'), 'ot-options.html does not use the ot小插件 name');
assert.ok(options.includes('/ot-branding.js'), 'ot-options.html does not load visible-name compatibility layer');

const sidepanel = read('ot-sidepanel.html').toString('utf8');
assert.ok(sidepanel.includes('<title>ot小插件</title>'), 'ot-sidepanel.html does not use the ot小插件 name');
assert.ok(sidepanel.includes('src="popup.html"'), 'ot side panel does not use the local popup');
assert.ok(!sidepanel.includes('sidepanel.b7741352.js'), 'ot side panel still loads the remote welcome page');

const iframeBranding = read('content/ot_iframe_branding.js').toString('utf8');
assert.ok(iframeBranding.includes('welcome\\.png'), 'remote welcome logo removal is missing');
assert.ok(iframeBranding.includes('欢迎使用ot小插件'), 'remote welcome heading is not renamed');

const upstreamBackground = read('static/background/index.js').toString('utf8');
assert.ok(
  upstreamBackground.includes('openPanelOnActionClick:!1}),chrome.sidePanel.setOptions({tabId:t,path:"ot-sidepanel.html"'),
  'toolbar click still opens the legacy side panel'
);

console.log('extension compatibility tests passed');
