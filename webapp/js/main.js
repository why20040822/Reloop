// Reloop 触达工作台 — 入口(引导: 侧边栏/搜索初始化 + 路由启动)
// 信息架构参考 shadcn dashboard-01(无构建步骤, 原生 ES Modules 落地):
//   components/sidebar.js       app-sidebar(nav-main/nav-workspace/nav-secondary/nav-user)
//   components/search.js        Cmd+K 全局搜索(command palette)
//   components/toast.js         通知(sonner)
//   components/section-cards.js KPI 统计卡行(内容区第一屏)
//   components/factors.js       双因子条形图(对应 chart-area)
//   components/score.js         分数环
//   views/                      页面视图(对应 app/ 下各 page)
//   js/router.js                hash 路由 + tab 栏
//   js/state.js                 全局共享状态 + i18n
//   data/provider.js            API/配置/登录态数据层(对应 data.json/后端契约)
import { router } from "./router.js";
import { initSidebar } from "./components/sidebar.js";
import { initSearch } from "./components/search.js";

initSidebar();
initSearch();
window.addEventListener("hashchange", router);
router();
