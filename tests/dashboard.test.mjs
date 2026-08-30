import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import test from "node:test";

const dashboardModule = new URL("../frontend/src/lib/dashboard.ts", import.meta.url);

const DAY = 86400_000;
const now = Date.now();
const iso = (ms) => new Date(now - ms).toISOString();

const talents = [
  { id: 1, name: "A", last_active_at: iso(6 * DAY), value_score: .71 },   // 6 天前(7日窗口内)
  { id: 2, name: "B", last_active_at: iso(2 * DAY), value_score: .93 },   // 2 天前(窗口内, 最新)
  { id: 3, name: "C", last_active_at: "not-a-date", value_score: .42 },   // 非法时间 -> 排除
  { id: 4, name: "D", last_active_at: null, value_score: .36 },           // 无时间 -> 排除
  { id: 5, name: "E", last_active_at: iso(20 * DAY), value_score: .55 },  // 20 天前(窗口外)
];
const matches = [
  { rank: 2, talent_id: 1, name: "A", score: .76 },
  { rank: 1, talent_id: 3, name: "C", score: .88, contact_reason: "适合尽快联系" },
];

test("activity rows: 7 天阀门只保留窗口内人才, 最新在前", async () => {
  assert.equal(existsSync(dashboardModule), true, "dashboard row helpers should exist");
  const { buildActivityRows } = await import(dashboardModule.href);

  // 默认 7 天窗口: E(20天)/C(非法)/D(无) 全部排除, B(2天) 在 A(6天) 前
  assert.deepEqual(buildActivityRows(talents).map((row) => row.talent.id), [2, 1]);
  // 30 天窗口: E 进入, 非法/无时间仍排除
  assert.deepEqual(buildActivityRows(talents, 30).map((row) => row.talent.id), [2, 1, 5]);
  assert.deepEqual(talents.map((talent) => talent.id), [1, 2, 3, 4, 5]);
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
  assert.equal(activity.activeAt, talents[1].last_active_at);
  assert.equal(match.score, .88);
  assert.equal(match.reason, "适合尽快联系");
  assert.equal(match.talent.id, 3);
});
