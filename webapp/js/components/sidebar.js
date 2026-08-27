// 侧边栏(对应 shadcn app-sidebar.tsx: 组合 nav-main / nav-workspace / nav-secondary / nav-user)
// - nav-main      主菜单: 总览/人才库/岗位管理
// - nav-workspace 工作空间: 特别关注/数据连接
// - nav-secondary 底部: 主题/帮助/登录
// - nav-user      profile-mini(登录态由 router.updateSidebarAuth 驱动)
// 本模块负责: 交互事件 + 路由联动高亮(active); DOM 在 index.html
import { toast } from "./toast.js";
import { openLoginModal } from "../views/auth.js";

// 路由 → 侧边栏 nav 高亮(data-nav 值)
const NAV_BY_BASE = {
  "#/": "home",
  "#/talents": "talents",
  "#/talent": "talents",
  "#/positions": "positions",
  "#/settings": "settings",
};

export function setActiveNav(hash) {
  const h = hash || "#/";
  if (h.includes("filter=followed")) return markActive("followed");
  const base = "#/" + (h.split("/")[1] || "");
  markActive(NAV_BY_BASE[base] || "home");
}

function markActive(navKey) {
  document.querySelectorAll(".nav-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.nav === navKey);
  });
}

export function initSidebar() {
  const sidebar = document.getElementById("sidebar");
  const backdrop = document.getElementById("sidebarBackdrop");
  const mobileBtn = document.getElementById("mobileMenuBtn");
  const collapseBtn = document.getElementById("sidebarCollapseBtn");

  if (mobileBtn) mobileBtn.addEventListener("click", () => { sidebar.classList.toggle("open"); backdrop.classList.toggle("show"); });
  if (backdrop) backdrop.addEventListener("click", () => { sidebar.classList.remove("open"); backdrop.classList.remove("show"); });
  if (collapseBtn) collapseBtn.addEventListener("click", () => { sidebar.classList.toggle("collapsed"); });

  // nav 点击后(移动端)收起抽屉
  document.querySelectorAll(".nav-item").forEach((el) => {
    el.addEventListener("click", () => { sidebar.classList.remove("open"); backdrop.classList.remove("show"); });
  });

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

  // 数据健康条 / 帮助(8/24 起就存在的 DOM, 此前未接线)
  const healthBar = document.getElementById("dataHealthBar");
  if (healthBar) healthBar.addEventListener("click", () => toast("数据状态良好"));
  const helpBtn = document.getElementById("helpBtn");
  if (helpBtn) helpBtn.addEventListener("click", () => toast("接口文档见 /docs · 使用说明见 README"));
}
