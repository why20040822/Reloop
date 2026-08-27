// 飞书扫码登录弹窗 + 登录回调(不改动逻辑)
import { api, setAuth, isAuthed } from "../../data/provider.js";
import { t } from "../state.js";
import { esc, view } from "../utils/dom.js";
import { renderTabs, router } from "../router.js";

let _loginPollTimer = null;

export async function openLoginModal() {
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

export function closeModal() {
  document.getElementById("loginOverlay")?.remove();
  clearInterval(_loginPollTimer);
}

export async function handleAuthCallback() {
  const hash = location.hash || "";
  const q = hash.includes("?") ? hash.slice(hash.indexOf("?") + 1) : "";
  const code = new URLSearchParams(q).get("code") || new URLSearchParams(location.search).get("code");
  view().innerHTML = `<div class="spinner">${code ? t("logging_in") : t("auth_cb_err")}…</div>`;
  if (!code) { setTimeout(() => { location.hash = "#/"; }, 1500); return; }
  try {
    const r = await api.feishuLogin(code);
    setAuth(r);
    renderTabs();
    view().innerHTML = `
      <header class="mast"><div><div class="kicker">${t("kicker")}</div><h1>${t("login_success")}</h1></div></header>
      <div class="card soft"><div class="hint">${t("logged_as")}: <b>${esc(r.user?.display_name || "")}</b></div>
      <a class="btn blue" style="display:inline-block;text-align:center;text-decoration:none" href="#/">${t("login_back")}</a></div>`;
    setTimeout(() => { try { window.close(); } catch (e) {} }, 2000);
  } catch (e) {
    const msg = code ? t("login_failed") : t("auth_cb_err");
    view().innerHTML = `<div class="empty">${esc(msg)}<br><button class="btn" onclick="location.hash='#/'">${t("back")}</button></div>`;
  }
}
