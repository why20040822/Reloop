import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import test from "node:test";

const dashboardModule = new URL("../frontend/src/lib/dashboard.ts", import.meta.url);

const talents = [
  { id: 1, name: "A", last_active_at: "2026-08-21T10:00:00.000Z", value_score: .71 },
  { id: 2, name: "B", last_active_at: "2026-08-25T10:00:00.000Z", value_score: .93 },
  { id: 3, name: "C", last_active_at: "not-a-date", value_score: .42 },
  { id: 4, name: "D", last_active_at: null, value_score: .36 },
];
const matches = [
  { rank: 2, talent_id: 1, name: "A", score: .76 },
  { rank: 1, talent_id: 3, name: "C", score: .88, contact_reason: "适合尽快联系" },
];

test("activity rows sort newest first and keep invalid or null dates last in source order", async () => {
  assert.equal(existsSync(dashboardModule), true, "dashboard row helpers should exist");
  const { buildActivityRows } = await import(dashboardModule.href);

  assert.deepEqual(buildActivityRows(talents).map((row) => row.talent.id), [2, 1, 3, 4]);
  assert.deepEqual(talents.map((talent) => talent.id), [1, 2, 3, 4]);
});

test("match rows preserve backend recommendation order", async () => {
  assert.equal(existsSync(dashboardModule), true, "dashboard row helpers should exist");
  const { buildMatchRows } = await import(dashboardModule.href);

  assert.deepEqual(buildMatchRows(matches, talents).map((row) => row.talent.id), [1, 3]);
});

test("row helpers retain the presentation data for activity and matching", async () => {
  assert.equal(existsSync(dashboardModule), true, "dashboard row helpers should exist");
  const { buildActivityRows, buildMatchRows } = await import(dashboardModule.href);

  const activity = buildActivityRows(talents)[0];
  const match = buildMatchRows(matches, talents)[1];

  assert.equal(activity.score, .93);
  assert.match(activity.signal, /活跃信号/);
  assert.equal(activity.activeAt, "2026-08-25T10:00:00.000Z");
  assert.equal(match.score, .88);
  assert.equal(match.reason, "适合尽快联系");
  assert.equal(match.talent.id, 3);
});
