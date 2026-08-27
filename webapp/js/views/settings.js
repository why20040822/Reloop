// Settings / 设置(数据源 / 账号 / 同步)
import { api, getCfg, setCfg, getAuth, clearAuth, isAuthed, useMock } from "../../data/provider.js";
import { t, getLocale, setLocale } from "../state.js";
import { esc, view } from "../utils/dom.js";
import { openLoginModal } from "./auth.js";
import { renderTabs } from "../router.js";
import { toast } from "../components/toast.js";

export async function renderSettings() {
  const cfg = getCfg();
  let meInfo = null;
  if (!useMock() && isAuthed()) {
    try { meInfo = await api.me(); } catch (e) { /* auth preserved, no clearAuth */ }
  }
  view().innerHTML = `
    <header class="mast"><div><div class="kicker">${t("kicker")}</div><h1>${t("settings_title")}</h1></div>
      <div class="run"><b>${useMock() ? t("mode_mock") : t("mode_api")}</b></div></header>
    <div class="card"><div class="label">${t("data_source")}</div>
      <div class="api"><code>MODE=${useMock() ? "mock" : (cfg.apiBase || "同源")}</code><span class="badge ${useMock() ? "mut" : ""}">${useMock() ? "SAMPLE" : "LIVE"}</span></div>
      <div class="field"><span class="hint">${t("mode_label")}</span>
        <div class="seg"><button data-mode="live" class="${cfg.mode !== "mock" ? "on" : ""}">${t("ds_api")}</button><button data-mode="mock" class="${cfg.mode === "mock" ? "on" : ""}">${t("ds_mock")}</button></div></div>
      <div class="field"><span class="hint">${t("api_base")}</span><input id="apiBase" placeholder="${t("api_base_ph")}" value="${esc(cfg.apiBase)}"></div>
      <div class="field"><span class="hint">${t("language")}</span>
        <div class="seg"><button data-loc="zh-CN" class="${getLocale() === "zh-CN" ? "on" : ""}">中文</button><button data-loc="en-US" class="${getLocale() === "en-US" ? "on" : ""}">EN</button></div></div>
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

  view().querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", () => {
    if (b.dataset.loc) { setLocale(b.dataset.loc); renderSettings(); renderTabs(); }
    if (b.dataset.mode) { setCfg({ mode: b.dataset.mode }); renderSettings(); }
  }));
  view().querySelector("#saveCfg").addEventListener("click", () => {
    setCfg({ apiBase: view().querySelector("#apiBase").value.trim(), locale: getLocale() });
    view().querySelector("#savedLine").textContent = t("saved");
    toast(t("saved"));
  });
  const loginBtn = view().querySelector("#loginBtn");
  if (loginBtn) loginBtn.addEventListener("click", openLoginModal);
  const logoutBtn = view().querySelector("#logout");
  if (logoutBtn) logoutBtn.addEventListener("click", () => { clearAuth(); renderSettings(); renderTabs(); });

  // 同步按钮
  const syncBtn = view().querySelector("#syncBtn");
  if (syncBtn) {
    syncBtn.addEventListener("click", async () => {
      syncBtn.disabled = true;
      syncBtn.textContent = t("ttc_syncing");
      try {
        const r = await api.syncTTC();
        const pollProgress = async () => {
          const progEl = view().querySelector("#syncProgress");
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
