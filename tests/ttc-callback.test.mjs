import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import * as callbackFlow from "../frontend/src/lib/ttcCallback.ts";

test("TTC callback scrub preserves the static entry pathname and removes only hash query data", () => {
  assert.equal(
    callbackFlow.scrubCallbackHash("/reloop/", "#/ttc/callback?status=success"),
    "/reloop/#/ttc/callback",
  );
  assert.equal(
    callbackFlow.scrubCallbackHash("/reloop/", "#/auth/callback?status=success&handle=opaque"),
    "/reloop/#/auth/callback",
  );
});

test("StrictMode duplicate callback effects share one in-flight operation", async () => {
  assert.equal(typeof callbackFlow.runCallbackOnce, "function");
  let calls = 0;
  const key = `opaque-handle-${Date.now()}`;
  const first = callbackFlow.runCallbackOnce(key, async () => { calls += 1; return "session"; });
  const second = callbackFlow.runCallbackOnce(key, async () => { calls += 1; return "duplicate"; });

  assert.equal(first, second);
  assert.equal(await first, "session");
  assert.equal(await second, "session");
  assert.equal(calls, 1);
});

test("settled callback operations can be retried in the same SPA session", async () => {
  let calls = 0;
  const key = `retryable-operation-${Date.now()}`;

  assert.equal(await callbackFlow.runCallbackOnce(key, async () => { calls += 1; return calls; }), 1);
  assert.equal(await callbackFlow.runCallbackOnce(key, async () => { calls += 1; return calls; }), 2);
  assert.equal(calls, 2);
});

test("SPA callbacks exchange only opaque handles and never bind TTC browser tokens", () => {
  const app = readFileSync(new URL("../frontend/src/App.tsx", import.meta.url), "utf8");
  const api = readFileSync(new URL("../frontend/src/lib/api.ts", import.meta.url), "utf8");

  assert.match(app, /get\("handle"\)/);
  assert.match(app, /runCallbackOnce\(/);
  assert.doesNotMatch(app, /get\("token"\)/);
  assert.doesNotMatch(app, /api\.bindTtc/);
  assert.match(api, /feishuLogin:\s*\(handle: string\)/);
  assert.doesNotMatch(api, /bindTtc|json:\s*\{\s*token\s*\}/);
});
