// Talents / 人才库
import { api } from "../../data/provider.js";
import { t } from "../state.js";
import { esc, view, loading } from "../utils/dom.js";

export async function renderTalents(keyword = "") {
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

    view().innerHTML = `
      <header class="mast"><div><div class="kicker">${t("kicker")}</div><h1>${t("talent_pool")}</h1></div></header>
      <div class="searchbar"><div class="field"><input id="kw" placeholder="${t("search_ph")}" value="${esc(keyword)}"></div><button class="btn blue" id="searchBtn">${t("search_btn")}</button></div>
      <div class="tlist">${rows}</div>`;

    view().querySelector("#searchBtn").addEventListener("click", () => renderTalents(view().querySelector("#kw").value.trim()));
    view().querySelector("#kw").addEventListener("keydown", (e) => { if (e.key === "Enter") renderTalents(e.target.value.trim()); });
    view().querySelectorAll(".titem").forEach((el) => el.addEventListener("click", () => { location.hash = `#/talent/${el.dataset.id}`; }));
  } catch (e) {
    view().innerHTML = `<div class="empty">${esc(e.message || t("loading") + "失败")}</div>`;
  }
}
