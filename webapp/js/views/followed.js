// 特别关注人选
import { api } from "../../data/provider.js";
import { t } from "../state.js";
import { esc, view, loading } from "../utils/dom.js";

export async function renderFollowed() {
  loading();
  const list = await api.listTalents();
  const followed = list.filter((tp) => (tp.tags || []).includes("已关注"));
  const rows = followed.length ? followed.map((tp) => `
    <div class="titem" data-id="${tp.id}">
      <div><div class="name-line"><span class="name">${esc(tp.name)} <span class="fav-star">★</span></span><span class="base">${esc(tp.base_location || "")}</span></div>
      <div class="meta">${esc(tp.company || "")} · ${esc(tp.position || "")}</div></div>
    </div>`).join("") : `<div class="empty">${t("fav_empty")}</div>`;

  view().innerHTML = `
    <header class="mast"><div><div class="kicker">${t("kicker")}</div><h1>${t("fav_section")}</h1></div></header>
    <div class="tlist">${rows}</div>`;

  view().querySelectorAll(".titem").forEach((el) => el.addEventListener("click", () => { location.hash = `#/talent/${el.dataset.id}`; }));
  // 更新侧边栏计数
  const badge = document.getElementById("followedCount");
  if (badge) badge.textContent = String(followed.length);
}
