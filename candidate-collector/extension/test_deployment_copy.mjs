import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const sourceRoot = dirname(fileURLToPath(import.meta.url));
const deployedRoot = resolve(sourceRoot, '..', 'ot小插件-4.8.0');
const bridgeFiles = [
  'background.js',
  'content/auto_import.js',
  'content/boss_recommend_autopilot.js',
  'content/runtime_recovery.js',
  'manifest.json',
  'ot-sidepanel.html',
  'parsers/boss.js',
  'popup.html',
  'popup.js',
  'sider_bridge.js'
];

for (const path of bridgeFiles) {
  assert.deepEqual(
    readFileSync(join(deployedRoot, path)),
    readFileSync(join(sourceRoot, path)),
    `deployed plugin is stale: ${path}`
  );
}

console.log('deployed plugin bridge files match source');
