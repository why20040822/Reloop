import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

import { readSidebarCollapsed, writeSidebarCollapsed } from "../frontend/src/lib/sidebar.ts";

test("missing sidebar preference defaults to expanded", () => {
  const storage = { getItem: () => null };
  assert.equal(readSidebarCollapsed(storage), false);
});

test("only the exact true value restores a collapsed sidebar", () => {
  assert.equal(readSidebarCollapsed({ getItem: () => "true" }), true);
  assert.equal(readSidebarCollapsed({ getItem: () => "false" }), false);
  assert.equal(readSidebarCollapsed({ getItem: () => "invalid" }), false);
});

test("unavailable storage defaults to expanded", () => {
  const storage = { getItem: () => { throw new Error("blocked"); } };
  assert.equal(readSidebarCollapsed(storage), false);
});

test("sidebar preference writes the exact boolean string", () => {
  const writes = [];
  const storage = { setItem: (key, value) => writes.push([key, value]) };

  writeSidebarCollapsed(true, storage);
  writeSidebarCollapsed(false, storage);

  assert.deepEqual(writes, [
    ["reloop.sidebarCollapsed", "true"],
    ["reloop.sidebarCollapsed", "false"],
  ]);
});

test("unavailable storage does not break the sidebar control", () => {
  const storage = { setItem: () => { throw new Error("blocked"); } };
  assert.doesNotThrow(() => writeSidebarCollapsed(true, storage));
});

// R2(2026-08-28) App.tsx 拆分后, 壳/页面逻辑分布在多个文件; 断言目标不变, 输入改为组合源。
const APP_SOURCES = [
  "App.tsx",
  "components/Workbench.tsx",
  "pages/AuthFlows.tsx",
  "pages/Dashboard.tsx",
  "pages/TalentList.tsx",
  "pages/TalentDetail.tsx",
  "pages/Positions.tsx",
  "pages/Settings.tsx",
];
const appSource = APP_SOURCES.map(
  (p) => readFileSync(new URL(`../frontend/src/${p}`, import.meta.url), "utf8"),
).join("\n");
const stylesSource = readFileSync(new URL("../frontend/src/styles.css", import.meta.url), "utf8");

test("sidebar brand mark is the accessible desktop collapse control", () => {
  assert.doesNotMatch(appSource, /PanelLeftClose/);
  assert.doesNotMatch(appSource, /PanelLeftOpen/);
  assert.match(appSource, /收起侧边栏/);
  assert.match(appSource, /展开侧边栏/);
  assert.match(appSource, /className="sidebar-collapse-button brand-mark"/);
  assert.doesNotMatch(appSource, />\s*R\s*<\/button>/);
  assert.ok((appSource.match(/src="\/reloop-logo\.png"/g) || []).length >= 3);
  assert.match(appSource, /className="brand-logo"/);
  assert.match(appSource, /className="brand-wordmark"/);
  assert.match(appSource, /<Link className="brand mobile-brand" to="\/">/);
  assert.equal(existsSync(new URL("../frontend/public/reloop-logo.png", import.meta.url)), true);
});

test("workbench exposes its collapsed state to layout styles", () => {
  assert.match(appSource, /sidebar-collapsed/);
  assert.match(appSource, /readSidebarCollapsed/);
  assert.match(appSource, /writeSidebarCollapsed/);
});

test("dashboard heading omits the removed recommendation description", () => {
  assert.doesNotMatch(appSource, /基于人才活跃度与岗位匹配度，优先推进下一次触达。/);
});

test("ranked talent rows expose the required information without page subtitles", () => {
  assert.match(appSource, /className="focus-current"/);
  assert.match(appSource, /className="focus-experience"/);
  assert.match(appSource, /className="focus-education"/);
  assert.match(appSource, /className="focus-signal"/);
  assert.match(appSource, /className="focus-score"/);
  assert.match(appSource, /className="focus-activity"/);
  assert.doesNotMatch(appSource, /搜索并处理人才库中的候选人。/);
  assert.doesNotMatch(appSource, /你已标记的重点人选。/);
  assert.doesNotMatch(appSource, /岗位与 JD 会直接影响人才匹配与排序。/);
});

test("ranked talent rows stay readable without mobile horizontal overflow", () => {
  assert.match(stylesSource, /\.focus-list\s*\{[^}]*overflow:\s*hidden;/);
  assert.match(stylesSource, /@media \(max-width:\s*760px\)[\s\S]*\.focus-row\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)\s+56px\s+17px;/);
  assert.match(stylesSource, /@media \(max-width:\s*760px\)[\s\S]*\.rank,\s*\.focus-experience,\s*\.focus-education,\s*\.focus-activity\s*\{\s*display:\s*none;/);
});

test("empty position picker remains legible", () => {
  assert.match(appSource, /positions\.length === 0 && <option value="">暂无岗位<\/option>/);
  assert.match(appSource, /disabled=\{positions\.length === 0\}/);
  assert.match(stylesSource, /\.position-picker select\s*\{[^}]*min-width:\s*150px;/);
});

test("position picker uses a vertically centered custom arrow", () => {
  assert.match(appSource, /className="position-select"[\s\S]*<ChevronDown size=\{15\}/);
  assert.match(stylesSource, /\.position-picker select\s*\{[^}]*appearance:\s*none;/);
  assert.match(stylesSource, /\.position-select svg\s*\{[^}]*top:\s*50%;[^}]*transform:\s*translateY\(-50%\);/);
});

test("sidebar styles define a desktop icon rail and preserve the mobile drawer", () => {
  assert.match(stylesSource, /--sidebar-collapsed-width:\s*72px/);
  assert.match(stylesSource, /\.sidebar-collapsed/);
  assert.match(stylesSource, /\.sidebar-collapse-button/);
  assert.match(stylesSource, /\.brand-wordmark/);
  assert.match(stylesSource, /\.brand-logo/);
  assert.match(stylesSource, /\.mobile-brand/);
  assert.match(stylesSource, /@media \(max-width:\s*760px\)[\s\S]*\.sidebar-collapse-button\s*\{\s*display:\s*none;/);
  assert.match(stylesSource, /@media \(max-width:\s*760px\)[\s\S]*\.sidebar-collapsed \.main-stage\s*\{\s*margin-left:\s*0;/);
});

test("desktop sidebar animation keeps icon anchors fixed while clipping content", () => {
  const desktopStyles = stylesSource.split("@media")[0];

  assert.match(desktopStyles, /\.sidebar\s*\{[^}]*overflow:\s*hidden;/);
  assert.doesNotMatch(desktopStyles, /\.sidebar-collapsed \.sidebar-head\s*\{/);
  assert.doesNotMatch(desktopStyles, /\.sidebar-collapsed \.main-nav\s*\{/);
  assert.doesNotMatch(desktopStyles, /[^{}]*\.sidebar-collapsed \.nav-item[^{}]*\{[^}]*justify-content:/);
  assert.doesNotMatch(desktopStyles, /\.sidebar-collapsed \.sidebar-footer\s*\{/);
});
