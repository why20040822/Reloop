// Home / 今日推荐(两阶段: 初筛秒出 + 精算轮询更新)
import { api } from "../../data/provider.js";
import { S, t, getLocale } from "../state.js";
import { esc, view, loading } from "../utils/dom.js";
import { dualFactorBars, whyReason } from "../components/factors.js";
import { ring } from "../components/score.js";
import { sectionCards } from "../components/section-cards.js";
import { toast } from "../components/toast.js";

export async function renderHome() {
  const seq = ++S.homeSeq;
  loading();
  // 先获取岗位列表，确定 CURRENT_POSITION，再并行获取推荐+关注
  const positions = await api.listPositions().catch(() => []);
  if (seq !== S.homeSeq) return;
  if (!S.CURRENT_POSITION && positions.length) S.CURRENT_POSITION = positions[0]?.position_name;
  let reco = { top_n: [], phase: "final", total_pool: 0, shortlisted: 0 };
  let followed = [];
  try {
    [reco, followed] = await Promise.all([
      S.CURRENT_POSITION
        ? api.recommend(S.CURRENT_POSITION, S.SORT_BY,
            S.SORT_BY === "custom" ? S.W_ACTIVITY : undefined,
            S.SORT_BY === "custom" ? S.W_MATCH : undefined).catch(() => reco)
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
  if (seq !== S.homeSeq) return;
  renderHomeView(positions, reco, followed);
  if (reco.computing || reco.phase === "preview") {
    pollFinalResult(seq, S.CURRENT_POSITION);
  }
}

function pollFinalResult(seq, positionName) {
  setTimeout(async () => {
    if (seq !== S.homeSeq || S.CURRENT_POSITION !== positionName) return;
    try {
      const r = await api.recommendResult(positionName, S.SORT_BY,
        S.SORT_BY === "custom" ? S.W_ACTIVITY : undefined,
        S.SORT_BY === "custom" ? S.W_MATCH : undefined);
      if (seq !== S.homeSeq || S.CURRENT_POSITION !== positionName) return;
      if (r.status === "done" && r.phase === "final") {
        const positions = await api.listPositions().catch(() => []);
        const followed = await api.listFollowed().catch(() => []);
        if (seq !== S.homeSeq || S.CURRENT_POSITION !== positionName) return;
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
  const computing = !!(reco.computing || reco.phase === "preview");

  const chips = positions.map((p) => `<button class="chip" data-pos="${esc(p.position_name)}" aria-pressed="${p.position_name === S.CURRENT_POSITION}">${esc(p.position_name)}</button>`).join("");
  const banner = computing
    ? `<div class="calc-banner"><span class="pulse"></span>${t("computing_banner")}</div>`
    : (reco.cached ? `<div class="calc-banner done"><span class="dot"></span>${t("cached_banner")}</div>` : "");

  // 排序控件
  const sortBtns = `
    <div class="sort-controls">
      <button class="chip sort-btn" data-sort="match" aria-pressed="${S.SORT_BY === "match"}">${t("sort_by_match")}</button>
      <button class="chip sort-btn" data-sort="activity" aria-pressed="${S.SORT_BY === "activity"}">${t("sort_by_activity")}</button>
      <button class="chip sort-btn" data-sort="custom" aria-pressed="${S.SORT_BY === "custom"}">${t("sort_by_custom")}</button>
      ${S.SORT_BY === "custom" ? `
        <div class="weight-sliders">
          <label>${t("weight_activity")}: <span id="waVal">${S.W_ACTIVITY.toFixed(2)}</span></label>
          <input type="range" id="waSlider" min="0" max="1" step="0.05" value="${S.W_ACTIVITY}">
          <label>${t("weight_match")}: <span id="wmVal">${S.W_MATCH.toFixed(2)}</span></label>
          <input type="range" id="wmSlider" min="0" max="1" step="0.05" value="${S.W_MATCH}">
          <span class="hint">${t("weight_sum")}: ${(S.W_ACTIVITY + S.W_MATCH).toFixed(2)}</span>
        </div>` : ""}
    </div>`;

  const noPosMsg = positions.length === 0 ? '<div class="card soft" style="margin:12px 0"><div class="label">提示</div><p>请先到「岗位管理」设定招聘岗位。</p><a class="btn blue" href="#/positions" style="display:inline-block;text-decoration:none;margin-top:8px">去设定岗位</a></div>' : '';
  const rows = items.length ? items.map((it, idx) => rowHTML(it, idx === 0)).join("") : `<div class="empty">${t("empty_reco")}</div>`;

  view().innerHTML = `
    <header class="mast">
      <div><div class="kicker">${t("kicker")} / ${esc(S.CURRENT_POSITION)}</div><h1>${t("heroTitle")}</h1></div>
      <div class="run"><b>${new Date().toLocaleTimeString(getLocale(), { hour: "2-digit", minute: "2-digit" })}</b></div>
    </header>
    ${banner}
    <nav class="positions" aria-label="${t("aria_switch_pos")}">${chips}</nav>
    ${sortBtns}
    <button class="btn ghost" id="recomputeBtn">${t("recompute_btn")}</button>
    ${followed.length > 0 ? '<details class="followed-section" open><summary class="followed-summary">' + t("fav_section") + ' <span class="badge">' + followed.length + '</span></summary><div class="followed-grid">' + followed.map((tp) => '<div class="followed-card" data-id="' + tp.id + '"><div class="fc-name">' + esc(tp.name) + '</div><div class="fc-meta">' + esc(tp.company || "") + " · " + esc(tp.position || "") + '</div></div>').join("") + '</div></details>' : '<div class="followed-section empty-sec"><span class="hint">' + t("fav_empty") + '</span></div>'}
    ${sectionCards(reco, items)}
    <div class="board">${rows}</div>`;

  // 事件绑定
  view().querySelectorAll(".chip[data-pos]").forEach((c) => c.addEventListener("click", () => {
    if (S.CURRENT_POSITION === c.dataset.pos) return;
    S.CURRENT_POSITION = c.dataset.pos; renderHome();
  }));
  view().querySelectorAll(".sort-btn").forEach((btn) => btn.addEventListener("click", () => {
    S.SORT_BY = btn.dataset.sort;
    renderHome();
  }));
  const waSlider = view().querySelector("#waSlider");
  if (waSlider) {
    waSlider.addEventListener("input", (e) => {
      S.W_ACTIVITY = parseFloat(e.target.value);
      S.W_MATCH = 1 - S.W_ACTIVITY;
      view().querySelector("#waVal").textContent = S.W_ACTIVITY.toFixed(2);
      view().querySelector("#wmVal").textContent = S.W_MATCH.toFixed(2);
    });
    waSlider.addEventListener("change", () => renderHome());
  }
  const recomputeBtn = view().querySelector("#recomputeBtn");
  if (recomputeBtn) {
    recomputeBtn.addEventListener("click", async () => {
      recomputeBtn.disabled = true;
      recomputeBtn.textContent = t("loading") + "…";
      const reco = await api.recompute(S.CURRENT_POSITION, S.SORT_BY,
        S.SORT_BY === "custom" ? S.W_ACTIVITY : undefined,
        S.SORT_BY === "custom" ? S.W_MATCH : undefined);
      renderHomeView(positions, reco);
    });
  }
  wireRows();
  view().querySelectorAll(".followed-card").forEach((el) => el.addEventListener("click", () => { location.hash = `#/talent/${el.dataset.id}`; }));
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
  view().querySelectorAll(".actions").forEach((group) => {
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
        try {
          await api.feedback({ talent_id: tid, action });
        } catch (err) {
          toast(err.message || t("loading") + "失败");
          return;
        }
        btn.dataset.state = "done";
        status.textContent = action === "fav" ? t("watch_added") : "";
        toast(action === "fav" ? t("watch_added") : t("watch_remove"));
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

      try {
        await api.feedback({ talent_id: tid, action });
      } catch (err) {
        toast(err.message || t("loading") + "失败");
        return;
      }
      group.querySelectorAll(".act").forEach((b) => (b.dataset.state = ""));
      btn.dataset.state = "done";
      status.textContent = action === "confirm" ? t("done_contact") : action === "reject" ? t("done_skip") : t("done_correct");
    });
  });
}
