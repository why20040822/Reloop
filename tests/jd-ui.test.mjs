import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

import { analysisToDraft, draftToAnalysis, positionHasParsedJd } from "../frontend/src/lib/jd.ts";

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
  assert.doesNotMatch(apiSource, /localStorage\.(?:getItem|setItem)\([^\n]*(?:deepseek|apiKey)/i);
});
