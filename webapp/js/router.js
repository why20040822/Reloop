// Router + Tabs(底部 tab 栏 / 侧边栏登录态)
import { api, getAuth, isAuthed, useMock } from "../data/provider.js";
import { t } from "./state.js";
import { esc } from "./utils/dom.js";
import { renderHome } from "./views/home.js";
import { renderTalents } from "./views/talents.js";
import { renderFollowed } from "./views/followed.js";
import { renderTalentDetail } from "./views/talentDetail.js";
import { renderPositions } from "./views/positions.js";
import { renderSettings } from "./views/settings.js";
import { openLoginModal, closeModal, handleAuthCallback } from "./views/auth.js";
import { setActiveNav } from "./components/sidebar.js";

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

export function renderTabs() {
  const tabsEl = document.getElementById("tabs");
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

export function router() {
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
  setActiveNav(h);
}
