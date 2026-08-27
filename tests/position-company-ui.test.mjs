import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { formatPositionLabel } from "../frontend/src/lib/jd.ts";
import { MAX_JD_IMAGE_BYTES, MAX_JD_IMAGES, validateJdImageFiles } from "../frontend/src/lib/jdImages.ts";

function installBrowser() {
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
  return values;
}

test("position labels identify a company when available and otherwise retain the title", () => {
  assert.equal(formatPositionLabel({ id: 1, company_name: "北辰智能", position_name: "AI 产品经理", is_active: true }), "北辰智能 - AI 产品经理");
  assert.equal(formatPositionLabel({ id: 2, company_name: "  ", position_name: "AI 产品经理", is_active: true }), "AI 产品经理");
  assert.equal(formatPositionLabel({ id: 3, company_name: null, position_name: "AI 产品经理", is_active: true }), "AI 产品经理");
  assert.notEqual(
    formatPositionLabel({ id: 4, company_name: "北辰智能", position_name: "产品负责人", is_active: true }),
    formatPositionLabel({ id: 5, company_name: "远景科技", position_name: "产品负责人", is_active: true }),
  );
});

test("browser-local DeepSeek key is isolated from config and is attached only to JD parsing", async () => {
  const storage = installBrowser();
  const { api, config, deepseekApiKey } = await import(`../frontend/src/lib/api.ts?key-test=${Date.now()}`);
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), init });
    if (String(url).includes("parse-jd")) {
      return new Response(JSON.stringify({ analysis: { title: "AI 产品经理", summary: "摘要", responsibilities: ["职责"], required_skills: ["Python"], preferred_skills: ["LLM"], experience: "3 年", education: "本科", location: "上海", industry_keywords: ["AI"], salary_range: "面议", team_size: "5 人", reporting_line: "负责人", language_requirements: ["中文"], company_name: "北辰智能" }, source_text: "图片提取的 JD" }), { headers: { "Content-Type": "application/json" } });
    }
    return new Response(JSON.stringify([]), { headers: { "Content-Type": "application/json" } });
  };

  deepseekApiKey.write("  browser-only-secret  ");
  assert.equal(deepseekApiKey.read(), "browser-only-secret");
  storage.set("reloop.cfg", JSON.stringify({ mode: "live", deepseekApiKey: "browser-only-secret" }));
  assert.doesNotMatch(JSON.stringify(config.read()), /browser-only-secret|deepseek/i);

  await api.parseJd("原始 JD", ["data:image/png;base64,AA=="]);
  await api.listPositions();
  await api.recommend(42, "match");

  const parse = calls.find((call) => call.url.includes("parse-jd"));
  assert.equal(parse.init.headers["X-DeepSeek-Api-Key"], "browser-only-secret");
  assert.deepEqual(JSON.parse(parse.init.body), { jd_text: "原始 JD", images: ["data:image/png;base64,AA=="] });
  for (const call of calls.filter((call) => !call.url.includes("parse-jd"))) assert.equal(call.init.headers["X-DeepSeek-Api-Key"], undefined);
  assert.match(calls.find((call) => call.url.includes("recommend/compute")).url, /position_id=42/);

  deepseekApiKey.clear();
  assert.equal(deepseekApiKey.read(), "");
  assert.equal(storage.get("reloop.deepseekApiKey"), undefined);
});

test("JD image selection accepts four supported images and rejects invalid files before parsing", () => {
  const image = (name, type = "image/png", size = 1024) => ({ name, type, size });
  assert.equal(MAX_JD_IMAGES, 4);
  assert.equal(MAX_JD_IMAGE_BYTES, 8 * 1024 * 1024);
  assert.deepEqual(validateJdImageFiles([image("one.png"), image("two.jpg", "image/jpeg"), image("three.gif", "image/gif"), image("four.webp", "image/webp")], 0).accepted.map((file) => file.name), ["one.png", "two.jpg", "three.gif", "four.webp"]);
  const rejected = validateJdImageFiles([image("bad.svg", "image/svg+xml"), image("large.png", "image/png", MAX_JD_IMAGE_BYTES + 1)], 0);
  assert.equal(rejected.accepted.length, 0);
  assert.equal(rejected.errors.length, 2);
  assert.equal(validateJdImageFiles([image("extra.png")], MAX_JD_IMAGES).accepted.length, 0);
});

test("React matching uses position IDs, company editing, image controls, and no language-preference settings", () => {
  const app = readFileSync(new URL("../frontend/src/App.tsx", import.meta.url), "utf8");
  const drawer = readFileSync(new URL("../frontend/src/components/JDParserDrawer.tsx", import.meta.url), "utf8");

  assert.match(app, /selectedPositionId/);
  assert.match(app, /value=\{String\(position\.id\)\}/);
  assert.match(app, /api\.recommend\(selectedPositionId, "match"\)/);
  assert.match(app, /api\.recommendationResult\(selectedPositionId, "match"\)/);
  assert.match(app, /formatPositionLabel\(position\)/);
  assert.match(app, /company_name: companyName/);
  assert.match(app, /招聘公司/);
  assert.match(app, /if \(!positionHasParsedJd\(nextPosition\)\)/);
  assert.match(app, /setDrawerRawJd\(result\.source_text\)/);
  assert.match(app, /api\.parseJd\(drawerRawJd, drawerImages\.map\(\(image\) => image\.data_url\)\)/);
  assert.doesNotMatch(app, /使用偏好|保存偏好|locale|语言<select/);
  assert.match(app, /仅保存在此浏览器/);

  assert.match(drawer, /onPaste/);
  assert.match(drawer, /accept="image\/jpeg,image\/png,image\/gif,image\/webp"/);
  assert.match(drawer, /aria-label=\{`移除 \$\{image\.filename\}`\}/);
  assert.match(drawer, /alt=\{image\.filename\}/);
  assert.match(drawer, /招聘公司[\s\S]*岗位名称/);
});
