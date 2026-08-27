import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, Navigate, Route, Routes, useLocation, useNavigate, useParams } from "react-router-dom";
import {
  ArrowUpRight, BriefcaseBusiness, ChevronDown, ChevronRight, CircleHelp, Database, Heart, House,
  LogIn, Menu, Plus, Search, Settings, UsersRound, X,
} from "lucide-react";
import { DirectGlassSegment } from "./components/DirectGlassSegment";
import { JDParserDrawer, type JDParserDrawerStatus } from "./components/JDParserDrawer";
import { api, AUTH_CHANGE_EVENT, config, type CurrentUser, type Interaction, type JDAnalysis, type Position, type Recommendation, type SyncStatus, type Talent } from "./lib/api";
import { positionHasParsedJd } from "./lib/jd";
import { saveThenRefreshPosition } from "./lib/positionSave";
import { readSidebarCollapsed, writeSidebarCollapsed } from "./lib/sidebar";
import { scrubTtcCallbackHash } from "./lib/ttcCallback";
import { buildActivityRows, buildMatchRows, relativeActivity } from "./lib/dashboard";

const navItems = [
  { to: "/", label: "总览", icon: House, end: true },
  { to: "/talents", label: "人才库", icon: UsersRound },
  { to: "/positions", label: "岗位管理", icon: BriefcaseBusiness },
  { to: "/talents?filter=followed", label: "特别关注", icon: Heart },
];

function App() {
  return <Routes>
    <Route path="/auth/callback" element={<AuthCallback />} />
    <Route path="/ttc/connect" element={<TtcConnect />} />
    <Route path="/ttc/callback" element={<TtcCallback />} />
    <Route path="*" element={<Workbench />} />
  </Routes>;
}

function AuthCallback() {
  const location = useLocation();
  const navigate = useNavigate();
  const [message, setMessage] = useState("正在完成飞书登录…");
  useEffect(() => {
    const code = new URLSearchParams(location.search).get("code");
    if (!code) { setMessage("缺少飞书授权码，请返回设置页重新登录。"); return; }
    void api.feishuLogin(code)
      .then((auth) => { config.setAuth(auth); navigate("/ttc/connect", { replace: true }); })
      .catch((error: unknown) => setMessage(errorMessage(error)));
  }, [location.search, navigate]);
  return <CallbackScreen title="飞书登录" message={message} />;
}

function TtcConnect() {
  // 官方授权页对回调域名有白名单(TTC 前端硬编码), 未收录域名会在其页面报「授权失败」。
  // 因此不自动跳转: 默认主推零复制粘贴的扫码绑定; 官方页作为已收录域名的备选。
  const [mode, setMode] = useState<"choose" | "auto">("choose");
  const navigate = useNavigate();
  if (mode === "auto") return <TtcAutoConnect />;
  return <CallbackScreen title="连接你的人才库" message={"飞书扫码即可自动完成绑定与同步，无需复制粘贴。"} action={<div className="button-row">
    <button className="primary-button" onClick={() => setMode("auto")}>扫码绑定（推荐）</button>
    <button className="secondary-button" onClick={() => { void api.ttcLoginUrl().then(({ url }) => window.location.assign(url)).catch(() => setMode("auto")); }}>使用官方授权页</button>
    <button className="secondary-button" onClick={() => navigate("/settings")}>返回设置</button>
  </div>} />;
}

// 备用通道: 一键扫码绑定(零复制粘贴)——服务器无头浏览器打开 TTC 登录页,
// 这里轮询展示二维码截图; 用户手机飞书扫码后自动抓 Token/绑定/同步。
function TtcAutoConnect() {
  const navigate = useNavigate();
  const [qr, setQr] = useState("");
  const [status, setStatus] = useState("starting");
  const [message, setMessage] = useState("正在启动扫码绑定…");
  useEffect(() => {
    let stopped = false;
    let timer = 0;
    const run = async () => {
      try {
        const { sid } = await api.ttcAutoLogin();
        const poll = async () => {
          if (stopped) return;
          try {
            const s = await api.ttcAutoLoginStatus(sid);
            if (stopped) return;
            setStatus(s.status);
            if (s.qr_png_b64) setQr(s.qr_png_b64);
            if (s.status === "success") {
              setMessage(`已连接${s.bound_name ? `：${s.bound_name}` : ""}，正在后台同步你的人才库。`);
              setTimeout(() => navigate("/settings", { replace: true }), 1400);
              return;
            }
            if (s.status === "pending") {
              setMessage("请用飞书扫描下方二维码完成授权");
              timer = window.setTimeout(() => void poll(), 1500);
              return;
            }
            setMessage(s.error || "绑定未完成，请重试。");
          } catch (error) { if (!stopped) { setStatus("failed"); setMessage(errorMessage(error)); } }
        };
        await poll();
      } catch (error) { setStatus("failed"); setMessage(errorMessage(error)); }
    };
    void run();
    return () => { stopped = true; window.clearTimeout(timer); };
  }, [navigate]);
  return <main className="callback-screen"><div>
    <span className="brand-mark"><img className="brand-logo" src="/reloop-logo.png" alt="" /></span>
    <h1>扫码绑定人才库</h1>
    <p>{message}</p>
    {status === "pending" && qr ? <img className="ttc-qr" src={`data:image/png;base64,${qr}`} alt="TTC 登录二维码" /> : null}
    <div className="button-row">
      {(status === "failed" || status === "timeout" || status === "expired") && <button className="primary-button" onClick={() => window.location.reload()}>重新发起</button>}
      <button className="secondary-button" onClick={() => navigate("/settings")}>返回设置</button>
    </div>
  </div></main>;
}

function TtcCallback() {
  const location = useLocation();
  const navigate = useNavigate();
  const [message, setMessage] = useState("正在自动绑定并同步你的人才库…");
  useEffect(() => {
    const token = new URLSearchParams(location.search).get("token");
    history.replaceState(null, "", scrubTtcCallbackHash(window.location.pathname, window.location.hash));
    if (!token) { setMessage("未收到 TTC 登录凭证，请重新连接人才库。"); return; }
    let stopped = false;
    const bind = async () => {
      try {
        const result = await api.bindTtc(token);
        const poll = async () => {
          const status = await api.syncStatus(result.sync_id);
          if (stopped) return;
          if (status.status === "running") {
            setMessage(`正在同步人才库：${status.current || status.processed || 0}/${status.total || "…"}`);
            setTimeout(() => void poll(), 1500);
            return;
          }
          if (status.status === "done") {
            setMessage(`人才库已自动连接并同步 ${status.synced || status.current || 0} 位人才。`);
            setTimeout(() => navigate("/settings", { replace: true }), 900);
            return;
          }
          setMessage(status.error || status.message || "同步未完成，请在设置中重试。");
        };
        await poll();
      } catch (error) { if (!stopped) setMessage(errorMessage(error)); }
    };
    void bind();
    return () => { stopped = true; };
  }, [location.search, navigate]);
  return <CallbackScreen title="正在连接人才库" message={message} />;
}

function CallbackScreen({ title, message, action }: { title: string; message: string; action?: ReactNode }) {
  return <main className="callback-screen"><div><span className="brand-mark"><img className="brand-logo" src="/reloop-logo.png" alt="" /></span><h1>{title}</h1><p>{message}</p>{action}</div></main>;
}

function Workbench() {
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

function PageHeading({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return <header className="page-heading"><div><h1>{title}</h1>{description && <p>{description}</p>}</div>{action && <div className="page-heading-action">{action}</div>}</header>;
}

type DashboardMode = "activity" | "match";
function Dashboard() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<DashboardMode>("activity");
  const [positions, setPositions] = useState<Position[]>([]);
  const [selectedPosition, setSelectedPosition] = useState("");
  const [talents, setTalents] = useState<Talent[]>([]);
  const [matches, setMatches] = useState<Recommendation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerStatus, setDrawerStatus] = useState<JDParserDrawerStatus>("input");
  const [drawerRawJd, setDrawerRawJd] = useState("");
  const [drawerAnalysis, setDrawerAnalysis] = useState<JDAnalysis | null>(null);
  const [drawerError, setDrawerError] = useState("");
  const [refreshWarning, setRefreshWarning] = useState("");
  const matchSegmentRef = useRef<HTMLDivElement | null>(null);
  const drawerReturnTarget = useRef<HTMLElement | null>(null);
  const drawerReturnFallback = useRef<HTMLElement | null>(null);

  useEffect(() => { void (async () => { try { const [people, roles] = await Promise.all([api.listTalents(), api.listPositions()]); setTalents(people); setPositions(roles); setSelectedPosition((value) => value || roles[0]?.position_name || ""); } catch (reason) { setError(errorMessage(reason)); } finally { setLoading(false); } })(); }, []);
  useEffect(() => {
    if (mode !== "match" || !selectedPosition) return;
    let active = true;
    const load = async () => {
      setLoading(true); setError("");
      try {
        const first = await api.recommend(selectedPosition, "match");
        if (!active) return;
        setMatches(first.top_n || []);
        if (first.computing || first.phase === "preview") {
          const poll = async () => {
            const next = await api.recommendationResult(selectedPosition, "match");
            if (!active) return;
            if (next.status === "done") setMatches(next.top_n || []);
            else if (next.status === "running") setTimeout(() => void poll(), 1800);
          };
          setTimeout(() => void poll(), 1800);
        }
      } catch (reason) { if (active) setError(errorMessage(reason)); }
      finally { if (active) setLoading(false); }
    };
    void load();
    return () => { active = false; };
  }, [mode, selectedPosition]);

  const selected = positions.find((position) => position.position_name === selectedPosition);
  const openParser = (position?: Position, opener?: HTMLElement | null) => {
    drawerReturnTarget.current = opener || (document.activeElement instanceof HTMLElement ? document.activeElement : null);
    drawerReturnFallback.current = matchSegmentRef.current?.querySelector<HTMLElement>("[data-segment-value='match']") || null;
    setDrawerRawJd(position?.jd_text || "");
    setDrawerAnalysis(null);
    setDrawerError("");
    setRefreshWarning("");
    setDrawerStatus("input");
    setDrawerOpen(true);
  };
  const parseJd = async () => {
    setDrawerStatus("parsing");
    setDrawerError("");
    try {
      setDrawerAnalysis(await api.parseJd(drawerRawJd));
      setDrawerStatus("review");
    } catch (reason) {
      setDrawerError(errorMessage(reason));
      setDrawerStatus("input");
    }
  };
  const confirmJd = async (analysis: JDAnalysis) => {
    setDrawerStatus("saving");
    setDrawerError("");
    try {
      const result = await saveThenRefreshPosition(
        () => api.setPosition({ position_name: selected?.position_name || analysis.title, jd_text: drawerRawJd, jd_analysis: analysis }),
        () => api.listPositions(),
      );
      setPositions(result.positions || [result.position, ...positions.filter((position) => position.position_name !== result.position.position_name)]);
      setSelectedPosition(result.position.position_name);
      setRefreshWarning(result.refreshError ? "岗位已保存，但岗位列表未能刷新。已使用刚保存的岗位继续匹配。" : "");
      setDrawerOpen(false);
      setMode("match");
    } catch (reason) {
      setDrawerError(errorMessage(reason));
      setDrawerStatus("review");
    }
  };

  const rows = useMemo(() => mode === "match" ? buildMatchRows(matches, talents) : buildActivityRows(talents), [matches, mode, talents]);

  return <><div className="dashboard-page">
    <PageHeading title="今天最该联系谁" action={<DirectGlassSegment containerRef={matchSegmentRef} value={mode} options={[{ value: "activity", label: "活跃优先" }, { value: "match", label: "岗位匹配" }]} onChange={(value) => { const nextMode = value as DashboardMode; if (nextMode === "match" && !positionHasParsedJd(selected)) { openParser(selected); return; } setMode(nextMode); }} ariaLabel="选择人才展示方式" />} />
    {mode === "match" && <div className="match-controls"><label className="position-picker">当前岗位<span className="position-select"><select value={selectedPosition} disabled={positions.length === 0} onChange={(event) => { const nextPosition = positions.find((position) => position.position_name === event.target.value); if (!positionHasParsedJd(nextPosition)) { openParser(nextPosition, event.currentTarget); setSelectedPosition(event.target.value); setMode("activity"); return; } setSelectedPosition(event.target.value); }}>{positions.length === 0 && <option value="">暂无岗位</option>}{positions.map((position) => <option key={position.id} value={position.position_name}>{position.position_name}</option>)}</select><ChevronDown size={15} aria-hidden="true" /></span></label><button className="secondary-button" type="button" onClick={(event) => openParser(selected, event.currentTarget)}>解析新 JD</button></div>}
    {error && <Notice tone="error">{error}</Notice>}
    {refreshWarning && <Notice tone="info">{refreshWarning}</Notice>}
    <button className="talent-summary" type="button" onClick={() => navigate("/talents")}><span><small>{mode === "match" ? "岗位匹配候选" : "近 7 天活跃人才"}</small><strong>{rows.length}</strong></span><span>前往人才库 <ArrowUpRight size={16} /></span></button>
    <section className="talent-focus"><div className="section-heading"><h2>{mode === "match" ? `${selectedPosition || "岗位"}匹配人才` : "最近活跃人才"}</h2><button className="text-button" onClick={() => navigate("/talents")}>查看全部 <ChevronRight size={15} /></button></div>
      {loading ? <Loading /> : rows.length === 0 ? <Empty text="暂时没有可展示的人才。" /> : <div className="focus-list">{rows.map((row, index) => <button type="button" className="focus-row" key={row.talent.id} onClick={() => navigate(`/talent/${row.talent.id}`)}><span className="rank">{String(index + 1).padStart(2, "0")}</span><span className="focus-person"><Avatar person={row.talent} size="large" /><span><strong>{row.talent.name}</strong><small>{row.talent.base_location || "地点待补充"}</small></span></span><span className="focus-current"><small>当前经历</small><strong>{row.talent.company || "—"} · {row.talent.position || "—"}</strong></span><span className="focus-experience"><small>工作经历</small><strong>{row.talent.work_years ? `${row.talent.work_years} 年 · ${row.talent.company || "—"}` : "待补充"}</strong></span><span className="focus-education"><small>毕业院校</small><strong>{row.talent.education || "待补充"}</strong></span><span className="focus-signal"><small>最新动态</small><strong>{row.reason}</strong></span><span className="focus-score"><strong>{row.score == null ? "—" : Math.round(row.score * 100)}</strong><small>{mode === "match" ? "匹配分" : "价值分"}</small></span><span className="focus-activity"><small>最近活跃</small><strong>{relativeActivity(row.activeAt)}</strong></span><ChevronRight size={16} /></button>)}</div>}
    </section>
  </div><JDParserDrawer open={drawerOpen} rawJd={drawerRawJd} status={drawerStatus} analysis={drawerAnalysis} error={drawerError} returnFocusTarget={drawerReturnTarget.current} returnFocusFallback={drawerReturnFallback.current} onRawJdChange={(value) => { setDrawerRawJd(value); setDrawerError(""); }} onParse={() => void parseJd()} onConfirm={(analysis) => void confirmJd(analysis)} onReset={() => { setDrawerStatus("input"); setDrawerAnalysis(null); setDrawerError(""); }} onClose={() => setDrawerOpen(false)} /></>;
}

function TalentList() {
  const location = useLocation();
  const navigate = useNavigate();
  const followed = new URLSearchParams(location.search).get("filter") === "followed";
  const [keyword, setKeyword] = useState("");
  const [talents, setTalents] = useState<Talent[]>([]);
  const [error, setError] = useState("");
  const load = async (next = keyword) => { try { setError(""); setTalents(followed ? await api.listFollowed() : await api.listTalents(next)); } catch (reason) { setError(errorMessage(reason)); } };
  useEffect(() => { void load(""); }, [followed]);
  return <div><PageHeading title={followed ? "特别关注" : "人才库"} />{error && <Notice tone="error">{error}</Notice>}
    {!followed && <form className="search-field" onSubmit={(event) => { event.preventDefault(); void load(); }}><Search size={17} /><input value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="搜索人才、公司或职位" /><button className="primary-button">搜索</button></form>}
    <div className="talent-table"><div className="talent-table-head"><span>人才</span><span>当前经历</span><span>核心技能</span><span>价值分</span></div>{talents.map((talent) => <button type="button" className="talent-row" key={talent.id} onClick={() => navigate(`/talent/${talent.id}`)}><span className="person-cell"><Avatar person={talent} /><span><strong>{talent.name}</strong><small>{talent.base_location || "—"} · {talent.work_years || "—"} 年</small></span></span><span>{talent.company || "—"}<small>{talent.position || ""}</small></span><span className="tag-list">{(talent.skills || []).slice(0, 3).map((skill) => <i key={skill}>{skill}</i>)}</span><strong>{number(talent.value_score)}</strong></button>)}{!talents.length && <Empty text="没有找到符合条件的人才。" />}</div>
  </div>;
}

function TalentDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [talent, setTalent] = useState<Talent | null>(null);
  const [interactions, setInteractions] = useState<Interaction[]>([]);
  const [summary, setSummary] = useState("");
  const [kind, setKind] = useState("call");
  const [error, setError] = useState("");
  const load = async () => { if (!id) return; try { const person = await api.getTalent(Number(id)); setTalent(person); setInteractions(await api.getInteractions(Number(id))); } catch (reason) { setError(errorMessage(reason)); } };
  useEffect(() => { void load(); }, [id]);
  if (!talent) return <Loading />;
  const isFollowed = talent.tags?.includes("已关注");
  return <div><button className="back-button" onClick={() => navigate("/talents")}>← 返回人才库</button><PageHeading title={talent.name} description={`${talent.company || "—"} · ${talent.position || "—"}`} action={<button className="secondary-button" onClick={async () => { await api.followTalent(talent.id); await load(); }}>{isFollowed ? "取消关注" : "特别关注"}</button>} />{error && <Notice tone="error">{error}</Notice>}
    <div className="detail-layout"><section className="profile-card"><div className="profile-header"><Avatar person={talent} size="xl" /><div><h2>{talent.name}</h2><p>{talent.base_location || "地点待补充"}</p></div></div><KeyValue label="工作年限" value={talent.work_years ? `${talent.work_years} 年` : "—"} /><KeyValue label="学历" value={talent.education} /><KeyValue label="核心技能" value={(talent.skills || []).join("、")} /><KeyValue label="备注" value={talent.notes} /></section>
      <section className="profile-card"><h2>互动记录</h2>{interactions.length ? interactions.map((item, index) => <div className="interaction-row" key={index}><i>{item.interaction_type}</i><span>{item.summary || "—"}</span><small>{new Date(item.occurred_at).toLocaleDateString()}</small></div>) : <Empty text="暂无互动记录" />}<form className="interaction-form" onSubmit={async (event) => { event.preventDefault(); if (!summary.trim()) return; await api.addInteraction(talent.id, { interaction_type: kind, summary }); setSummary(""); await load(); }}><select value={kind} onChange={(event) => setKind(event.target.value)}><option value="call">电话</option><option value="message">消息</option><option value="interview">面试</option><option value="note">备注</option></select><input value={summary} onChange={(event) => setSummary(event.target.value)} placeholder="记录一次互动" /><button className="primary-button">保存</button></form></section></div>
  </div>;
}

function Positions() {
  const [positions, setPositions] = useState<Position[]>([]);
  const [name, setName] = useState("");
  const [jd, setJd] = useState("");
  const [message, setMessage] = useState("");
  const load = async () => setPositions(await api.listPositions());
  useEffect(() => { void load(); }, []);
  return <div><PageHeading title="岗位管理" /><div className="positions-layout"><section className="panel"><h2>已生效岗位</h2>{positions.length ? positions.map((position) => <article className="position-card" key={position.id}><div><strong>{position.position_name}</strong><p>{position.jd_text || "暂未填写 JD"}</p></div><button className="icon-button danger" aria-label={`删除 ${position.position_name}`} onClick={async () => { if (confirm(`删除「${position.position_name}」？`)) { await api.deletePosition(position.id); await load(); } }}><X size={16} /></button></article>) : <Empty text="还没有在招岗位。" />}</section>
    <form className="panel position-form" onSubmit={async (event) => { event.preventDefault(); if (!name.trim()) return; await api.setPosition({ position_name: name.trim(), jd_text: jd.trim() }); setName(""); setJd(""); setMessage("岗位已保存。"); await load(); }}><h2>新增或更新岗位</h2><label>岗位名称<input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：商业分析师" required /></label><label>职位描述（JD）<textarea value={jd} onChange={(event) => setJd(event.target.value)} placeholder="填写职责、目标和关键能力" /></label><button className="primary-button"><Plus size={16} />保存岗位</button>{message && <Notice tone="success">{message}</Notice>}</form></div>
  </div>;
}

function SettingsPage({ loginError, authRevision, onLogin, onConnect }: { loginError: string; authRevision: number; onLogin: () => void; onConnect: () => void }) {
  const [cfg, setCfg] = useState(config.read());
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [sync, setSync] = useState<SyncStatus | null>(null);
  const [helpOpen, setHelpOpen] = useState(false);
  const [preferenceMessage, setPreferenceMessage] = useState("");
  const [advancedMessage, setAdvancedMessage] = useState("");
  const [syncError, setSyncError] = useState("");
  const refreshUser = async () => { if (!config.auth()) { setUser(null); return; } try { setUser(await api.me()); } catch { config.clearAuth(); setUser(null); } };
  useEffect(() => { void refreshUser(); }, [authRevision]);
  const startSync = async () => {
    try {
      setSyncError("");
      const result = await api.syncTtc();
      const poll = async () => { const next = await api.syncStatus(result.sync_id); setSync(next); if (next.status === "running") setTimeout(() => void poll(), 1500); };
      await poll();
    } catch (error) { setSyncError(errorMessage(error)); }
  };
  const savePreferences = () => {
    setCfg(config.write({ locale: cfg.locale }));
    setPreferenceMessage("偏好已保存。");
  };
  const saveAdvancedSettings = () => {
    setCfg(config.write({ mode: cfg.mode, apiBase: cfg.apiBase }));
    setAdvancedMessage("高级设置已保存。");
  };
  return <div className="settings-page">
    <PageHeading
      title="设置"
      description="管理账号、人才库与使用偏好。"
      action={<button className="settings-help-button" type="button" aria-label="查看使用帮助" aria-expanded={helpOpen} title="使用帮助" onClick={() => setHelpOpen((open) => !open)}><CircleHelp size={19} /></button>}
    />
    {helpOpen && <section className="settings-help" aria-label="使用帮助"><strong>使用帮助</strong><p>访客模式读取共享人才库；登录后会自动连接并同步你的私有人才库。</p><p>真实 API、样本数据与后端地址位于高级设置中，普通使用无需调整。</p></section>}
    <section className="settings-panel settings-account-panel"><h2>账户与人才库</h2>{loginError && <Notice tone="error">{loginError}</Notice>}{user ? <><p>已登录为 <strong>{user.display_name}</strong> · 人才池 {user.pool_count} 人</p><p>{user.ttc_connected ? `已连接：${user.ttc_bound_name || "你的 TTC 人才库"}` : "尚未连接你的 TTC 人才库"}</p><div className="button-row">{!user.ttc_connected && <button className="secondary-button" type="button" onClick={onConnect}>连接人才库</button>}<button className="primary-button" type="button" onClick={() => void startSync()}>同步人才库</button><button className="text-button" type="button" onClick={() => { config.clearAuth(); setUser(null); }}>退出登录</button></div></> : <><p>登录飞书后，系统会自动连接并同步你的私有人才库。</p><button className="primary-button" type="button" onClick={onLogin}><LogIn size={16} />登录飞书</button></>}{syncError && <Notice tone="error">{syncError}</Notice>}{sync && <Notice tone={sync.status === "failed" ? "error" : "info"}>同步状态：{sync.status}{sync.total ? ` · ${sync.current || sync.processed || 0}/${sync.total}` : ""}{sync.error ? ` · ${sync.error}` : ""}</Notice>}</section>
    <section className="settings-panel"><h2>使用偏好</h2><label>语言<select value={cfg.locale} onChange={(event) => { setCfg({ ...cfg, locale: event.target.value as "zh-CN" | "en-US" }); setPreferenceMessage(""); }}><option value="zh-CN">中文</option><option value="en-US">English</option></select></label><button className="primary-button settings-save-button" type="button" onClick={savePreferences}>保存偏好</button>{preferenceMessage && <Notice tone="success">{preferenceMessage}</Notice>}</section>
    <details className="advanced-settings"><summary><span className="advanced-settings-title"><Database size={18} /><span><strong>高级设置</strong><small>数据来源与后端连接</small></span></span><ChevronRight className="advanced-settings-chevron" size={17} /></summary><div className="advanced-settings-content"><div className="setting-group"><label>数据模式</label><DirectGlassSegment value={cfg.mode} options={[{ value: "live", label: "真实 API" }, { value: "mock", label: "样本数据" }]} onChange={(mode) => { setCfg({ ...cfg, mode: mode as "live" | "mock" }); setAdvancedMessage(""); }} ariaLabel="数据模式" /></div><label>后端地址（可选）<input value={cfg.apiBase} onChange={(event) => { setCfg({ ...cfg, apiBase: event.target.value }); setAdvancedMessage(""); }} placeholder="留空 = 同源后端" /></label><button className="primary-button settings-save-button" type="button" onClick={saveAdvancedSettings}>保存高级设置</button>{advancedMessage && <Notice tone="success">{advancedMessage}</Notice>}</div></details>
  </div>;
}

function Avatar({ person, size = "" }: { person: Talent; size?: "" | "large" | "xl" }) { return <span className={`avatar ${size}`}>{person.name.slice(0, 1)}</span>; }
function KeyValue({ label, value }: { label: string; value?: string | null }) { return <div className="key-value"><span>{label}</span><strong>{value || "—"}</strong></div>; }
function Notice({ tone, children }: { tone: "error" | "success" | "info"; children: ReactNode }) { return <p className={`notice ${tone}`}>{children}</p>; }
function Loading() { return <div className="loading">正在加载…</div>; }
function Empty({ text }: { text: string }) { return <div className="empty">{text}</div>; }
function number(value?: number | null) { return value == null ? "—" : value.toFixed(2); }
function errorMessage(error: unknown) { return error instanceof Error ? error.message : "请求未完成，请稍后重试。"; }
export default App;
