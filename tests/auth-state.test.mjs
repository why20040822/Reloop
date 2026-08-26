import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";


test("auth changes refresh Settings without keying and remounting the app shell", () => {
  const appSource = readFileSync(new URL("../frontend/src/App.tsx", import.meta.url), "utf8");

  assert.doesNotMatch(appSource, /key=\{authTick\}/);
  assert.match(appSource, /addEventListener\(AUTH_CHANGE_EVENT, onAuthChange\)/);
  assert.match(appSource, /<SettingsPage[^>]*authRevision=\{authTick\}/);
  assert.match(appSource, /useEffect\(\(\) => \{ void refreshUser\(\); \}, \[authRevision\]\)/);
});


test("parse and save 401 responses clear auth without mutating drawer draft state", async () => {
  const values = new Map();
  const browserWindow = Object.assign(new EventTarget(), { setTimeout, clearTimeout });
  Object.defineProperties(globalThis, {
    localStorage: {
      configurable: true,
      value: {
        getItem: (key) => values.get(key) ?? null,
        setItem: (key, value) => values.set(key, value),
        removeItem: (key) => values.delete(key),
      },
    },
    location: {
      configurable: true,
      value: { protocol: "http:", hostname: "localhost", port: "5173", origin: "http://localhost:5173" },
    },
    window: { configurable: true, value: browserWindow },
  });

  const { api, AUTH_CHANGE_EVENT, config } = await import("../frontend/src/lib/api.ts");
  const drawer = {
    open: true,
    rawJd: "负责平台产品规划",
    review: { title: "平台产品负责人", required_skills: ["产品规划"] },
  };
  const expectedDrawer = structuredClone(drawer);
  let authChanges = 0;
  browserWindow.addEventListener(AUTH_CHANGE_EVENT, () => { authChanges += 1; });
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: "session expired" }), {
    status: 401,
    headers: { "Content-Type": "application/json" },
  });

  config.setAuth({ token: "expired-token", user: { user_id: "fs_test", display_name: "Test" } });
  authChanges = 0;
  await assert.rejects(api.parseJd(drawer.rawJd), /session expired/);
  assert.equal(config.auth(), null);
  assert.equal(authChanges, 1);
  assert.deepEqual(drawer, expectedDrawer);

  config.setAuth({ token: "expired-token", user: { user_id: "fs_test", display_name: "Test" } });
  authChanges = 0;
  await assert.rejects(api.setPosition({
    position_name: drawer.review.title,
    jd_text: drawer.rawJd,
    jd_analysis: drawer.review,
  }), /session expired/);
  assert.equal(config.auth(), null);
  assert.equal(authChanges, 1);
  assert.deepEqual(drawer, expectedDrawer);
});
