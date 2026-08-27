// Talent detail / 人才详情 (全字段)
import { api } from "../../data/provider.js";
import { t, getLocale } from "../state.js";
import { esc, view, loading, fmtDate } from "../utils/dom.js";

export async function renderTalentDetail(id) {
  loading();
  const tp = await api.getTalent(id);
  if (!tp) { view().innerHTML = `<div class="empty">—</div>`; return; }
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

  view().innerHTML = `
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
      <div class="interactions">${inter.length ? inter.map((r) => `<div class="ilog"><span class="tag">${t("it_" + r.interaction_type) || r.interaction_type}</span><span>${esc(r.summary || "")}</span><span class="hint">${r.occurred_at ? new Date(r.occurred_at).toLocaleDateString(getLocale()) : ""}</span></div>`).join("") : `<div class="hint">${t("no_interactions")}</div>`}</div>
      <div class="label" style="margin-top:6px">${t("log_interaction")}</div>
      <div class="field"><select id="itype"><option value="call">${t("it_call")}</option><option value="message">${t("it_message")}</option><option value="interview">${t("it_interview")}</option><option value="note">${t("it_note")}</option></select></div>
      <div class="field"><input id="isum" placeholder="${t("inter_summary")}"></div>
      <button class="btn" id="isubmit">${t("inter_submit")}</button>
    </div>`;

  view().querySelector("#back").addEventListener("click", () => history.back());
  view().querySelector("#favBtn").addEventListener("click", async () => {
    await api.followTalent(Number(id));
    renderTalentDetail(id);
  });
  view().querySelector("#isubmit").addEventListener("click", async () => {
    await api.addInteraction(id, { interaction_type: view().querySelector("#itype").value, count: 1, summary: view().querySelector("#isum").value.trim() });
    renderTalentDetail(id);
  });
}
