// Reloop 触达工作台 — 路由 + 视图（Home / Talents / Talent detail / Positions / Settings）
import { api, getCfg, setCfg, useMock } from "./data/provider.js";
import { STRINGS } from "./i18n.js";

const view = document.getElementById("view");
const tabsEl = document.getElementById("tabs");
let LOCALE = getCfg().locale || "zh-CN";
const t = (k) => (STRINGS[LOCALE] && STRINGS[LOCALE][k]) || STRINGS["zh-CN"][k] || k;
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// —— 当前选中岗位（跨视图共享）——
let CURRENT_POSITION = null;

// —— 五因子键顺序（雷达 5 个顶点）——
const FACTOR_KEYS = ["activity", "match", "value", "relationship", "tendency"];
const factorLabel = (k) => t("factor_" + k);

// 五因子雷达（SVG 五边形，复刻设计语言）
function radarSVG(bd) {
  const cx = 50, cy = 52, R = 40;
  const pts = FACTOR_KEYS.map((k, i) => {
    const ang = -Math.PI / 2 + (i * 2 * Math.PI) / 5;
    const v = Math.max(0.05, Math.min(1, bd?.[k] ?? 0));
    return [cx + Math.cos(ang) * R * v, cy + Math.sin(ang) * R * v];
  });
  const grid = FACTOR_KEYS.map((k, i) => {
    const ang = -Math.PI / 2 + (i * 2 * Math.PI) / 5;
    return [cx + Math.cos(ang) * R, cy + Math.sin(ang) * R];
  });
  const poly = pts.map((p) => p.map((n) => n.toFixed(1)).join(",")).join(" ");
  const gridPoly = grid.map((p) => p.map((n) => n.toFixed(1)).join(",")).join(" ");
  const dots = pts.map((p) => `<circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="2" fill="#1B4FD8"/>`).join("");
  return `<svg class="radar" viewBox="0 0 100 104" role="img" aria-label="${t("why")}">
    <polygon points="${gridPoly}" fill="none" stroke="rgba(26,26,26,.25)"/>
    <polygon points="${gridPoly}" fill="none" stroke="rgba(26,26,26,.12)" transform="translate(50 52) scale(.5) translate(-50 -52)"/>
    <polygon points="${poly}" fill="rgba(27,79,216,.18)" stroke="#1B4FD8" stroke-width="2"/>${dots}
  </svg>`;
}

function factorBars(bd) {
  return `<div class="factors">${FACTOR_KEYS.map((k) => {
    const v = Math.max(0, Math.min(1, bd?.[k] ?? 0));
    return `<div class="factor"><span>${factorLabel(k)}</span><span class="bar"><span class="fill" style="width:${(v * 100).toFixed(0)}%"></span></span><span class="fnum">${v.toFixed(2)}</span></div>`;
  }).join("")}</div>`;
}

// 「为什么排这里」——从 breakdown 里挑最高/最低因子生成一句解读（弥补后端只给数字）
function whyReason(bd) {
  if (!bd) return "";
  const entries = FACTOR_KEYS.map((k) => [k, bd[k] ?? 0]);
  const top = entries.slice().sort((a, b) => b[1] - a[1])[0];
  const low = entries.slice().sort((a, b) => a[1] - b[1])[0];
  return `${factorLabel(top[0])} ${top[1].toFixed(2)} ${t("why_high")}；${factorLabel(low[0])} ${low[1].toFixed(2)} ${t("why_low")}。`;
}

const ring = (score) => {
  const off = Math.round(126 * (1 - Math.max(0, Math.min(1, score))));
  return `<span class="score"><svg viewBox="0 0 52 52"><circle class="track" cx="26" cy="26" r="20"/><circle class="meter" style="stroke-dashoffset:${off}" cx="26" cy="26" r="20"/></svg>${score.toFixed(2)}</span>`;
};

function loading() { view.innerHTML = `<div class="spinner">${t("loading")}…</div>`; }

// ============ Home / 今日推荐 ============
async function renderHome() {
  loading();
  const positions = await api.listPositions();
  if (!CURRENT_POSITION) CURRENT_POSITION = positions[0]?.position_name || "商业分析师";
  const reco = await api.recommend(CURRENT_POSITION);
  const items = (reco.top_n || []).slice();
  const pending = items.filter((i) => (i.status || "pending") === "pending").length;

  const chips = positions.map((p) => `<button class="chip" data-pos="${esc(p.position_name)}" aria-pressed="${p.position_name === CURRENT_POSITION}">${esc(p.position_name)}</button>`).join("");
  const rows = items.length ? items.map((it, idx) => rowHTML(it, idx === 0)).join("") : `<div class="empty">${t("empty_reco")}</div>`;

  view.innerHTML = `
    <header class="mast">
      <div><div class="kicker">${t("kicker")} / ${esc(CURRENT_POSITION)}</div><h1>${t("heroTitle")}</h1></div>
      <div class="run"><b>${new Date().toLocaleTimeString(LOCALE, { hour: "2-digit", minute: "2-digit" })}</b>${esc(reco.run_id || "")}</div>
    </header>
    <nav class="positions" aria-label="${t("aria_switch_pos")}">${chips}</nav>
    <div class="stats"><div class="stat"><span>${t("stat_pool")}</span><strong>${reco.total_pool ?? "—"}</strong></div><div class="stat"><span>${t("stat_short")}</span><strong>${reco.shortlisted ?? items.length}</strong></div><div class="stat"><span>${t("stat_pending")}</span><strong id="pendingCount">${pending}</strong></div></div>
    <div class="board">${rows}</div>`;

  view.querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => { CURRENT_POSITION = c.dataset.pos; renderHome(); }));
  wireRows();
}

function rowHTML(it, open) {
  const bd = it.score_breakdown || {};
  return `<details class="row" data-tid="${it.talent_id}" ${open ? "open" : ""}>
    <summary>
      <span class="rank">#${String(it.rank).padStart(2, "0")}</span>
      <span class="person"><span class="name-line"><span class="name">${esc(it.name)}</span><span class="base">${esc(it.base_location || "")}</span></span><span class="meta">${esc(it.company || "")} · ${esc(it.position || "")}</span><span class="reason">${esc(it.contact_reason || "")}</span></span>
      ${ring(it.score || 0)}
    </summary>
    <div class="expanded">
      <div class="radar-wrap">${radarSVG(bd)}<div class="radar-legend">${FACTOR_KEYS.map((k) => `<span><i></i>${factorLabel(k)} ${(bd[k] ?? 0).toFixed(2)}</span>`).join("")}</div></div>
      <div class="insight">
        <b>${t("why")}</b><p>${esc(whyReason(bd))}</p>
        ${factorBars(bd)}
        <div class="actions" data-tid="${it.talent_id}">
          <button class="act primary" data-act="confirm">${t("act_contact")}</button>
          <button class="act" data-act="reject">${t("act_skip")}</button>
          <button class="act" data-act="correct">${t("act_correct")}</button>
        </div>
        <div class="status-line" aria-live="polite">${statusText(it.status)}</div>
      </div>
    </div>
  </details>`;
}
function statusText(s) { if (s === "confirmed") return t("done_contact"); if (s === "rejected") return t("done_skip"); return ""; }

function wireRows() {
  view.querySelectorAll(".actions").forEach((group) => {
    group.addEventListener("click", async (e) => {
      const btn = e.target.closest("button"); if (!btn) return;
      const tid = Number(group.dataset.tid); const action = btn.dataset.act;
      group.querySelectorAll(".act").forEach((b) => (b.dataset.state = ""));
      btn.dataset.state = "done";
      const status = group.parentElement.querySelector(".status-line");
      status.textContent = action === "confirm" ? t("done_contact") : action === "reject" ? t("done_skip") : t("done_correct");
      await api.feedback({ talent_id: tid, action });
      if (action !== "correct") {
        const el = document.getElementById("pendingCount");
        if (el) el.textContent = String(Math.max(0, Number(el.textContent) - 1));
      }
    });
  });
}

// ============ Talents / 人才库 ============
async function renderTalents(keyword = "") {
  loading();
  const list = await api.listTalents(keyword);
  const rows = list.length ? list.map((tp) => `
    <div class="titem" data-id="${tp.id}">
      <div><div class="name-line"><span class="name">${esc(tp.name)}</span><span class="base">${esc(tp.base_location || "")}</span></div>
      <div class="meta">${esc(tp.company || "")} · ${esc(tp.position || "")}</div>
      <div class="tags-row">${(tp.skills || []).slice(0, 3).map((s) => `<span class="tag">${esc(s)}</span>`).join("")}</div></div>
      <span class="vscore">${tp.value_score != null ? tp.value_score.toFixed(2) : "—"}</span>
    </div>`).join("") : `<div class="empty">—</div>`;

  view.innerHTML = `
    <header class="mast"><div><div class="kicker">${t("kicker")}</div><h1>${t("talent_pool")}</h1></div></header>
    <div class="searchbar"><div class="field"><input id="kw" placeholder="${t("search_ph")}" value="${esc(keyword)}"></div><button class="btn blue" id="searchBtn">${t("search_btn")}</button></div>
    <div class="tlist">${rows}</div>`;

  view.querySelector("#searchBtn").addEventListener("click", () => renderTalents(view.querySelector("#kw").value.trim()));
  view.querySelector("#kw").addEventListener("keydown", (e) => { if (e.key === "Enter") renderTalents(e.target.value.trim()); });
  view.querySelectorAll(".titem").forEach((el) => el.addEventListener("click", () => { location.hash = `#/talent/${el.dataset.id}`; }));
}

// ============ Talent detail / 人才详情 ============
async function renderTalentDetail(id) {
  loading();
  const tp = await api.getTalent(id);
  if (!tp) { view.innerHTML = `<div class="empty">—</div>`; return; }
  const inter = await api.getInteractions(id);
  const bd = { activity: 0.5, match: 0.6, value: tp.value_score ?? 0.5, relationship: 0.3, tendency: tp.tendency_score ?? 0.5 };
  const kv = (k, v) => `<div class="kv"><span>${k}</span><div>${esc(v ?? "—")}</div></div>`;

  view.innerHTML = `
    <header class="topback"><button class="iconbtn" id="back">←</button><div class="kicker">${t("kicker")}</div></header>
    <div class="detail-head"><h1>${esc(tp.name)}</h1><div class="meta">${esc(tp.company || "")} · ${esc(tp.position || "")} · ${esc(tp.base_location || "")}</div>
      <div class="tags-row">${(tp.tags || []).map((x) => `<span class="tag">${esc(x)}</span>`).join("")}</div></div>
    <div class="card soft">
      ${kv(t("detail_years"), tp.work_years != null ? tp.work_years + t("years_unit") : "—")}
      ${kv(t("detail_edu"), tp.education)}
      ${kv(t("detail_skills"), (tp.skills || []).join("、"))}
      ${kv(t("detail_value"), tp.value_score != null ? tp.value_score.toFixed(2) : "—")}
      ${kv(t("detail_tendency"), tp.tendency_score != null ? tp.tendency_score.toFixed(2) : "—")}
    </div>
    <div class="card"><div class="label">${t("why")}</div><div class="expanded" style="padding-left:0"><div class="radar-wrap">${radarSVG(bd)}</div><div class="insight">${factorBars(bd)}</div></div></div>
    <div class="card"><div class="label">${t("interactions")}</div>
      <div class="interactions">${inter.length ? inter.map((r) => `<div class="ilog"><span class="tag">${t("it_" + r.interaction_type) || r.interaction_type}</span><span>${esc(r.summary || "")}</span><span class="hint">${new Date(r.occurred_at).toLocaleDateString(LOCALE)}</span></div>`).join("") : `<div class="hint">${t("no_interactions")}</div>`}</div>
      <div class="label" style="margin-top:6px">${t("log_interaction")}</div>
      <div class="field"><select id="itype"><option value="call">${t("it_call")}</option><option value="message">${t("it_message")}</option><option value="interview">${t("it_interview")}</option><option value="note">${t("it_note")}</option></select></div>
      <div class="field"><input id="isum" placeholder="${t("inter_summary")}"></div>
      <button class="btn" id="isubmit">${t("inter_submit")}</button>
    </div>`;

  view.querySelector("#back").addEventListener("click", () => history.back());
  view.querySelector("#isubmit").addEventListener("click", async () => {
    await api.addInteraction(id, { interaction_type: view.querySelector("#itype").value, count: 1, summary: view.querySelector("#isum").value.trim() });
    renderTalentDetail(id);
  });
}

// ============ Positions / 岗位 ============
async function renderPositions() {
  loading();
  const positions = await api.listPositions();
  const list = positions.map((p) => `<div class="card soft"><div class="name-line"><span class="name">${esc(p.position_name)}</span>${p.is_active ? `<span class="badge">${t("active")}</span>` : ""}</div><div class="hint">${esc(p.jd_text || "")}</div></div>`).join("");
  view.innerHTML = `
    <header class="mast"><div><div class="kicker">${t("kicker")}</div><h1>${t("positions_title")}</h1></div></header>
    ${list}
    <div class="card"><div class="label">${t("set_position")}</div>
      <div class="field"><input id="pname" placeholder="${t("pos_name")}"></div>
      <div class="field"><textarea id="pjd" placeholder="${t("pos_jd")}"></textarea></div>
      <button class="btn blue" id="psubmit">${t("pos_submit")}</button>
    </div>`;
  view.querySelector("#psubmit").addEventListener("click", async () => {
    const name = view.querySelector("#pname").value.trim(); if (!name) return;
    await api.setPosition({ position_name: name, jd_text: view.querySelector("#pjd").value.trim() });
    CURRENT_POSITION = name; location.hash = "#/"; 
  });
}

// ============ Settings / 设置 ============
async function renderSettings() {
  const cfg = getCfg();
  view.innerHTML = `
    <header class="mast"><div><div class="kicker">${t("kicker")}</div><h1>${t("settings_title")}</h1></div>
      <div class="run"><b>${useMock() ? t("mode_mock") : t("mode_api")}</b></div></header>
    <div class="card"><div class="label">${t("data_source")}</div>
      <div class="api"><code>MODE=${useMock() ? "mock" : (cfg.apiBase || "同源")}</code><span class="badge ${useMock() ? "mut" : ""}">${useMock() ? "SAMPLE" : "LIVE"}</span></div>
      <div class="field"><span class="hint">${t("mode_label")}</span>
        <div class="seg"><button data-mode="live" class="${cfg.mode !== "mock" ? "on" : ""}">${t("ds_api")}</button><button data-mode="mock" class="${cfg.mode === "mock" ? "on" : ""}">${t("ds_mock")}</button></div></div>
      <div class="field"><span class="hint">${t("api_base")}</span><input id="apiBase" placeholder="${t("api_base_ph")}" value="${esc(cfg.apiBase)}"></div>
      <div class="field"><span class="hint">${t("owner_id")}</span><input id="ownerId" value="${esc(cfg.ownerId)}"></div>
      <div class="field"><span class="hint">${t("language")}</span>
        <div class="seg"><button data-loc="zh-CN" class="${LOCALE === "zh-CN" ? "on" : ""}">中文</button><button data-loc="en-US" class="${LOCALE === "en-US" ? "on" : ""}">EN</button></div></div>
      <button class="btn" id="saveCfg">${t("save")}</button>
      <div class="status-line" id="savedLine"></div>
    </div>
    <div class="card soft"><div class="label">${t("gaps_title")}</div>
      <div class="hint">${t("gaps_list")}</div>
    </div>`;

  view.querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", () => {
    if (b.dataset.loc) { LOCALE = b.dataset.loc; setCfg({ locale: LOCALE }); renderSettings(); renderTabs(); }
    if (b.dataset.mode) { setCfg({ mode: b.dataset.mode }); renderSettings(); }
  }));
  view.querySelector("#saveCfg").addEventListener("click", () => {
    setCfg({ apiBase: view.querySelector("#apiBase").value.trim(), ownerId: view.querySelector("#ownerId").value.trim(), locale: LOCALE });
    view.querySelector("#savedLine").textContent = t("saved");
  });
}

// ============ Router + Tabs ============
const TABS = [
  { hash: "#/", key: "tab_home", icon: "◆" },
  { hash: "#/talents", key: "tab_talents", icon: "▤" },
  { hash: "#/positions", key: "tab_positions", icon: "▣" },
  { hash: "#/settings", key: "tab_settings", icon: "⚙" },
];
function renderTabs() {
  const cur = location.hash || "#/";
  const base = "#/" + (cur.split("/")[1] || "");
  tabsEl.innerHTML = TABS.map((tb) => `<button class="tab ${base === tb.hash ? "active" : ""}" data-hash="${tb.hash}"><span class="ti">${tb.icon}</span>${t(tb.key)}</button>`).join("");
  tabsEl.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => { location.hash = b.dataset.hash; }));
}

function router() {
  const h = location.hash || "#/";
  window.scrollTo(0, 0);
  if (h.startsWith("#/talent/")) renderTalentDetail(h.split("/")[2]);
  else if (h.startsWith("#/talents")) renderTalents();
  else if (h.startsWith("#/positions")) renderPositions();
  else if (h.startsWith("#/settings")) renderSettings();
  else renderHome();
  renderTabs();
}
window.addEventListener("hashchange", router);
router();
