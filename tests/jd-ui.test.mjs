import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

import { analysisToDraft, draftToAnalysis, positionHasParsedJd } from "../frontend/src/lib/jd.ts";
import { cycleFocus, restoreFocus } from "../frontend/src/lib/drawerFocus.ts";
import { saveThenRefreshPosition } from "../frontend/src/lib/positionSave.ts";

const analysis = {
  title: "数据产品经理",
  summary: "负责数据产品的规划与交付。",
  responsibilities: ["规划数据产品"],
  required_skills: ["Python"],
  preferred_skills: ["统计学"],
  experience: "5 年以上",
  education: "本科及以上",
  location: "上海",
  industry_keywords: ["SaaS"],
  salary_range: "30-50K",
  team_size: "6 人",
  reporting_line: "产品负责人",
  language_requirements: ["中文"],
};

test("JD list fields round-trip one item per line", () => {
  const draft = analysisToDraft({ ...analysis, required_skills: ["Python", "SQL"] });
  assert.equal(draft.required_skills, "Python\nSQL");
  assert.deepEqual(draftToAnalysis(draft).required_skills, ["Python", "SQL"]);
});

test("JD list fields remove blank and duplicate entries without changing first-occurrence order", () => {
  const draft = analysisToDraft(analysis);
  draft.required_skills = "Python\n \nSQL\nPython\n SQL ";
  assert.deepEqual(draftToAnalysis(draft).required_skills, ["Python", "SQL"]);
});

test("JD review draft defaults an absent optional company to an empty controlled value", () => {
  const draft = analysisToDraft({
    title: "产品负责人", summary: "摘要", responsibilities: ["职责"], required_skills: ["技能"],
    preferred_skills: ["加分"], experience: "3 年", education: "本科", location: "上海",
    industry_keywords: ["AI"], salary_range: "面议", team_size: "5 人", reporting_line: "负责人",
    language_requirements: ["中文"],
  });

  assert.equal(draft.company_name, "");
});

test("only structured positions can enter matching directly", () => {
  assert.equal(positionHasParsedJd({ jd_analysis: null }), false);
  assert.equal(positionHasParsedJd({ jd_analysis: analysis }), true);
});

test("JD drawer declares its accessible controls without browser model credentials", () => {
  const drawerPath = new URL("../frontend/src/components/JDParserDrawer.tsx", import.meta.url);
  const apiPath = new URL("../frontend/src/lib/api.ts", import.meta.url);
  assert.equal(existsSync(drawerPath), true);
  const drawerSource = readFileSync(drawerPath, "utf8");
  const apiSource = readFileSync(apiPath, "utf8");

  assert.match(drawerSource, /role="dialog"/);
  assert.match(drawerSource, /aria-modal="true"/);
  assert.match(drawerSource, /解析 JD/);
  assert.match(drawerSource, /确认并开始匹配/);
  assert.match(drawerSource, /解析新 JD/);
  assert.doesNotMatch(apiSource, /DEEPSEEK_API_KEY|X-DeepSeek-Api-Key|deepseekApiKey/);
  assert.doesNotMatch(apiSource, /const defaultConfig:[^\n]*deepseek/i);
});

test("drawer focus cycling wraps Tab and Shift+Tab within available controls", () => {
  const calls = [];
  const first = { focus: () => calls.push("first"), isConnected: true };
  const middle = { focus: () => calls.push("middle"), isConnected: true };
  const last = { focus: () => calls.push("last"), isConnected: true };

  assert.equal(cycleFocus([first, middle, last], last, false), first);
  assert.equal(cycleFocus([first, middle, last], first, true), last);
  assert.deepEqual(calls, ["first", "last"]);
});

test("drawer focus restoration uses the connected fallback when its opener unmounts", () => {
  const calls = [];
  const opener = { focus: () => calls.push("opener"), isConnected: false };
  const matchSegment = { focus: () => calls.push("match"), isConnected: true };

  assert.equal(restoreFocus(opener, matchSegment), matchSegment);
  assert.deepEqual(calls, ["match"]);
});

test("successful position save remains committed when the following refresh fails", async () => {
  const saved = { id: 7, position_name: "平台产品负责人", is_active: true };
  const result = await saveThenRefreshPosition(
    async () => saved,
    async () => { throw new Error("refresh unavailable"); },
  );

  assert.equal(result.position, saved);
  assert.equal(result.positions, null);
  assert.equal(result.refreshError instanceof Error, true);
});

test("position save rejection remains an error before any refresh is attempted", async () => {
  let refreshed = false;
  await assert.rejects(
    saveThenRefreshPosition(
      async () => { throw new Error("save rejected"); },
      async () => { refreshed = true; return []; },
    ),
    /save rejected/,
  );
  assert.equal(refreshed, false);
});
