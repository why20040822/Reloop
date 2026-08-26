// Reloop 触达工作台 — 路由 + 视图（Home / Talents / Talent detail / Positions / Settings）
// v3.5: 双因子(活跃度+匹配度) / 排序切换+滑块 / 关注功能 / 详情页全字段 / 特别关注 / 岗位删除 / 同步进度
import { api, getCfg, setCfg, getAuth, setAuth, clearAuth, isAuthed, useMock } from "./data/provider.js";
import { STRINGS } from "./i18n.js";

const view = document.getElementById("view");
const tabsEl = document.getElementById("tabs");
let LOCALE = getCfg().locale || "zh-CN";
const t = (k, vars) => {
  let s = (STRINGS[LOCALE] && STRINGS[LOCALE][k]) || STRINGS["zh-CN"][k] || k;
  if (vars) Object.entries(vars).forEach(([key, val]) => { s = s.replace(`{${key}}`, val); });
  return s;
};
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// —— 全局状态 ——
let CURRENT_POSITION = null;
let SORT_BY = "match";
let W_ACTIVITY = 0.5;
let W_MATCH = 0.5;
let homeSeq = 0;

// —— 双因子(活跃度+匹配度) ——
const FACTOR_KEYS = ["activity", "match"];
const factorLabel = (k) => t("factor_" + k);

// 双因子条形图
function dualFactorBars(bd) {
  return `<div class="dual-factors">${FACTOR_KEYS.map((k) => {
    const v = Math.max(0, Math.min(1, bd?.[k] ?? 0));
    return `<div class="df-item"><span class="df-label">${factorLabel(k)}</span><span class="df-bar"><span class="df-fill" style="width:${(v * 100).toFixed(0)}%"></span></span><span class="df-val">${v.toFixed(2)}</span></div>`;
  }).join("")}</div>`;
}

function factorBars(bd) {
  return `<div class="factors">${FACTOR_KEYS.map((k) => {
    const v = Math.max(0, Math.min(1, bd?.[k] ?? 0));
    return `<div class="factor"><span>${factorLabel(k)}</span><span class="bar"><span class="fill" style="width:${(v * 100).toFixed(0)}%"></span></span><span class="fnum">${v.toFixed(2)}</span></div>`;
  }).join("")}</div>`;
}

function whyReason(bd) {
  if (!bd) return "";
  const act = bd.activity ?? 0;
  const match = bd.match ?? 0;
  if (act >= match) return `${t("factor_activity")} ${act.toFixed(2)} ${t("why_high")}；${t("factor_match")} ${match.toFixed(2)} ${t("why_low")}。`;
  return `${t("factor_match")} ${match.toFixed(2)} ${t("why_high")}；${t("factor_activity")} ${act.toFixed(2)} ${t("why_low")}。`;
}

const ring = (score) => {
  const off = Math.round(126 * (1 - Math.max(0, Math.min(1, score))));
  return `<span class="score"><svg viewBox="0 0 52 52"><circle class="track" cx="26" cy="26" r="20"/><circle class="meter" style="stroke-dashoffset:${off}" cx="26" cy="26" r="20"/></svg>${score.toFixed(2)}</span>`;
};

function loading() { view.innerHTML = `<div class="spinner">${t("loading")}…</div>`; }

// ============ Home / 今日推荐(两阶段: 初筛秒出 + 精算轮询更新) ============
async function renderHome() {
  const seq = ++homeSeq;
  loading();
  // 先获取岗位列表，确定 CURRENT_POSITION，再并行获取推荐+关注
  const positions = await api.listPositions().catch(() => []);
  if (seq !== homeSeq) return;
  if (!CURRENT_POSITION && positions.length) CURRENT_POSITION = positions[0]?.position_name;
  let reco = { top_n: [], phase: "final", total_pool: 0, shortlisted: 0 };
  let followed = [];
  try {
    [reco, followed] = await Promise.all([
      CURRENT_POSITION
        ? api.recommend(CURRENT_POSITION, SORT_BY,
            SORT_BY === "custom" ? W_ACTIVITY : undefined,
            SORT_BY === "custom" ? W_MATCH : undefined).catch(() => reco)
        : Promise.resolve(reco),
      api.listFollowed().catch(() => []),
    ]);
    // 兼容后端返回 error 结构
    if (reco && reco.error) {
      console.warn("[home] recommend returned error:", reco.error);
      reco = { top_n: [], phase: "final", total_pool: 0, shortlisted: 0 };
    }
  } catch (e) {
    console.warn("[home] recommend error:", e);
  }
  if (seq !== homeSeq) return;
  renderHomeView(positions, reco, followed);
  if (reco.computing || reco.phase === "preview") {
    pollFinalResult(seq, CURRENT_POSITION);
  }
}

function pollFinalResult(seq, positionName) {
  setTimeout(async () => {
    if (seq !== homeSeq || CURRENT_POSITION !== positionName) return;
    try {
      const r = await api.recommendResult(positionName, SORT_BY,
        SORT_BY === "custom" ? W_ACTIVITY : undefined,
        SORT_BY === "custom" ? W_MATCH : undefined);
      if (seq !== homeSeq || CURRENT_POSITION !== positionName) return;
      if (r.status === "done" && r.phase === "final") {
        const positions = await api.listPositions().catch(() => []);
        const followed = await api.listFollowed().catch(() => []);
        if (seq !== homeSeq || CURRENT_POSITION !== positionName) return;
        renderHomeView(positions, r, followed);
        return;
      }
      if (r.status === "failed") return;
    } catch (e) { /* 网络抖动: 继续下一轮 */ }
    pollFinalResult(seq, positionName);
  }, 2500);
}

function renderHomeView(positions, reco, followed) {
  followed = followed || [];
  const items = (reco.top_n || []).slice();
  const pending = items.filter((i) => (i.status || "pending") === "pending").length;
  const computing = !!(reco.computing || reco.phase === "preview");

  const chips = positions.map((p) => `<button class="chip" data-pos="${esc(p.position_name)}" aria-pressed="${p.position_name === CURRENT_POSITION}">${esc(p.position_name)}</button>`).join("");
  const banner = computing
    ? `<div class="calc-banner"><span class="pulse"></span>${t("computing_banner")}</div>`
    : (reco.cached ? `<div class="calc-banner done"><span class="dot"></span>${t("cached_banner")}</div>` : "");

  // 排序控件
  const sortBtns = `
    <div class="sort-controls">
      <button class="chip sort-btn" data-sort="match" aria-pressed="${SORT_BY === "match"}">${t("sort_by_match")}</button>
      <button class="chip sort-btn" data-sort="activity" aria-pressed="${SORT_BY === "activity"}">${t("sort_by_activity")}</button>
      <button class="chip sort-btn" data-sort="custom" aria-pressed="${SORT_BY === "custom"}">${t("sort_by_custom")}</button>
      ${SORT_BY === "custom" ? `
        <div class="weight-sliders">
          <label>${t("weight_activity")}: <span id="waVal">${W_ACTIVITY.toFixed(2)}</span></label>
          <input type="range" id="waSlider" min="0" max="1" step="0.05" value="${W_ACTIVITY}">
          <label>${t("weight_match")}: <span id="wmVal">${W_MATCH.toFixed(2)}</span></label>
          <input type="range" id="wmSlider" min="0" max="1" step="0.05" value="${W_MATCH}">
          <span class="hint">${t("weight_sum")}: ${(W_ACTIVITY + W_MATCH).toFixed(2)}</span>
        </div>` : ""}
    </div>`;

  const noPosMsg = positions.length === 0 ? '<div class="card soft" style="margin:12px 0"><div class="label">\u63d0\u793a</div><p>\u8bf7\u5148\u5230\u300c\u5c97\u4f4d\u7ba1\u7406\u300d\u8bbe\u5b9a\u62db\u8058\u5c97\u4f4d\u3002</p><a class="btn blue" href="#/positions" style="display:inline-block;text-decoration:none;margin-top:8px">\u53bb\u8bbe\u5b9a\u5c97\u4f4d</a></div>' : '';
  const rows = items.length ? items.map((it, idx) => rowHTML(it, idx === 0)).join("") : `<div class="empty">${t("empty_reco")}</div>`;

  view.innerHTML = `
    <header class="mast">
      <div><div class="kicker">${t("kicker")} / ${esc(CURRENT_POSITION)}</div><h1>${t("heroTitle")}</h1></div>
      <div class="run"><b>${new Date().toLocaleTimeString(LOCALE, { hour: "2-digit", minute: "2-digit" })}</b></div>
    </header>
    ${banner}
    <nav class="positions" aria-label="${t("aria_switch_pos")}">${chips}</nav>
    ${sortBtns}
    <button class="btn ghost" id="recomputeBtn">${t("recompute_btn")}</button>
    ${followed.length > 0 ? '<details class="followed-section" open><summary class="followed-summary">' + t("fav_section") + ' <span class="badge">' + followed.length + '</span></summary><div class="followed-grid">' + followed.map((tp) => '<div class="followed-card" data-id="' + tp.id + '"><div class="fc-name">' + esc(tp.name) + '</div><div class="fc-meta">' + esc(tp.company || "") + " · " + esc(tp.position || "") + '</div></div>').join("") + '</div></details>' : '<div class="followed-section empty-sec"><span class="hint">' + t("fav_empty") + '</span></div>'}
    <div class="stats"><div class="stat"><span>${t("stat_pool")}</span><strong>${reco.total_pool ?? "—"}</strong></div><div class="stat"><span>${t("stat_short")}</span><strong>${reco.shortlisted ?? items.length}</strong></div></div>
    <div class="board">${rows}</div>`;

  // 事件绑定
  view.querySelectorAll(".chip[data-pos]").forEach((c) => c.addEventListener("click", () => {
    if (CURRENT_POSITION === c.dataset.pos) return;
    CURRENT_POSITION = c.dataset.pos; renderHome();
  }));
  view.querySelectorAll(".sort-btn").forEach((btn) => btn.addEventListener("click", () => {
    SORT_BY = btn.dataset.sort;
    renderHome();
  }));
  const waSlider = view.querySelector("#waSlider");
  if (waSlider) {
    waSlider.addEventListener("input", (e) => {
      W_ACTIVITY = parseFloat(e.target.value);
      W_MATCH = 1 - W_ACTIVITY;
      view.querySelector("#waVal").textContent = W_ACTIVITY.toFixed(2);
      view.querySelector("#wmVal").textContent = W_MATCH.toFixed(2);
    });
    waSlider.addEventListener("change", () => renderHome());
  }
  const recomputeBtn = view.querySelector("#recomputeBtn");
  if (recomputeBtn) {
    recomputeBtn.addEventListener("click", async () => {
      recomputeBtn.disabled = true;
      recomputeBtn.textContent = t("loading") + "…";
      const reco = await api.recompute(CURRENT_POSITION, SORT_BY,
        SORT_BY === "custom" ? W_ACTIVITY : undefined,
        SORT_BY === "custom" ? W_MATCH : undefined);
      renderHomeView(positions, reco);
    });
  }
  wireRows();
  view.querySelectorAll(".followed-card").forEach((el) => el.addEventListener("click", () => { location.hash = `#/talent/${el.dataset.id}`; }));
}

function rowHTML(it, open) {
  const bd = it.score_breakdown || {};
  const preview = it.contact_reason && it.contact_reason.startsWith("快速初筛");
  const isFaved = (it.tags || []).includes("已关注");
  return `<details class="row" data-tid="${it.talent_id}" ${open ? "open" : ""}>
    <summary>
      <span class="rank">#${String(it.rank).padStart(2, "0")}</span>
      <span class="person"><span class="name-line"><span class="name">${esc(it.name)}${isFaved ? ' <span class="fav-star">★</span>' : ""}</span><span class="base">${esc(it.base_location || "")}</span></span><span class="meta">${esc(it.company || "")} · ${esc(it.position || "")}</span><span class="reason">${esc(it.contact_reason || "")}${preview ? ` <span class="preview-tag">${t("preview_tag")}</span>` : ""}</span></span>
      ${ring(it.score || 0)}
    </summary>
    <div class="expanded">
      <div class="dual-display">${dualFactorBars(bd)}</div>
      <div class="insight">
        <b>${t("why")}</b><p>${esc(whyReason(bd))}</p>
        <div class="actions" data-tid="${it.talent_id}">
          <button class="act ${isFaved ? "" : "primary"}" data-act="${isFaved ? "unfav" : "fav"}">${isFaved ? t("watch_remove") : t("watch_btn")}</button>
          <button class="act" data-act="reject">${t("act_skip")}</button>
          <button class="act" data-act="correct">${t("act_correct")}</button>
          <button class="act view-profile" data-tid="${it.talent_id}">查看完整档案</button>
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
      const status = group.parentElement.querySelector(".status-line");

      // 查看完整档案 -> 跳转详情页
      if (btn.classList.contains("view-profile")) {
        location.hash = `#/talent/${tid}`;
        return;
      }

      if (action === "fav" || action === "unfav") {
        await api.feedback({ talent_id: tid, action });
        btn.dataset.state = "done";
        status.textContent = action === "fav" ? t("watch_added") : "";
        // 切换按钮状态
        if (action === "fav") {
          btn.textContent = t("watch_remove");
          btn.classList.remove("primary");
          btn.dataset.act = "unfav";
        } else {
          btn.textContent = t("watch_btn");
          btn.classList.add("primary");
          btn.dataset.act = "fav";
        }
        return;
      }

      group.querySelectorAll(".act").forEach((b) => (b.dataset.state = ""));
      btn.dataset.state = "done";
      status.textContent = action === "confirm" ? t("done_contact") : action === "reject" ? t("done_skip") : t("done_correct");
      await api.feedback({ talent_id: tid, action });
    });
  });
}

// ============ Talents / 人才库 ============
async function renderTalents(keyword = "") {
  loading();
  try {
    const list = await api.listTalents(keyword);
    const rows = list.length ? list.map((tp) => {
    const isFollowed = (tp.tags || []).includes("已关注");
    const statusChip = tp.seek_status ? `<span class="tag st-${esc(tp.seek_status)}">${esc(tp.seek_status)}</span>` : "";
    const contactChip = tp.contact_status ? `<span class="tag">联系: ${esc(tp.contact_status)}</span>` : "";
    return `<div class="titem" data-id="${tp.id}">
      <div><div class="name-line"><span class="name">${esc(tp.name)}${isFollowed ? ' <span class="fav-star">★</span>' : ""}</span><span class="base">${esc(tp.base_location || "")}</span></div>
      <div class="meta">${esc(tp.company || "")} · ${esc(tp.position || "")}</div>
      <div class="tags-row">${(tp.skills || []).slice(0, 3).map((s) => `<span class="tag">${esc(s)}</span>`).join("")}${statusChip}${contactChip}</div></div>
      <span class="vscore">${tp.work_years != null ? tp.work_years.toFixed(1) + t("years_unit") : "—"}</span>
    </div>`;
  }).join("") : `<div class="empty">—</div>`;

    view.innerHTML = `
    <header class="mast"><div><div class="kicker">${t("kicker")}</div><h1>${t("talent_pool")}</h1></div></header>
    <div class="searchbar"><div class="field"><input id="kw" placeholder="${t("search_ph")}" value="${esc(keyword)}"></div><button class="btn blue" id="searchBtn">${t("search_btn")}</button></div>
    <div class="tlist">${rows}</div>`;

    view.querySelector("#searchBtn").addEventListener("click", () => renderTalents(view.querySelector("#kw").value.trim()));
    view.querySelector("#kw").addEventListener("keydown", (e) => { if (e.key === "Enter") renderTalents(e.target.value.trim()); });
    view.querySelectorAll(".titem").forEach((el) => el.addEventListener("click", () => { location.hash = `#/talent/${el.dataset.id}`; }));
  } catch (e) {
    view.innerHTML = `<div class="empty">${esc(e.message || t("loading") + "失败")}</div>`;
  }
}

// ============ 特别关注人选 ============
async function renderFollowed() {
  loading();
  const list = await api.listTalents();
  const followed = list.filter((t) => (t.tags || []).includes("已关注"));
  const rows = followed.length ? followed.map((tp) => `
    <div class="titem" data-id="${tp.id}">
      <div><div class="name-line"><span class="name">${esc(tp.name)} <span class="fav-star">★</span></span><span class="base">${esc(tp.base_location || "")}</span></div>
      <div class="meta">${esc(tp.company || "")} · ${esc(tp.position || "")}</div></div>
    </div>`).join("") : `<div class="empty">${t("fav_empty")}</div>`;

  view.innerHTML = `
    <header class="mast"><div><div class="kicker">${t("kicker")}</div><h1>${t("fav_section")}</h1></div></header>
    <div class="tlist">${rows}</div>`;

  view.querySelectorAll(".titem").forEach((el) => el.addEventListener("click", () => { location.hash = `#/talent/${el.dataset.id}`; }));
  // 更新侧边栏计数
  const badge = document.getElementById("followedCount");
  if (badge) badge.textContent = String(followed.length);
}

// ============ Talent detail / 人才详情 (全字段) ============
function fmtDate(v) {
  if (!v) return "—";
  const d = new Date(v);
  return isNaN(d) ? String(v) : d.toLocaleDateString(LOCALE);
}

async function renderTalentDetail(id) {
  loading();
  const tp = await api.getTalent(id);
  if (!tp) { view.innerHTML = `<div class="empty">—</div>`; return; }
  const inter = await api.getInteractions(id);
  const kv = (k, v) => `<div class="kv"><span>${k}</span><div>${esc(v ?? "—")}</div></div>`;
  const isFollowed = (tp.tags || []).includes("已关注");

  // ---- 基本信息(含联系方式/求职状态/薪资/目标岗位) ----
  const basicInfo = [
    kv("联系电话", tp.contact_phone || "—"),
    kv("邮箱", tp.contact_email || "—"),
    kv("所在城市", tp.base_location),
    kv(t("detail_years"), tp.work_years != null ? tp.work_years + t("years_unit") : "—"),
    kv(t("detail_edu"), tp.education),
    kv("求职状态", tp.seek_status || "—"),
    kv("当前薪资", tp.current_salary || "—"),
    kv("期望薪资", tp.expected_salary || "—"),
    kv("目标岗位", (tp.target_positions || []).join("、") || "—"),
    kv(t("detail_skills"), (tp.skills || []).join("、")),
    kv("简历更新", fmtDate(tp.resume_updated_at)),
    kv("最近活跃", fmtDate(tp.last_active_at)),
  ].join("");

  // ---- 教育经历明细 ----
  const eduRows = (tp.education_history || []).map((e) => {
    const tier = Array.isArray(e.school_tier) ? e.school_tier.join("/") : (e.school_tier || "");
    return `<div class="edu-item">
      <strong>${esc(e.school || "")}</strong>${e.major ? ` · ${esc(e.major)}` : ""}
      <span class="tag">${esc(e.degree || "")}</span>
      <span class="hint">${esc(e.start_date || "")} - ${esc(e.end_date || "至今")}${tier ? " · " + esc(tier) : ""}</span>
    </div>`;
  }).join("");

  // ---- 工作经历(多段: 起止时间/公司/业务线/岗位·职级/职责/管理规模) ----
  const workHistory = (tp.work_history || []).map((wh) => {
    const dur = wh.duration_months ? `${Math.round(wh.duration_months / 12)}年${wh.duration_months % 12}月` : "";
    const level = wh.job_level ? ` · ${esc(wh.job_level)}` : "";
    const line = wh.business_line ? ` · ${esc(wh.business_line)}` : "";
    const mgmt = wh.management_scale ? `<span class="tag">管理: ${esc(wh.management_scale)}</span>` : "";
    return `<div class="wh-item">
      <strong>${esc(wh.company || "")}</strong>${line}
      <div class="meta">${esc(wh.position || "")}${level}</div>
      <span class="hint">${esc(wh.start_date || "")} - ${esc(wh.end_date || "至今")}${dur ? " · " + dur : ""}${wh.is_internship ? " · 实习" : ""}</span>
      ${mgmt}
      ${wh.description ? `<div class="wh-desc">${esc(wh.description)}</div>` : ""}
    </div>`;
  }).join("");

  // ---- 稳定性 ----
  const stab = tp.stability || {};
  const stabilityInfo = (stab.avg_tenure != null || stab.max_tenure != null) ? [
    kv(t("stability_avg"), stab.avg_tenure != null ? stab.avg_tenure.toFixed(1) + "年" : "—"),
    kv(t("stability_max"), stab.max_tenure != null ? stab.max_tenure.toFixed(1) + "年" : "—"),
    kv(t("stability_recent"), stab.recent_tenure != null ? stab.recent_tenure.toFixed(1) + "年" : "—"),
    kv(t("stability_companies"), stab.company_count ?? "—"),
    stab.max_management_scale ? kv("最大管理规模", stab.max_management_scale) : "",
    stab.has_big_company_exp != null ? kv("大厂经验", stab.has_big_company_exp ? "是" : "否") : "",
  ].join("") : "";

  // ---- 项目经验(完整) ----
  const projects = (tp.projects || []).map((p) => {
    const stack = Array.isArray(p.tech_stack) ? p.tech_stack.join(", ") : (p.tech_stack || "");
    const ind = Array.isArray(p.industry) ? p.industry.join("/") : (p.industry || "");
    const scen = Array.isArray(p.scenario) ? p.scenario.join("/") : (p.scenario || "");
    const badges = [p.is_ai_project ? "AI项目" : "", p.has_landing ? "已落地" : "", p.is_zero_to_one ? "0→1" : ""].filter(Boolean).map((b) => `<span class="tag">${b}</span>`).join("");
    return `<div class="proj-item">
      <strong>${esc(p.name || "")}</strong>${p.role ? ` · ${esc(p.role)}` : ""}${p.company ? ` @ ${esc(p.company)}` : ""}
      ${ind ? `<span class="tag">${esc(ind)}</span>` : ""}
      ${badges}
      <div class="hint">${esc(p.start_date || "")} - ${esc(p.end_date || "")}${scen ? " · 场景: " + esc(scen) : ""}</div>
      ${stack ? `<div class="hint">${t("project_stack")}: ${esc(stack)}</div>` : ""}
      ${p.description ? `<div class="wh-desc">${esc(p.description)}</div>` : ""}
      ${p.core_achievement ? `<div class="wh-desc ach">成果: ${esc(p.core_achievement)}</div>` : ""}
    </div>`;
  }).join("");

  // ---- 投递记录 ----
  const deliveries = (tp.delivery_records || []).map((d) => `<div class="del-item"><span>${esc(d.position || "")}</span> · <span>${esc(d.company || "")}</span><span class="hint">${esc(d.date || "")} ${esc(d.status || "")}</span></div>`).join("");

  // ---- 备注(含关注原因/联系状态) ----
  const contactStatusBadge = tp.contact_status ? `<span class="tag st-${esc(tp.contact_status)}">联系状态: ${esc(tp.contact_status)}</span>` : "";
  const notes = (tp.notes || contactStatusBadge) ? `<div class="card soft"><div class="label">${t("notes_title")}</div><div class="tags-row">${contactStatusBadge}</div>${tp.notes ? `<p>${esc(tp.notes)}</p>` : `<p class="hint">—</p>`}</div>` : "";

  view.innerHTML = `
    <header class="topback"><button class="iconbtn" id="back">←</button><div class="kicker">${t("kicker")}</div></header>
    <div class="detail-head">
      <h1>${esc(tp.name)}</h1>
      <div class="meta">${esc(tp.company || "")} · ${esc(tp.position || "")} · ${esc(tp.base_location || "")}</div>
      <div class="tags-row">${(tp.tags || []).map((x) => `<span class="tag">${esc(x)}</span>`).join("")}</div>
      <div style="display:flex;gap:8px;align-items:center;margin-top:8px">
        <button class="btn ${isFollowed ? "" : "blue"}" id="favBtn" data-fav="${isFollowed ? "1" : "0"}">${isFollowed ? t("watch_remove") : t("watch_btn")}</button>
        ${tp.contact_status ? `<span class="badge">${esc(tp.contact_status)}</span>` : ""}
      </div>
    </div>
    <div class="card soft"><div class="label">基本信息</div>${basicInfo}</div>
    ${eduRows ? `<div class="card soft"><div class="label">教育经历</div>${eduRows}</div>` : ""}
    ${stabilityInfo ? `<div class="card soft"><div class="label">稳定性指标</div>${stabilityInfo}</div>` : ""}
    ${workHistory ? `<div class="card soft"><div class="label">${t("work_history_title")}</div>${workHistory}</div>` : ""}
    ${projects ? `<div class="card soft"><div class="label">${t("projects_title")}</div>${projects}</div>` : ""}
    ${deliveries ? `<div class="card soft"><div class="label">投递记录</div>${deliveries}</div>` : ""}
    ${notes}
    <div class="card"><div class="label">${t("interactions")}</div>
      <div class="interactions">${inter.length ? inter.map((r) => `<div class="ilog"><span class="tag">${t("it_" + r.interaction_type) || r.interaction_type}</span><span>${esc(r.summary || "")}</span><span class="hint">${r.occurred_at ? new Date(r.occurred_at).toLocaleDateString(LOCALE) : ""}</span></div>`).join("") : `<div class="hint">${t("no_interactions")}</div>`}</div>
      <div class="label" style="margin-top:6px">${t("log_interaction")}</div>
      <div class="field"><select id="itype"><option value="call">${t("it_call")}</option><option value="message">${t("it_message")}</option><option value="interview">${t("it_interview")}</option><option value="note">${t("it_note")}</option></select></div>
      <div class="field"><input id="isum" placeholder="${t("inter_summary")}"></div>
      <button class="btn" id="isubmit">${t("inter_submit")}</button>
    </div>`;

  view.querySelector("#back").addEventListener("click", () => history.back());
  view.querySelector("#favBtn").addEventListener("click", async () => {
    await api.followTalent(Number(id));
    renderTalentDetail(id);
  });
  view.querySelector("#isubmit").addEventListener("click", async () => {
    await api.addInteraction(id, { interaction_type: view.querySelector("#itype").value, count: 1, summary: view.querySelector("#isum").value.trim() });
    renderTalentDetail(id);
  });
}

// ============ Positions / 岗位管理 ============
async function renderPositions() {
  loading();
  const positions = await api.listPositions();
  const list = positions.map((p) => `
    <div class="card soft">
      <div class="name-line">
        <span class="name">${esc(p.position_name)}</span>
        ${p.is_active ? `<span class="badge">${t("active")}</span>` : ""}
        <button class="act del-pos-btn" data-id="${p.id}" data-name="${esc(p.position_name)}" style="margin-left:auto">${t("del_position")}</button>
      </div>
      <div class="hint">${esc(p.jd_text || "").slice(0, 200)}</div>
    </div>`).join("");

  view.innerHTML = `
    <header class="mast"><div><div class="kicker">${t("kicker")}</div><h1>${t("positions_title")}</h1></div></header>
    ${list}
    <div class="card"><div class="label">${t("set_position")}</div>
      <div class="field"><span class="hint">${t("pos_name")}</span><input id="pname" placeholder="${t("pos_name_ph")}"></div>
      <div class="field"><span class="hint">${t("pos_jd")}</span><textarea id="pjd" placeholder="${t("pos_jd_ph")}" rows="4"></textarea></div>
      <button class="btn blue" id="psubmit">${t("pos_submit")}</button>
    </div>`;

  view.querySelector("#psubmit").addEventListener("click", async () => {
    const name = view.querySelector("#pname").value.trim(); if (!name) return;
    await api.setPosition({ position_name: name, jd_text: view.querySelector("#pjd").value.trim() });
    CURRENT_POSITION = name; location.hash = "#/";
  });

  // 删除按钮
  view.querySelectorAll(".del-pos-btn").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!confirm(t("del_position_confirm"))) return;
      await api.deletePosition(Number(btn.dataset.id));
      if (CURRENT_POSITION === btn.dataset.name) CURRENT_POSITION = null;
      renderPositions();
    });
  });
}

// ============ Settings / 设置 ============
async function renderSettings() {
  const cfg = getCfg();
  const auth = getAuth();
  let meInfo = null;
  if (!useMock() && isAuthed()) {
    try { meInfo = await api.me(); } catch (e) { /* auth preserved, no clearAuth */ }
  }
  view.innerHTML = `
    <header class="mast"><div><div class="kicker">${t("kicker")}</div><h1>${t("settings_title")}</h1></div>
      <div class="run"><b>${useMock() ? t("mode_mock") : t("mode_api")}</b></div></header>
    <div class="card"><div class="label">${t("data_source")}</div>
      <div class="api"><code>MODE=${useMock() ? "mock" : (cfg.apiBase || "同源")}</code><span class="badge ${useMock() ? "mut" : ""}">${useMock() ? "SAMPLE" : "LIVE"}</span></div>
      <div class="field"><span class="hint">${t("mode_label")}</span>
        <div class="seg"><button data-mode="live" class="${cfg.mode !== "mock" ? "on" : ""}">${t("ds_api")}</button><button data-mode="mock" class="${cfg.mode === "mock" ? "on" : ""}">${t("ds_mock")}</button></div></div>
      <div class="field"><span class="hint">${t("api_base")}</span><input id="apiBase" placeholder="${t("api_base_ph")}" value="${esc(cfg.apiBase)}"></div>
      <div class="field"><span class="hint">${t("language")}</span>
        <div class="seg"><button data-loc="zh-CN" class="${LOCALE === "zh-CN" ? "on" : ""}">中文</button><button data-loc="en-US" class="${LOCALE === "en-US" ? "on" : ""}">EN</button></div></div>
      <button class="btn" id="saveCfg">${t("save")}</button>
      <div class="status-line" id="savedLine"></div>
    </div>
    <div class="card soft"><div class="label">${t("account_title")}</div>
      ${meInfo ? `
        <div class="hint">${t("logged_as")}: <b>${esc(meInfo.display_name || meInfo.user_id)}</b> · ${t("pool_count")}: ${meInfo.pool_count}</div>
        <div class="hint">${t("data_isolated")}</div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <button class="btn" id="logout">${t("logout")}</button>
        </div>`
        : `<div class="hint">${t("not_logged_in")}</div>
        <button class="btn blue" id="loginBtn">${t("login_feishu")}</button>`}
    </div>
    <div class="card soft"><div class="label">${t("data_sync_title")}</div>
      <button class="btn blue" id="syncBtn">${t("ttc_sync_btn")}</button>
      <div id="syncProgress" class="hint" style="margin-top:8px"></div>
    </div>`;

  view.querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", () => {
    if (b.dataset.loc) { LOCALE = b.dataset.loc; setCfg({ locale: LOCALE }); renderSettings(); renderTabs(); }
    if (b.dataset.mode) { setCfg({ mode: b.dataset.mode }); renderSettings(); }
  }));
  view.querySelector("#saveCfg").addEventListener("click", () => {
    setCfg({ apiBase: view.querySelector("#apiBase").value.trim(), locale: LOCALE });
    view.querySelector("#savedLine").textContent = t("saved");
  });
  const loginBtn = view.querySelector("#loginBtn");
  if (loginBtn) loginBtn.addEventListener("click", openLoginModal);
  const logoutBtn = view.querySelector("#logout");
  if (logoutBtn) logoutBtn.addEventListener("click", () => { clearAuth(); renderSettings(); renderTabs(); });

  // 同步按钮
  const syncBtn = view.querySelector("#syncBtn");
  if (syncBtn) {
    syncBtn.addEventListener("click", async () => {
      syncBtn.disabled = true;
      syncBtn.textContent = t("ttc_syncing");
      try {
        const r = await api.syncTTC();
        const pollProgress = async () => {
          const progEl = view.querySelector("#syncProgress");
          if (!progEl) return;
          try {
            const status = await api.syncStatus(r.sync_id);
            if (status.status === "running") {
              progEl.textContent = t("sync_status_running", { current: status.current || 0, total: status.total || 0 });
              setTimeout(pollProgress, 1500);
            } else if (status.status === "done") {
              progEl.textContent = t("sync_status_done", { n: status.current || 0 });
              syncBtn.disabled = false;
              syncBtn.textContent = t("ttc_sync_btn");
            } else {
              progEl.textContent = t("sync_status_failed", { err: status.message || "" });
              syncBtn.disabled = false;
              syncBtn.textContent = t("ttc_sync_btn");
            }
          } catch (e) {
            progEl.textContent = t("sync_status_failed", { err: "网络错误" });
            syncBtn.disabled = false;
            syncBtn.textContent = t("ttc_sync_btn");
          }
        };
        pollProgress();
      } catch (e) {
        syncBtn.disabled = false;
        syncBtn.textContent = t("ttc_sync_btn");
      }
    });
  }
}

// ============ 飞书扫码登录 (不改动逻辑) ============
let _loginPollTimer = null;

async function openLoginModal() {
  closeModal();
  const overlay = document.createElement("div");
  overlay.className = "overlay"; overlay.id = "loginOverlay";
  overlay.innerHTML = `
    <div class="modal">
      <div class="label">${t("login_feishu")}</div>
      <button class="btn blue" id="openLoginBtn">${t("login_open")}</button>
      <div class="hint" id="loginLine">${t("login_hint")}</div>
      <div class="hint muted" style="font-size:11px">${t("login_redirect_note")}</div>
      <details style="margin-top:4px">
        <summary class="hint" style="cursor:pointer">${t("login_qr_fold")}</summary>
        <div class="qrbox"><img id="loginQr" alt="${t("login_feishu")}"></div>
        <div class="hint muted" style="font-size:11px">${t("login_qr_note")}</div>
      </details>
      <button class="btn" id="closeLogin">${t("close")}</button>
    </div>`;
  document.body.appendChild(overlay);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) closeModal(); });
  overlay.querySelector("#closeLogin").addEventListener("click", closeModal);

  const line = overlay.querySelector("#loginLine");
  overlay.querySelector("#openLoginBtn").addEventListener("click", async () => {
    try {
      const r = await api.feishuLoginUrl();
      window.open(r.url, "_blank");
      line.textContent = t("login_waiting");
    } catch (e) { line.textContent = t("login_qr_fail"); }
  });
  const qr = overlay.querySelector("#loginQr");
  overlay.querySelector("details").addEventListener("toggle", () => {
    if (!qr.src) { qr.src = api.qrcodeUrl(); qr.onerror = () => { line.textContent = t("login_qr_fail"); }; }
  });

  clearInterval(_loginPollTimer);
  _loginPollTimer = setInterval(() => {
    if (!document.getElementById("loginOverlay")) { clearInterval(_loginPollTimer); return; }
    if (isAuthed()) {
      clearInterval(_loginPollTimer);
      closeModal();
      renderTabs();
      router();
    }
  }, 1200);
}

function closeModal() {
  document.getElementById("loginOverlay")?.remove();
  clearInterval(_loginPollTimer);
}

async function handleAuthCallback() {
  const hash = location.hash || "";
  const q = hash.includes("?") ? hash.slice(hash.indexOf("?") + 1) : "";
  const code = new URLSearchParams(q).get("code") || new URLSearchParams(location.search).get("code");
  view.innerHTML = `<div class="spinner">${code ? t("logging_in") : t("auth_cb_err")}…</div>`;
  if (!code) { setTimeout(() => { location.hash = "#/"; }, 1500); return; }
  try {
    const r = await api.feishuLogin(code);
    setAuth(r);
    renderTabs();
    view.innerHTML = `
      <header class="mast"><div><div class="kicker">${t("kicker")}</div><h1>${t("login_success")}</h1></div></header>
      <div class="card soft"><div class="hint">${t("logged_as")}: <b>${esc(r.user?.display_name || "")}</b></div>
      <a class="btn blue" style="display:inline-block;text-align:center;text-decoration:none" href="#/">${t("login_back")}</a></div>`;
    setTimeout(() => { try { window.close(); } catch (e) {} }, 2000);
  } catch (e) {
    const msg = code ? t("login_failed") : t("auth_cb_err");
    view.innerHTML = `<div class="empty">${esc(msg)}<br><button class="btn" onclick="location.hash='#/'">${t("back")}</button></div>`;
  }
}

// ============ Router + Tabs ============
const TABS = [
  { hash: "#/", key: "tab_home", icon: "◆" },
  { hash: "#/talents", key: "tab_talents", icon: "▤" },
  { hash: "#/positions", key: "tab_positions", icon: "▣" },
  { hash: "#/settings", key: "tab_settings", icon: "⚙" },
];

function updateSidebarAuth() {
  const sidebarLogin = document.getElementById("sidebarLoginBtn");
  const profileMini = document.getElementById("profileMini");
  const auth = getAuth();
  if (auth) {
    if (sidebarLogin) sidebarLogin.style.display = "none";
    if (profileMini) {
      profileMini.style.display = "flex";
      const nameEl = profileMini.querySelector("strong");
      const smallEl = profileMini.querySelector("small");
      if (nameEl) nameEl.textContent = auth.user?.display_name || "用户";
      if (smallEl) smallEl.textContent = t("logged_as");
    }
  } else {
    if (sidebarLogin) sidebarLogin.style.display = "flex";
    if (profileMini) profileMini.style.display = "none";
  }
}

function renderTabs() {
  const cur = location.hash || "#/";
  const base = "#/" + (cur.split("/")[1] || "");
  const auth = getAuth();
  const authBtn = auth
    ? `<button class="tab auth" data-auth="settings" title="${esc(auth.user?.display_name || "")}"><span class="ti">◉</span>${esc((auth.user?.display_name || t("me")).slice(0, 8))}</button>`
    : `<button class="tab auth" data-auth="login"><span class="ti">◇</span>${t("login")}</button>`;
  tabsEl.innerHTML = TABS.map((tb) => `<button class="tab ${base === tb.hash ? "active" : ""}" data-hash="${tb.hash}"><span class="ti">${tb.icon}</span>${t(tb.key)}</button>`).join("") + authBtn;
  tabsEl.querySelectorAll(".tab[data-hash]").forEach((b) => b.addEventListener("click", () => { location.hash = b.dataset.hash; }));
  tabsEl.querySelectorAll(".tab[data-auth]").forEach((b) => b.addEventListener("click", () => {
    if (b.dataset.auth === "login") openLoginModal();
    else location.hash = "#/settings";
  }));
  updateSidebarAuth();

  // 更新特别关注计数
  if (isAuthed() || !useMock()) {
    api.listFollowed().then((list) => {
      const badge = document.getElementById("followedCount");
      if (badge) badge.textContent = String(list.length);
    }).catch(() => {});
  }
}

function router() {
  const h = location.hash || "#/";
  window.scrollTo(0, 0);
  closeModal();
  if (h.startsWith("#/auth/callback")) handleAuthCallback();
  else if (h.startsWith("#/talent/")) renderTalentDetail(h.split("/")[2]);
  else if (h.startsWith("#/talents")) {
    const params = new URLSearchParams(h.includes("?") ? h.split("?")[1] : "");
    if (params.get("filter") === "followed") renderFollowed();
    else renderTalents();
  }
  else if (h.startsWith("#/positions")) renderPositions();
  else if (h.startsWith("#/settings")) renderSettings();
  else renderHome();
  renderTabs();
}

// 侧边栏事件绑定
function initSidebar() {
  const sidebar = document.getElementById("sidebar");
  const backdrop = document.getElementById("sidebarBackdrop");
  const mobileBtn = document.getElementById("mobileMenuBtn");
  const collapseBtn = document.getElementById("sidebarCollapseBtn");

  if (mobileBtn) mobileBtn.addEventListener("click", () => { sidebar.classList.toggle("open"); backdrop.classList.toggle("show"); });
  if (backdrop) backdrop.addEventListener("click", () => { sidebar.classList.remove("open"); backdrop.classList.remove("show"); });
  if (collapseBtn) collapseBtn.addEventListener("click", () => { sidebar.classList.toggle("collapsed"); });

  const themeBtn = document.getElementById("themeToggleBtn");
  if (themeBtn) themeBtn.addEventListener("click", () => {
    const html = document.documentElement;
    const isDark = html.dataset.theme === "dark";
    html.dataset.theme = isDark ? "light" : "dark";
    themeBtn.querySelector(".theme-icon").textContent = isDark ? "🌙" : "☀️";
    themeBtn.querySelector("span:last-child").textContent = isDark ? "深色模式" : "浅色模式";
  });

  const sidebarLogin = document.getElementById("sidebarLoginBtn");
  if (sidebarLogin) sidebarLogin.addEventListener("click", openLoginModal);

  const profileMini = document.getElementById("profileMini");
  if (profileMini) profileMini.addEventListener("click", () => { location.hash = "#/settings"; });
}

initSidebar();
window.addEventListener("hashchange", router);
router();
