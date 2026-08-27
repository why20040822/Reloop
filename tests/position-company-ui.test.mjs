import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { applyParsedJdResult, formatPositionLabel } from "../frontend/src/lib/jd.ts";
import { MAX_JD_IMAGE_BYTES, MAX_JD_IMAGES, canParseJd, mergeJdImages, removeJdImage, validateJdImageFiles } from "../frontend/src/lib/jdImages.ts";
import { buildManualPositionPayload, buildReviewedPositionPayload, findPositionById, requiresJdParser } from "../frontend/src/lib/positionFlow.ts";

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

test("browser-local DeepSeek key is isolated from config and never crosses origins", async () => {
  const storage = installBrowser();
  const { api, canSendDeepseekApiKey, config, deepseekApiKey } = await import(`../frontend/src/lib/api.ts?key-test=${Date.now()}`);
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

  const callsBeforeCrossOrigin = calls.length;
  config.write({ apiBase: "https://other.example" });
  assert.equal(canSendDeepseekApiKey("https://other.example/positions/parse-jd", location.origin), false);
  await assert.rejects(api.parseJd("跨域 JD"), /仅能发送到同源工作台服务/);
  assert.equal(calls.length, callsBeforeCrossOrigin);

  deepseekApiKey.clear();
  await api.parseJd("无密钥跨域 JD");
  const noKeyCrossOriginParse = calls.at(-1);
  assert.match(noKeyCrossOriginParse.url, /^https:\/\/other\.example\/positions\/parse-jd/);
  assert.equal(noKeyCrossOriginParse.init.headers["X-DeepSeek-Api-Key"], undefined);

  assert.equal(deepseekApiKey.read(), "");
  assert.equal(storage.get("reloop.deepseekApiKey"), undefined);
});

test("JD input can parse text or images and image state merges/removes without stale reintroduction", () => {
  const image = (name, type = "image/png", size = 1024) => ({ name, type, size });
  assert.equal(MAX_JD_IMAGES, 4);
  assert.equal(MAX_JD_IMAGE_BYTES, 8 * 1024 * 1024);
  assert.deepEqual(validateJdImageFiles([image("one.png"), image("two.jpg", "image/jpeg"), image("three.gif", "image/gif"), image("four.webp", "image/webp")], 0).accepted.map((file) => file.name), ["one.png", "two.jpg", "three.gif", "four.webp"]);
  const rejected = validateJdImageFiles([image("bad.svg", "image/svg+xml"), image("large.png", "image/png", MAX_JD_IMAGE_BYTES + 1)], 0);
  assert.equal(rejected.accepted.length, 0);
  assert.equal(rejected.errors.length, 2);
  assert.equal(validateJdImageFiles([image("extra.png")], MAX_JD_IMAGES).accepted.length, 0);

  assert.equal(canParseJd("文本 JD", []), true);
  assert.equal(canParseJd("  ", [{ id: "one", filename: "one.png", data_url: "data:image/png;base64,AA==" }]), true);
  assert.equal(canParseJd("  ", []), false);

  const existing = [{ id: "one", filename: "one.png", data_url: "data:image/png;base64,one" }];
  const decodedLater = [{ id: "two", filename: "two.png", data_url: "data:image/png;base64,two" }];
  const removedCurrent = removeJdImage(existing, "one");
  assert.deepEqual(mergeJdImages(removedCurrent, decodedLater).map((item) => item.id), ["two"]);
  assert.deepEqual(mergeJdImages(existing, [...decodedLater, { id: "two", filename: "duplicate.png", data_url: "data:image/png;base64,duplicate" }]).map((item) => item.id), ["one", "two"]);
});

test("position flow applies parsed source text, mirrors company payloads, and gates same-title positions by ID", () => {
  const analysis = { company_name: "  北辰智能  ", title: "产品负责人", summary: "摘要", responsibilities: ["职责"], required_skills: ["技能"], preferred_skills: ["加分"], experience: "3 年", education: "本科", location: "上海", industry_keywords: ["AI"], salary_range: "面议", team_size: "5 人", reporting_line: "负责人", language_requirements: ["中文"] };
  const positions = [
    { id: 7, company_name: "北辰智能", position_name: "产品负责人", jd_analysis: analysis, is_active: true },
    { id: 8, company_name: "远景科技", position_name: "产品负责人", jd_analysis: null, is_active: true },
  ];
  assert.equal(findPositionById(positions, 8)?.company_name, "远景科技");
  assert.equal(requiresJdParser(findPositionById(positions, 7)), false);
  assert.equal(requiresJdParser(findPositionById(positions, 8)), true);
  assert.deepEqual(applyParsedJdResult({ analysis, source_text: "图片识别后的 JD" }), { analysis, rawJd: "图片识别后的 JD" });
  assert.deepEqual(buildReviewedPositionPayload(positions[0], analysis, "图片识别后的 JD"), { position_name: "产品负责人", company_name: "北辰智能", jd_text: "图片识别后的 JD", jd_analysis: { ...analysis, company_name: "北辰智能" } });
  assert.deepEqual(buildManualPositionPayload("  远景科技 ", "产品负责人", "手动 JD"), { position_name: "产品负责人", company_name: "远景科技", jd_text: "手动 JD" });
});

test("React keeps the tested helpers wired to controls and prevents heading overflow", () => {
  const app = readFileSync(new URL("../frontend/src/App.tsx", import.meta.url), "utf8");
  const drawer = readFileSync(new URL("../frontend/src/components/JDParserDrawer.tsx", import.meta.url), "utf8");
  const styles = readFileSync(new URL("../frontend/src/styles.css", import.meta.url), "utf8");

  assert.match(app, /value=\{String\(position\.id\)\}/);
  assert.match(app, /api\.parseJd\(drawerRawJd, drawerImages\.map\(\(image\) => image\.data_url\)\)/);
  assert.doesNotMatch(app, /使用偏好|保存偏好|locale|语言<select/);
  assert.match(drawer, /onPaste/);
  assert.match(drawer, /accept="image\/jpeg,image\/png,image\/gif,image\/webp"/);
  assert.match(drawer, /disabled=\{busy \|\| !canParseJd\(rawJd, images\)\}/);
  assert.match(drawer, /useEffect\(\(\) => \{ setImageError\(""\); \}, \[open\]\);/);
  assert.match(styles, /\.current-match-heading\s*\{[^}]*min-width:\s*0;/);
  assert.match(styles, /\.current-match-heading\s*\{[^}]*(?:overflow-wrap|word-break|text-overflow)/);
});
