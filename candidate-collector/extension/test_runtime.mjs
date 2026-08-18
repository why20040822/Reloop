import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const context = vm.createContext({
  URL,
  window: {},
  location: {href: 'https://app.ttcadvisory.com/app/talent/PL12345'},
});

for (const file of ['parsers/common.js', 'parsers/ttc.js']) {
  const source = fs.readFileSync(new URL(file, import.meta.url), 'utf8');
  assert.equal(/(^|\s)(import|export)\s/m.test(source), false, `${file} must be a classic script`);
  vm.runInContext(source, context, {filename: file});
  vm.runInContext(source, context, {filename: file});
}

const ttc = context.window.__TTC_PARSERS.ttc;
assert.equal(ttc.extractTtcPersonLeadsId('https://app.ttcadvisory.com/app/talent/PL12345'), 'PL12345');
assert.equal(ttc.extractTtcPersonLeadsId('https://app.ttcadvisory.com/app/talent/12345'), '12345');
assert.equal(ttc.extractTtcPersonLeadsId('https://example.com/app/talent/PL12345'), null);

const interceptor = fs.readFileSync(new URL('content/network_interceptor.js', import.meta.url), 'utf8');
const autoImport = fs.readFileSync(new URL('content/auto_import.js', import.meta.url), 'utf8');
const retryPolicy = fs.readFileSync(new URL('content/retry_policy.js', import.meta.url), 'utf8');
const background = fs.readFileSync(new URL('background.js', import.meta.url), 'utf8');
const popup = fs.readFileSync(new URL('popup.js', import.meta.url), 'utf8');
const popupHtml = fs.readFileSync(new URL('popup.html', import.meta.url), 'utf8');
const manifest = JSON.parse(fs.readFileSync(new URL('manifest.json', import.meta.url), 'utf8'));
for (const endpoint of [
  '/api/talent_store/v1/person_leads/basic_info',
  '/api/talent_store/v1/person_leads/resume/attachment/list',
  '/api/ent/talent/basic',
  '/api/ent/card/console/intelligence/screen',
]) {
  assert.ok(interceptor.includes(endpoint), `interceptor missing ${endpoint}`);
}

assert.ok(interceptor.includes('TTC_CAPTURE_PORT_INIT_V2'), 'MAIN bridge must use a dedicated MessagePort');
assert.ok(autoImport.includes("chrome.runtime.connect({name: 'ttc-pdf-upload-v2'})"));
assert.equal(autoImport.includes("fetch('http://127.0.0.1:8765"), false);
assert.equal(background.includes('candidate.name'), false, 'background must not persist candidate PII');
assert.ok(popupHtml.includes('id="reload"'), 'popup must expose a self-reload control for stale service workers');
assert.ok(popup.includes('chrome.runtime.reload()'), 'popup reload control must use chrome.runtime.reload');
assert.ok(popup.includes('statusOverrideUntil'), 'health result must not be immediately overwritten by polling');
assert.ok(background.includes(`const EXTENSION_VERSION = '${manifest.version}'`));
assert.ok(popup.includes(`const EXPECTED_BACKGROUND_VERSION = '${manifest.version}'`));
assert.deepEqual(manifest.permissions, ['storage']);
assert.deepEqual(manifest.host_permissions.sort(), [
  'http://127.0.0.1:8765/*',
  'http://localhost:8765/*'
]);
for (const contentScript of manifest.content_scripts) {
  assert.ok(
    contentScript.exclude_matches?.includes('https://*.maimai.cn/platform/login*'),
    `${contentScript.js.join(', ')} must not run on the Maimai login page`
  );
}
const autoImportEntry = manifest.content_scripts.find(entry => entry.js.includes('content/auto_import.js'));
assert.deepEqual(autoImportEntry.js, ['content/retry_policy.js', 'content/auto_import.js']);
const retryContext = vm.createContext({});
vm.runInContext(retryPolicy, retryContext, {filename: 'content/retry_policy.js'});
assert.equal(retryContext.__TTC_RETRY_POLICY.delayMs(1), 5000);
assert.equal(retryContext.__TTC_RETRY_POLICY.delayMs(2), 10000);
assert.equal(retryContext.__TTC_RETRY_POLICY.delayMs(20), 60000);
assert.equal(retryContext.__TTC_RETRY_POLICY.shouldKeepRetrying(new Error('Failed to fetch'), 99), true);
assert.equal(retryContext.__TTC_RETRY_POLICY.shouldKeepRetrying(new Error('bad capture'), 4), false);

const backgroundContext = vm.createContext({
  URL,
  Blob: class Blob {},
  FormData: class FormData {},
  fetch: async () => ({ok: true, json: async () => ({ok: true})}),
  atob: value => Buffer.from(value, 'base64').toString('binary'),
  Uint8Array,
  chrome: {
    storage: {local: {get: async () => ({}), set: async () => {}, remove: async () => {}}},
    runtime: {
      onConnect: {addListener() {}},
      onMessage: {addListener() {}},
      onInstalled: {addListener() {}},
    },
  },
});
vm.runInContext(background, backgroundContext, {filename: 'background.js'});
const maimaiPayload = {
  platform: 'maimai',
  source_candidate_id: '123456',
  text: 'authorized maimai candidate profile',
  capture_request_url: 'https://api.maimai.cn/api/ent/talent/basic',
};
const maimaiSender = {url: 'https://maimai.cn/ent/talent/detail'};
assert.doesNotThrow(() => backgroundContext.validateCapturePayload(maimaiPayload, maimaiSender));
assert.throws(() => backgroundContext.validateCapturePayload(
  {...maimaiPayload, capture_request_url: 'https://evil.example/api/ent/talent/basic'},
  maimaiSender
));

console.log('runtime tests passed');
