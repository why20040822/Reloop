// Positions / 岗位管理
import { api } from "../../data/provider.js";
import { S, t } from "../state.js";
import { esc, view, loading } from "../utils/dom.js";

export async function renderPositions() {
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

  view().innerHTML = `
    <header class="mast"><div><div class="kicker">${t("kicker")}</div><h1>${t("positions_title")}</h1></div></header>
    ${list}
    <div class="card"><div class="label">${t("set_position")}</div>
      <div class="field"><span class="hint">${t("pos_name")}</span><input id="pname" placeholder="${t("pos_name_ph")}"></div>
      <div class="field"><span class="hint">${t("pos_jd")}</span><textarea id="pjd" placeholder="${t("pos_jd_ph")}" rows="4"></textarea></div>
      <button class="btn blue" id="psubmit">${t("pos_submit")}</button>
    </div>`;

  view().querySelector("#psubmit").addEventListener("click", async () => {
    const name = view().querySelector("#pname").value.trim(); if (!name) return;
    await api.setPosition({ position_name: name, jd_text: view().querySelector("#pjd").value.trim() });
    S.CURRENT_POSITION = name; location.hash = "#/";
  });

  // 删除按钮
  view().querySelectorAll(".del-pos-btn").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!confirm(t("del_position_confirm"))) return;
      await api.deletePosition(Number(btn.dataset.id));
      if (S.CURRENT_POSITION === btn.dataset.name) S.CURRENT_POSITION = null;
      renderPositions();
    });
  });
}
