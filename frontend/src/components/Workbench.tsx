import { useEffect, useState } from "react";
import { Link, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { BriefcaseBusiness, Heart, House, Menu, Settings, UsersRound, X } from "lucide-react";
import { AUTH_CHANGE_EVENT, api, config } from "../lib/api";
import { readSidebarCollapsed, writeSidebarCollapsed } from "../lib/sidebar";
import { errorMessage } from "./ui";
import { AuthCallback, TtcCallback, TtcConnect } from "../pages/AuthFlows";
import { Dashboard } from "../pages/Dashboard";
import { TalentList } from "../pages/TalentList";
import { TalentDetail } from "../pages/TalentDetail";
import { Positions } from "../pages/Positions";
import { SettingsPage } from "../pages/Settings";

const navItems = [
  { to: "/", label: "总览", icon: House, end: true },
  { to: "/talents", label: "人才库", icon: UsersRound },
  { to: "/positions", label: "岗位管理", icon: BriefcaseBusiness },
  { to: "/talents?filter=followed", label: "特别关注", icon: Heart },
];

export default function Workbench() {
  const location = useLocation();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(readSidebarCollapsed);
  const [loginError, setLoginError] = useState("");
  const [authTick, setAuthTick] = useState(0);
  const isSettings = location.pathname === "/settings";
  const closeMenu = () => setMenuOpen(false);

  useEffect(() => { closeMenu(); }, [location.pathname, location.search]);
  useEffect(() => {
    const onKeydown = (event: KeyboardEvent) => { if (event.key === "Escape") closeMenu(); };
    window.addEventListener("keydown", onKeydown);
    return () => window.removeEventListener("keydown", onKeydown);
  }, []);
  useEffect(() => {
    const onAuthChange = () => setAuthTick((tick) => tick + 1);
    window.addEventListener(AUTH_CHANGE_EVENT, onAuthChange);
    return () => window.removeEventListener(AUTH_CHANGE_EVENT, onAuthChange);
  }, []);

  const startFeishuLogin = async () => {
    setLoginError("");
    try { window.location.assign((await api.feishuLoginUrl()).url); }
    catch (error) { setLoginError(errorMessage(error)); navigate("/settings"); }
  };
  const startTtcLogin = () => navigate("/ttc/connect");
  const toggleSidebar = () => setSidebarCollapsed((collapsed) => {
    const next = !collapsed;
    writeSidebarCollapsed(next);
    return next;
  });

  return <div className={`app-shell ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
    <button className="mobile-menu-button" type="button" aria-label="打开菜单" onClick={() => setMenuOpen(true)}><Menu size={20} /></button>
    <button className={`sidebar-backdrop ${menuOpen ? "show" : ""}`} type="button" aria-label="关闭菜单" onClick={closeMenu} />
    <aside className={`sidebar ${menuOpen ? "mobile-open" : ""}`}>
      <div className="sidebar-head">
        <button className="sidebar-collapse-button brand-mark" type="button" aria-label={sidebarCollapsed ? "展开侧边栏" : "收起侧边栏"} aria-pressed={sidebarCollapsed} title={sidebarCollapsed ? "展开侧边栏" : "收起侧边栏"} onClick={toggleSidebar}><img className="brand-logo" src="/reloop-logo.png" alt="" /></button>
        <Link className="brand-wordmark" to="/"><strong>RE:LOOP</strong></Link>
        <Link className="brand mobile-brand" to="/"><span className="brand-mark"><img className="brand-logo" src="/reloop-logo.png" alt="" /></span><strong>RE:LOOP</strong></Link>
        <button className="mobile-close" type="button" aria-label="关闭菜单" onClick={closeMenu}><X size={18} /></button>
      </div>
      <nav className="main-nav" aria-label="主导航">
        {navItems.map(({ to, label, icon: Icon }) => {
          const followed = to.includes("followed");
          const talentFilter = new URLSearchParams(location.search).get("filter");
          const active = followed
            ? location.pathname === "/talents" && talentFilter === "followed"
            : to === "/talents"
              ? location.pathname === "/talents" && talentFilter !== "followed"
              : to === "/" ? location.pathname === "/" : location.pathname.startsWith(to);
          return <Link key={to} to={to} className={`nav-item ${active ? "active" : ""}`} title={sidebarCollapsed ? label : undefined} onClick={closeMenu}><Icon size={18} /><span>{label}</span></Link>;
        })}
      </nav>
      <div className="sidebar-spacer" />
      <div className="sidebar-footer">
        <Link className={`settings-trigger ${isSettings ? "active" : ""}`} to="/settings" title={sidebarCollapsed ? "设置" : undefined} onClick={closeMenu}><Settings size={17} /><span>设置</span></Link>
      </div>
    </aside>
    <main className="main-stage">
      <section className="page-content">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/talents" element={<TalentList />} />
          <Route path="/talent/:id" element={<TalentDetail />} />
          <Route path="/positions" element={<Positions />} />
          <Route path="/settings" element={<SettingsPage loginError={loginError} authRevision={authTick} onLogin={startFeishuLogin} onConnect={startTtcLogin} />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </section>
    </main>
  </div>;
}
