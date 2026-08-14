"use client";

import Link from "next/link";
import Image from "next/image";
import { usePathname, useRouter } from "next/navigation";
import {
  ArrowDown,
  ArrowUpRight,
  Bell,
  BriefcaseBusiness,
  Building2,
  CalendarDays,
  ChartNoAxesCombined,
  Check,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Clock3,
  Command,
  Database,
  FileText,
  Filter,
  FolderOpen,
  FolderPlus,
  Grid2X2,
  Globe2,
  GraduationCap,
  History,
  ListFilter,
  LoaderCircle,
  Mail,
  MapPin,
  Menu,
  MessageCircle,
  Moon,
  MoreHorizontal,
  PanelLeftClose,
  PanelLeftOpen,
  Phone,
  Plus,
  RefreshCw,
  Search,
  Settings,
  ShieldCheck,
  Signal,
  SlidersHorizontal,
  Sparkles,
  Star,
  Sun,
  Tag,
  Target,
  TriangleAlert,
  TrendingUp,
  UserRound,
  UsersRound,
  WandSparkles,
  X,
  Zap,
} from "lucide-react";
import {
  type ComponentType,
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

type Icon = ComponentType<{ size?: number; strokeWidth?: number; className?: string }>;

export type Talent = {
  id: string;
  name: string;
  initials: string;
  age: number;
  company: string;
  role: string;
  experience: string;
  school: string;
  matchRole: string;
  score: number;
  updated: string;
  login: string;
  level: "S" | "A" | "B";
  city: string;
  industry: string;
  color: string;
  source?: "sample" | "reloop";
  phone?: string | null;
  email?: string | null;
  keywords?: string[];
  platform?: string | null;
  qualityScore?: number | null;
  reviewStatus?: string | null;
  collectedAt?: string | null;
};

type ReloopCandidate = {
  id: number;
  name?: string | null;
  phone?: string | null;
  email?: string | null;
  current_company?: string | null;
  current_role?: string | null;
  current_title?: string | null;
  current_location?: string | null;
  location?: string | null;
  explicit_age?: number | null;
  experience_years?: number | null;
  undergraduate_school?: string | null;
  score?: number | null;
  jd_score?: number | null;
  jd_recommendation?: string | null;
  recommendation?: string | null;
  collected_at?: string | null;
  updated_at?: string | null;
  experiences?: Array<{ company?: string; role?: string; period?: string }>;
  keywords?: string[];
  platform?: string | null;
  quality_score?: number | null;
  review_status?: string | null;
};

export const talents: Talent[] = [];

const navSections: { label?: string; items: { label: string; href: string; icon: Icon; badge?: string }[] }[] = [
  {
    items: [
      { label: "总览", href: "/", icon: Grid2X2 },
      { label: "人才库", href: "/talent", icon: UsersRound },
      { label: "AI 洞察", href: "/insights", icon: WandSparkles },
    ],
  },
  {
    label: "工作空间",
    items: [
      { label: "特别关注人选", href: "/projects", icon: Star },
      { label: "数据连接", href: "/sources", icon: Database },
    ],
  },
];

const liveTalentColors = ["indigo", "cyan", "violet", "emerald", "amber", "rose"] as const;

function mapReloopCandidate(candidate: ReloopCandidate, index: number): Talent {
  const name = candidate.name?.trim() || "待识别候选人";
  const experience = candidate.experience_years
    ? `${candidate.experience_years} 年工作经历`
    : candidate.experiences?.[0]?.period
      ? `经历 ${candidate.experiences[0].period}`
      : "经历待补全";
  const score = Math.round(candidate.score ?? candidate.jd_score ?? 0);
  const firstExperience = candidate.experiences?.[0];
  const role = candidate.current_role || candidate.current_title || firstExperience?.role || "职位待核";
  const company = candidate.current_company || firstExperience?.company || "公司待核";

  return {
    id: `reloop-${candidate.id}`,
    name,
    initials: name.slice(0, 1),
    age: candidate.explicit_age || 0,
    company,
    role,
    experience,
    school: candidate.undergraduate_school || "学历待核",
    matchRole: candidate.jd_recommendation || candidate.recommendation || "待匹配",
    score,
    updated: candidate.updated_at || candidate.collected_at || "刚刚",
    login: candidate.platform || "云端精品库",
    level: score >= 90 ? "S" : score >= 75 ? "A" : "B",
    city: candidate.current_location || candidate.location || "城市待核",
    industry: "待分类",
    color: liveTalentColors[index % liveTalentColors.length],
    source: "reloop",
    phone: candidate.phone || null,
    email: candidate.email || null,
    keywords: Array.isArray(candidate.keywords) ? candidate.keywords : [],
    platform: candidate.platform || null,
    qualityScore: typeof candidate.quality_score === "number" ? candidate.quality_score : null,
    reviewStatus: candidate.review_status || null,
    collectedAt: candidate.collected_at || null,
  };
}

function mergeTalents(liveTalents: Talent[]): Talent[] {
  const liveIds = new Set(liveTalents.map((talent) => talent.id));
  return [...liveTalents, ...talents.filter((talent) => !liveIds.has(talent.id))];
}

function listTalents(liveTalents: Talent[]): Talent[] {
  // 列表页：云端精品库有数据时只展示真实人才；mock 仅作云端为空时的占位演示
  return liveTalents.length > 0 ? liveTalents : talents;
}

function useReloopTalents() {
  const [liveTalents, setLiveTalents] = useState<Talent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    fetch("/api/reloop/candidates", { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error("Reloop 后端未连接");
        const payload = await response.json();
        if (!Array.isArray(payload)) throw new Error("候选人数据格式异常");
        if (active) setLiveTalents(payload.map((item: ReloopCandidate, index: number) => mapReloopCandidate(item, index)));
      })
      .catch((cause: unknown) => {
        if (active) setError(cause instanceof Error ? cause.message : "Reloop 后端未连接");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  return { liveTalents, loading, error };
}

function Logo() {
  return (
    <div className="brand">
      <Image className="brand-mark" src="/reloop-logo.png" alt="RE:LOOP" width={25} height={25} priority unoptimized />
      <span className="brand-name">RE:LOOP</span>
      <span className="brand-beta">BETA</span>
    </div>
  );
}

function Avatar({
  talent,
  size = "md",
  online = false,
}: {
  talent: Talent;
  size?: "sm" | "md" | "lg" | "xl";
  online?: boolean;
}) {
  return (
    <span className={`avatar avatar-${size} avatar-${talent.color}`} aria-hidden="true">
      {talent.initials}
      {online && <i className="online-dot" />}
    </span>
  );
}

function useTheme() {
  const [dark, setDark] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const saved = window.localStorage.getItem("link-hub-theme");
      const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      setDark(saved ? saved === "dark" : prefersDark);
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    window.localStorage.setItem("link-hub-theme", dark ? "dark" : "light");
  }, [dark]);

  return { dark, setDark };
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { dark, setDark } = useTheme();
  const { liveTalents } = useReloopTalents();
  const [mobileNav, setMobileNav] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [toast, setToast] = useState("");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const allTalents = useMemo(() => mergeTalents(liveTalents), [liveTalents]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSidebarCollapsed(window.localStorage.getItem("reloop-sidebar-collapsed") === "true");
      window.localStorage.removeItem("reloop-sidebar-width");
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    window.localStorage.setItem("reloop-sidebar-collapsed", String(sidebarCollapsed));
  }, [sidebarCollapsed]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setSearchOpen(true);
      }
      if (event.key === "Escape") setSearchOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timeout = window.setTimeout(() => setToast(""), 2600);
    return () => window.clearTimeout(timeout);
  }, [toast]);

  const searchResults = useMemo(() => {
    if (!query.trim()) return allTalents.slice(0, 4);
    const normalized = query.toLowerCase();
    return allTalents.filter((talent) =>
      [talent.name, talent.company, talent.role, talent.matchRole]
        .join(" ")
        .toLowerCase()
        .includes(normalized),
    );
  }, [allTalents, query]);

  const sectionTitle = pathname.startsWith("/insights")
    ? "AI 洞察"
    : pathname.startsWith("/projects")
      ? "特别关注人选"
    : pathname.startsWith("/jobs")
      ? "职位"
    : pathname.startsWith("/sources")
      ? "数据连接"
    : pathname.startsWith("/talent/")
      ? "人才详情"
      : pathname.startsWith("/talent")
        ? "人才库"
        : "总览";

  return (
    <div className={`app-shell ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
      <aside id="app-sidebar" className={`sidebar ${mobileNav ? "sidebar-open" : ""}`}>
        <div className="sidebar-head">
          <Logo />
          <button
            className="icon-button sidebar-collapse-button"
            onClick={() => setSidebarCollapsed(true)}
            aria-label="收起侧栏"
            aria-controls="app-sidebar"
            aria-expanded="true"
            title="收起侧栏"
          >
            <PanelLeftClose size={17} />
          </button>
          <button className="icon-button sidebar-close" onClick={() => setMobileNav(false)} aria-label="关闭导航">
            <PanelLeftClose size={17} />
          </button>
        </div>

        <button className="workspace-switch">
          <span className="workspace-logo" aria-hidden="true"><Image src="/reloop-logo.png" alt="" width={28} height={28} unoptimized /></span>
          <span>
            <strong>RE:LOOP Talent Team</strong>
            <small>企业工作区</small>
          </span>
          <ChevronDown size={15} />
        </button>

        <nav className="main-nav">
          {navSections.map((section, sectionIndex) => (
            <div className="nav-section" key={section.label ?? sectionIndex}>
              {section.label && <span className="nav-label">{section.label}</span>}
              {section.items.map((item) => {
                const isActive =
                  item.href === "/"
                    ? pathname === "/"
                    : pathname.startsWith(item.href);
                const NavIcon = item.icon;
                return (
                  <Link
                    href={item.href}
                    key={item.label}
                    className={`nav-item ${isActive ? "active" : ""}`}
                    onClick={() => setMobileNav(false)}
                  >
                    <NavIcon size={17} strokeWidth={1.9} />
                    <span>{item.label}</span>
                    {item.badge && <em>{item.badge}</em>}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>

        <div className="sidebar-spacer" />
        <button className="data-health" onClick={() => router.push("/sources")}>
          <span className="data-health-copy">
            <span className="status-orb"><span /></span>
            <span>
              <strong>数据源状态</strong>
              <small>点击查看</small>
            </span>
          </span>
          <ChevronRight size={14} />
        </button>
        <div className="sidebar-bottom">
          <button><CircleHelp size={17} />帮助中心</button>
          <button><Settings size={17} />设置</button>
          <div className="profile-mini">
            <span className="avatar avatar-sm avatar-slate">笑</span>
            <span><strong>笑咪</strong><small>管理员</small></span>
            <MoreHorizontal size={17} />
          </div>
        </div>
      </aside>

      {mobileNav && <button className="sidebar-backdrop" aria-label="关闭导航" onClick={() => setMobileNav(false)} />}

      <main className="main-stage">
        <header className="topbar">
          <div className="topbar-left">
            {sidebarCollapsed && (
              <button
                className="icon-button desktop-sidebar-open"
                onClick={() => setSidebarCollapsed(false)}
                aria-label="展开侧栏"
                aria-controls="app-sidebar"
                aria-expanded="false"
                title="展开侧栏"
              >
                <PanelLeftOpen size={18} />
              </button>
            )}
            <button className="icon-button mobile-menu" onClick={() => setMobileNav(true)} aria-label="打开导航">
              <Menu size={19} />
            </button>
            <span className="section-crumb">RE:LOOP</span>
            <ChevronRight size={14} />
            <strong>{sectionTitle}</strong>
          </div>
          <div className="topbar-actions">
            <button className="global-search" onClick={() => setSearchOpen(true)}>
              <Search size={15} />
              <span>搜索人才、公司或职位…</span>
              <kbd><Command size={11} />K</kbd>
            </button>
            <button className="icon-button" onClick={() => setDark(!dark)} aria-label={dark ? "切换至浅色模式" : "切换至深色模式"}>
              {dark ? <Sun size={18} /> : <Moon size={18} />}
            </button>
            <button className="icon-button notification-button" onClick={() => setToast("暂无未读通知")} aria-label="通知">
              <Bell size={18} />
              <i />
            </button>
            <button className="top-add-button" onClick={() => setToast("已打开人才录入入口")}>
              <Plus size={16} />
              添加人才
            </button>
          </div>
        </header>
        <div className={`page-content ${pathname === "/" ? "dashboard-page-content" : ""}`}>{children}</div>
      </main>

      {searchOpen && (
        <div className="command-overlay" role="dialog" aria-modal="true" aria-label="全局搜索">
          <button className="command-backdrop" onClick={() => setSearchOpen(false)} aria-label="关闭搜索" />
          <div className="command-panel">
            <div className="command-input">
              <Search size={19} />
              <input
                autoFocus
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="搜索人才、公司、岗位…"
              />
              <button onClick={() => setSearchOpen(false)} aria-label="关闭"><X size={17} /></button>
            </div>
            <div className="command-label">{query ? `搜索结果 · ${searchResults.length}` : "最近查看"}</div>
            <div className="command-results">
              {searchResults.map((talent) => (
                <button
                  key={talent.id}
                  onClick={() => {
                    setSearchOpen(false);
                    router.push(`/talent/${talent.id}`);
                  }}
                >
                  <Avatar talent={talent} size="sm" online={talent.score > 90} />
                  <span><strong>{talent.name}</strong><small>{talent.company} · {talent.role}</small></span>
                  <span className="command-score">{talent.score}</span>
                  <ChevronRight size={15} />
                </button>
              ))}
              {searchResults.length === 0 && (
                <div className="empty-search">
                  <Search size={22} />
                  <strong>没有找到匹配人才</strong>
                  <span>换一个关键词试试</span>
                </div>
              )}
            </div>
            <div className="command-footer"><span><kbd>↑</kbd><kbd>↓</kbd> 选择</span><span><kbd>↵</kbd> 打开</span><span><kbd>esc</kbd> 关闭</span></div>
          </div>
        </div>
      )}

      {toast && (
        <div className="toast">
          <span><Check size={14} /></span>
          {toast}
        </div>
      )}
    </div>
  );
}

type RecentActiveTalent = { talent: Talent; activeMinutes: number; active: string; latestSignal: string };

function ScoreRing({ score, size = "md" }: { score: number; size?: "sm" | "md" | "lg" }) {
  return (
    <span className={`score-ring score-${size}`} style={{ "--score": score } as React.CSSProperties}>
      <span>{score}</span>
    </span>
  );
}

function PageHeading({
  eyebrow,
  title,
  description,
  children,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  children?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        {eyebrow && <span className="eyebrow">{eyebrow}</span>}
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {children && <div className="page-heading-actions">{children}</div>}
    </div>
  );
}

function SectionHeader({
  title,
  meta,
  children,
}: {
  title: string;
  meta?: string;
  children?: ReactNode;
}) {
  return (
    <div className="section-header">
      <div><h2>{title}</h2>{meta && <span>{meta}</span>}</div>
      {children}
    </div>
  );
}



export function DashboardPage() {
  const router = useRouter();
  const [period, setPeriod] = useState("今天");
  const { liveTalents } = useReloopTalents();
  const todayStr = new Date().toISOString().slice(0, 10);
  const todayNew = liveTalents.filter((t) => (t.collectedAt || "").startsWith(todayStr)).length;
  const sortedRecentTalents = useMemo<RecentActiveTalent[]>(
    () => [...liveTalents]
      .sort((a, b) => (b.collectedAt || "").localeCompare(a.collectedAt || ""))
      .slice(0, 12)
      .map((talent) => ({
        talent,
        activeMinutes: 9999,
        active: (talent.collectedAt || "").slice(0, 10),
        latestSignal: `来自${talent.platform || "云端"} · 已入精品库`,
      })),
    [liveTalents],
  );

  const renderActiveTalentGroup = () => (
    <div className="active-talent-group">
      {sortedRecentTalents.map((item, index) => (
        <button
          className="active-talent-row"
          key={item.talent.id}
          onClick={() => router.push(`/talent/${item.talent.id}`)}
        >
          <span className="active-talent-rank">{String(index + 1).padStart(2, "0")}</span>
          <span className="active-talent-person">
            <Avatar talent={item.talent} size="md" online={item.activeMinutes < 60} />
            <span>
              <span><strong>{item.talent.name}</strong>{item.talent.age ? <em>{item.talent.age} 岁</em> : null}</span>
              <small>{item.talent.company} · {item.talent.role} · {item.talent.city}</small>
            </span>
          </span>
          <span className="active-talent-experience">
            <small>工作经历</small>
            <strong>{item.talent.experience}</strong>
          </span>
          <span className="active-talent-school">
            <small>毕业院校</small>
            <strong>{item.talent.school}</strong>
          </span>
          <span className="active-talent-signal">
            <small>最新动态</small>
            <strong>{item.latestSignal}</strong>
          </span>
          <span className="active-talent-score">
            <strong>{item.talent.score}</strong>
            <small>活跃指数</small>
          </span>
          <span className="active-talent-time">
            <i />
            <strong>{item.active}入库</strong>
            <small>入库时间</small>
          </span>
          <ChevronRight className="active-talent-open" size={16} />
        </button>
      ))}
    </div>
  );

  return (
    <div className="dashboard-single-screen">
      <div className="dashboard-overview-zone">
        <div className="editorial-hero-grid">
          <div className="editorial-hero-copy">
            <div className="editorial-wordmark" aria-label="RE:LOOP">RE:LOOP</div>
            <div className="editorial-kicker">
              <span>FIELD NOTES / 03</span>
              <span>人才信号 · AUG 2026</span>
            </div>
            <div className="dashboard-compact-heading">
              <PageHeading
                eyebrow={new Date().toLocaleDateString("zh-CN", { year: "numeric", month: "long", day: "numeric", weekday: "long" })}
                title="早上好，笑咪"
                description={`云端精品库现有 ${liveTalents.length} 位人才，全部具备联系方式。`}
              >
                <button
                  className="secondary-button"
                  onClick={() => setPeriod((current) => current === "今天" ? "本周" : "今天")}
                >
                  <CalendarDays size={15} />{period}<ChevronDown size={14} />
                </button>
                <button className="primary-button" onClick={() => router.push("/insights")}>
                  <Sparkles size={15} />生成 AI 周报
                </button>
              </PageHeading>
            </div>
            <div className="editorial-proofline">
              <span><i />实时捕捉中</span>
              <span>PRIVATE + PUBLIC SIGNALS</span>
            </div>
          </div>

          <div className="editorial-note-rail">
            <article className="editorial-note editorial-note-sage">
              <span className="editorial-note-tape" aria-hidden="true" />
              <span className="editorial-note-index">01</span>
              <small>THE DAILY SIGNAL</small>
              <strong>{liveTalents.length} 位<br />精品人才在库</strong>
              <p>不是每份简历都进库，进库即可联系。</p>
            </article>
            <button
              className="today-active-highlight editorial-anchor-note"
              onClick={() => router.push("/talent?sort=updated")}
            >
              <span className="today-active-icon"><Zap size={17} /></span>
              <span className="today-active-copy">
                <small>今日新入库</small>
                <strong>{todayNew}</strong>
              </span>
              <span className="today-active-detail">按入库时间统计</span>
              <span className="today-active-action">查看最新入库人才 <ArrowUpRight size={14} /></span>
            </button>
          </div>
        </div>
      </div>

      <section className="recommend-section active-focus-section active-talent-stage" id="recent-talents">
        <SectionHeader title="最新入库人才" meta="按入库时间倒序 · 可上下滑动">
          <div className="section-actions">
            <span className="live-pill"><i />持续更新</span>
            <button
              className="text-button"
              onClick={() => router.push("/talent?sort=updated")}
            >
              查看全部 <ArrowUpRight size={14} />
            </button>
          </div>
        </SectionHeader>
        <div className="active-talent-columns" aria-hidden="true">
          <span className="active-column-person">人才</span>
          <span className="active-column-experience">工作经历</span>
          <span className="active-column-school">毕业院校</span>
          <span className="active-column-signal">最新动态</span>
          <span className="active-column-score">活跃</span>
          <span className="active-column-time">入库时间</span>
          <span />
        </div>
        <div
          className="active-talent-viewport"
          role="region"
          aria-label="最近活跃人才，可上下滚动查看更多"
          tabIndex={0}
        >
          <div className="active-talent-track">
            {renderActiveTalentGroup()}
          </div>
        </div>
      </section>

      <section className="editorial-closing-cta" aria-labelledby="editorial-closing-title">
        <div>
          <span className="editorial-kicker"><span>NEXT / 04</span><span>KEEP THE SIGNAL MOVING</span></span>
          <h2 id="editorial-closing-title">把下一条信号，变成下一次联系。</h2>
          <p>从最近活跃的人才开始，继续你的下一步判断。</p>
        </div>
        <div className="editorial-closing-actions">
          <button className="primary-button" onClick={() => router.push("/talent?sort=updated")}>
            进入人才库 <ArrowUpRight size={14} />
          </button>
          <button className="editorial-closing-link" onClick={() => router.push("/insights")}>
            查看 AI 洞察 <ChevronRight size={14} />
          </button>
        </div>
      </section>
      <footer className="editorial-footer">
        <span>RE:LOOP / TALENT INTELLIGENCE</span>
        <span>FIELD NOTES · 2026</span>
      </footer>
    </div>
  );
}

const filterGroups = [
  { label: "最近活跃", values: ["近 24 小时", "近 3 天", "近 7 天", "近 30 天"] },
  { label: "职位", values: ["产品", "技术", "运营", "管理"] },
];

const talentActivityDetails: Record<string, { latestSignal: string; activeTime: string; followStatus: "待跟进" | "跟进中" | "已收藏"; activeRank: number }> = {};

type TalentCardProfile = {
  degree: string;
  advantage: string;
  tags: string[];
  currentPeriod: string;
  previousPeriod: string;
  previousCompany: string;
  previousRole: string;
  educationPeriod: string;
};

const talentCardProfiles: Record<string, TalentCardProfile> = {};

function profileForTalent(talent: Talent): TalentCardProfile {
  return talentCardProfiles[talent.id] ?? {
    degree: "学历待核",
    advantage: "云端精品库记录，等待人工复核补全",
    tags: [talent.platform || "云端精品库"],
    currentPeriod: "当前经历待核",
    previousPeriod: "",
    previousCompany: "",
    previousRole: "",
    educationPeriod: "待核",
  };
}

function activityForTalent(talent: Talent) {
  return talentActivityDetails[talent.id] ?? {
    latestSignal: "已入云端精品库，活跃信号待接入",
    activeTime: talent.updated || "刚刚",
    followStatus: "待跟进" as const,
    activeRank: 999,
  };
}

export function TalentPage() {
  const router = useRouter();
  const { liveTalents, loading: liveLoading, error: liveError } = useReloopTalents();
  const [sort, setSort] = useState<"score" | "recent" | "priority">("score");
  const [search, setSearch] = useState("");
  const [selectedFilters, setSelectedFilters] = useState<string[]>([]);
  const [checked, setChecked] = useState<string[]>([]);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [activeView, setActiveView] = useState(false);
  const allTalents = useMemo(() => listTalents(liveTalents), [liveTalents]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const params = new URLSearchParams(window.location.search);
      const query = params.get("search");
      const querySort = params.get("sort");
      const nextFilters: string[] = [];
      if (query) setSearch(query);
      if (params.get("status") === "active") {
        nextFilters.push("近期活跃");
        setActiveView(true);
      }
      if (params.get("period") === "7d") nextFilters.push("近 7 天");
      if (params.get("period") === "1d") nextFilters.push("近 24 小时");
      if (params.get("priority") === "high") nextFilters.push("优先关注");
      if (params.get("match") === "high") nextFilters.push("高匹配");
      if (querySort === "recent" || querySort === "updated") setSort("recent");
      if (querySort === "priority") setSort("priority");
      if (querySort === "score") setSort("score");
      if (nextFilters.length) setSelectedFilters(nextFilters);
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  const sortedTalents = useMemo(() => {
    const selectedCities = selectedFilters.filter((item) => ["北京", "上海", "杭州", "深圳"].includes(item));
    const selectedIndustries = selectedFilters.filter((item) => ["人工智能", "互联网", "企业服务", "自动驾驶"].includes(item));
    const filtered = allTalents.filter((talent) => {
      const detail = activityForTalent(talent);
      const matchesSearch = [talent.name, talent.company, talent.role, talent.matchRole, detail.latestSignal]
        .join(" ")
        .toLowerCase()
        .includes(search.toLowerCase());
      if (!matchesSearch) return false;
      if (selectedCities.length && !selectedCities.includes(talent.city)) return false;
      if (selectedIndustries.length && !selectedIndustries.includes(talent.industry)) return false;
      if (selectedFilters.includes("优先关注") && talent.score < 87) return false;
      if (selectedFilters.includes("高匹配") && talent.score < 85) return false;
      if (selectedFilters.includes("已跟进") && detail.followStatus === "待跟进") return false;
      if (selectedFilters.includes("未跟进") && detail.followStatus !== "待跟进") return false;
      const periodDays = { "近 24 小时": 1, "近 3 天": 3, "近 7 天": 7, "近 30 天": 30 } as const;
      for (const [label, days] of Object.entries(periodDays)) {
        if (selectedFilters.includes(label)) {
          const ts = Date.parse(talent.updated || "");
          if (Number.isNaN(ts) || Date.now() - ts > days * 86400000) return false;
        }
      }
      const selectedRoles = selectedFilters.filter((item) => ["产品", "技术", "运营", "管理"].includes(item));
      if (selectedRoles.length && !selectedRoles.some((r) => `${talent.role} ${talent.matchRole}`.includes(r))) return false;
      return true;
    });
    return [...filtered].sort((a, b) => {
      if (sort === "score" || sort === "priority") return b.score - a.score;
      return activityForTalent(a).activeRank - activityForTalent(b).activeRank;
    });
  }, [allTalents, search, selectedFilters, sort]);

  const toggleFilter = (value: string) =>
    setSelectedFilters((current) =>
      current.includes(value) ? current.filter((item) => item !== value) : [...current, value],
    );

  return (
    <>
      <PageHeading title={activeView ? "最近活跃人才" : "人才库"} description={activeView ? "近 7 天出现新信号的人才，按最近活跃时间从近到远排列。" : "跨私域、公域与公开活跃信号，持续识别值得联系的人才。"}>
        <button className="secondary-button"><ArrowDown size={15} />导入人才</button>
        <button className="primary-button"><Plus size={15} />新建人才</button>
      </PageHeading>

      {liveError && <div className="live-backend-notice warning"><TriangleAlert size={14} />{liveError}，请检查后端连接后刷新</div>}

      <div className="talent-layout">
        <aside className={`filter-panel ${filtersOpen ? "filter-open" : ""}`}>
          <div className="filter-panel-head">
            <span><SlidersHorizontal size={15} />筛选人才</span>
            <button onClick={() => setSelectedFilters([])}>清空</button>
          </div>
          {filterGroups.map((group) => (
            <div className="filter-group" key={group.label}>
              <div className="filter-group-label"><span>{group.label}</span><ChevronDown size={14} /></div>
              {group.values.map((value) => (
                <label key={value}>
                  <input type="checkbox" checked={selectedFilters.includes(value)} onChange={() => toggleFilter(value)} />
                  <span className="fake-check"><Check size={11} /></span>
                  <span>{value}</span>
                </label>
              ))}
            </div>
          ))}
          <div className="filter-toggle-line">
            <span>仅看最近更新</span>
            <button className="switch"><i /></button>
          </div>
        </aside>

        <section className="talent-list-panel">
          <div className="talent-toolbar">
            <div>
              <strong>{activeView ? "近期活跃" : "全部人才"}</strong>
              <span>{liveLoading ? "同步中…" : `${sortedTalents.length} 条`}</span>
              <small><Sparkles size={12} />{liveTalents.length ? `Reloop 云端精品库 ${liveTalents.length} 位人才` : "云端精品库同步中…"}</small>
            </div>
            <div className="talent-toolbar-actions">
              <button className="mobile-filter-button" onClick={() => setFiltersOpen(!filtersOpen)}><Filter size={15} />筛选</button>
              <label className="table-search"><Search size={14} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="在结果中搜索" /></label>
              <div className="sort-tabs">
                <button className={sort === "recent" ? "active" : ""} onClick={() => setSort("recent")}>最近活跃</button>
                <button className={sort === "score" ? "active" : ""} onClick={() => setSort("score")}>活跃度</button>
                <button className={sort === "priority" ? "active" : ""} onClick={() => setSort("priority")}>联系优先级</button>
              </div>
              <button className="icon-button"><ListFilter size={16} /></button>
            </div>
          </div>

          {selectedFilters.length > 0 && (
            <div className="active-filters">
              <span>已选条件</span>
              {selectedFilters.map((filter) => (
                <button key={filter} onClick={() => toggleFilter(filter)}>{filter}<X size={12} /></button>
              ))}
            </div>
          )}

          <div className="talent-profile-list">
            {sortedTalents.map((talent) => {
              const profile = profileForTalent(talent);
              const activity = activityForTalent(talent);
              const experienceYears = talent.experience.match(/^\d+\s*年/)?.[0] ?? talent.experience.split("·")[0].trim();
              return (
                <article className="talent-profile-card" key={talent.id} onDoubleClick={() => router.push(`/talent/${talent.id}`)}>
                  <label className="talent-profile-check">
                    <input
                      type="checkbox"
                      aria-label={`选择 ${talent.name}`}
                      checked={checked.includes(talent.id)}
                      onChange={() => setChecked((current) => current.includes(talent.id) ? current.filter((id) => id !== talent.id) : [...current, talent.id])}
                    />
                  </label>

                  <div className="talent-profile-main">
                    <Avatar talent={talent} size="lg" online={talent.score > 90} />
                    <div className="talent-profile-copy">
                      <button className="talent-profile-name" onClick={() => router.push(`/talent/${talent.id}`)}>{talent.name}</button>
                      <div className="talent-profile-basics"><span>{talent.age ? `${talent.age} 岁` : "年龄待核"}</span><i /><span>{experienceYears}</span><i /><span>{profile.degree}</span></div>
                      <p><small>期望</small><strong>{talent.city}<i>·</i>{talent.matchRole}</strong></p>
                      <p><small>优势</small><strong title={profile.advantage}>{profile.advantage}</strong></p>
                      <div className="talent-profile-tags">
                        {profile.tags.map((tag, index) => <span className={index < 2 ? "primary-tag" : ""} key={tag}>{tag}</span>)}
                      </div>
                    </div>
                  </div>

                  <div className="talent-profile-timeline">
                    <div className="talent-timeline-row">
                      <span className="talent-timeline-icon"><BriefcaseBusiness size={12} /></span>
                      <time>{profile.currentPeriod}</time>
                      <strong>{talent.company}<i>·</i>{talent.role}</strong>
                    </div>
                    {profile.previousCompany && <div className="talent-timeline-row compact-row">
                      <span className="talent-timeline-dot" />
                      <time>{profile.previousPeriod}</time>
                      <strong>{profile.previousCompany}<i>·</i>{profile.previousRole}</strong>
                    </div>}
                    <div className="talent-timeline-row education-row">
                      <span className="talent-timeline-icon"><GraduationCap size={12} /></span>
                      <time>{profile.educationPeriod}</time>
                      <strong>{talent.school}</strong>
                    </div>
                  </div>

                  <div className="talent-profile-activity">
                    <div className="talent-profile-score"><small>活跃指数</small><strong>{talent.score}</strong></div>
                    <span className="talent-profile-active"><i />{activity.activeTime}</span>
                    <span className={`follow-status follow-${activity.followStatus === "待跟进" ? "pending" : activity.followStatus === "跟进中" ? "progress" : "saved"}`}>{activity.followStatus}</span>
                    <p title={activity.latestSignal}><Signal size={11} />{activity.latestSignal}</p>
                    <button className="table-view-button" onClick={() => router.push(`/talent/${talent.id}`)}>查看详情<ChevronRight size={12} /></button>
                  </div>
                </article>
              );
            })}
            {sortedTalents.length === 0 && <div className="empty-table"><Search size={22} /><strong>没有匹配的人才</strong><span>试试调整关键词或筛选条件</span></div>}
          </div>
          <div className="table-footer">
            <span>显示 1–{sortedTalents.length}，其中 {liveTalents.length} 条来自 Reloop</span>
            <div><button disabled><ChevronRight className="rotate-180" size={15} /></button><button className="active">1</button><button>2</button><button>3</button><span>…</span><button>48</button><button><ChevronRight size={15} /></button></div>
          </div>
        </section>
      </div>
    </>
  );
}

type JobRecord = {
  id: string;
  title: string;
  clientName: string;
  clientRole: string;
  company: string;
  companyShort: string;
  city: string;
  salary: string;
  owner: string;
  status: "急招" | "招聘中" | "待确认" | "暂停";
  jdFile: string;
  documentCount: number;
  updated: string;
  matchCount: number;
  topMatch: number;
  summary: string;
  tags: string[];
  tone: string;
};

const jobs: JobRecord[] = [];

const jobFilterGroups = [
  { label: "职位状态", values: ["急招", "招聘中", "待确认", "暂停"] },
];

export function JobsPage() {
  const router = useRouter();
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<"updated" | "matches" | "status">("updated");
  const [selectedFilters, setSelectedFilters] = useState<string[]>([]);
  const [checked, setChecked] = useState<string[]>([]);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [activeJob, setActiveJob] = useState<JobRecord | null>(null);

  const visibleJobs = useMemo(() => {
    const normalized = search.trim().toLowerCase();
    const filtered = jobs.filter((job) => {
      const matchesSearch = [job.title, job.clientName, job.company, job.jdFile]
        .join(" ")
        .toLowerCase()
        .includes(normalized);
      const selectedStatuses = selectedFilters.filter((value) => ["急招", "招聘中", "待确认", "暂停"].includes(value));
      const selectedCompanies = selectedFilters.filter((value) => ["星海智能", "远景科技", "智驾未来", "云帆数据"].includes(value));
      const selectedCities = selectedFilters.filter((value) => ["北京", "上海", "深圳", "杭州"].includes(value));
      const selectedOwners = selectedFilters.filter((value) => ["米娅", "李然", "周倩"].includes(value));

      return matchesSearch
        && (selectedStatuses.length === 0 || selectedStatuses.includes(job.status))
        && (selectedCompanies.length === 0 || selectedCompanies.includes(job.company))
        && (selectedCities.length === 0 || selectedCities.includes(job.city))
        && (selectedOwners.length === 0 || selectedOwners.includes(job.owner));
    });

    return [...filtered].sort((a, b) => {
      if (sort === "matches") return b.matchCount - a.matchCount;
      if (sort === "status") {
        const statusOrder = { 急招: 0, 招聘中: 1, 待确认: 2, 暂停: 3 };
        return statusOrder[a.status] - statusOrder[b.status];
      }
      return jobs.indexOf(a) - jobs.indexOf(b);
    });
  }, [search, selectedFilters, sort]);

  const toggleFilter = (value: string) =>
    setSelectedFilters((current) =>
      current.includes(value) ? current.filter((item) => item !== value) : [...current, value],
    );

  return (
    <>
      <PageHeading
        title="职位"
        description="将客户、公司、岗位 JD 与人才匹配进度整合在一个工作台中。"
      >
        <button className="secondary-button"><ArrowDown size={15} />导入 JD</button>
        <button className="primary-button"><Plus size={15} />新建职位</button>
      </PageHeading>

      <section className="job-overview-strip">
        <div><span>全部职位</span><strong>24</strong></div>
        <div><span>正在招聘</span><strong>18</strong><small>75%</small></div>
        <div><span>急招职位</span><strong className="orange-number">5</strong><small>需优先推进</small></div>
        <div><span>待确认 JD</span><strong>3</strong><small>等待客户反馈</small></div>
        <div className="job-ai-stat"><Sparkles size={15} /><span><strong>177</strong><small>AI 高匹配人才</small></span></div>
      </section>

      <div className="talent-layout jobs-layout">
        <aside className={`filter-panel ${filtersOpen ? "filter-open" : ""}`}>
          <div className="filter-panel-head">
            <span><SlidersHorizontal size={15} />筛选职位</span>
            <button onClick={() => setSelectedFilters([])}>清空</button>
          </div>
          {jobFilterGroups.map((group) => (
            <div className="filter-group" key={group.label}>
              <div className="filter-group-label"><span>{group.label}</span><ChevronDown size={14} /></div>
              {group.values.map((value) => (
                <label key={value}>
                  <input type="checkbox" checked={selectedFilters.includes(value)} onChange={() => toggleFilter(value)} />
                  <span className="fake-check"><Check size={11} /></span>
                  <span>{value}</span>
                </label>
              ))}
            </div>
          ))}
        </aside>

        <section className="talent-list-panel jobs-list-panel">
          <div className="talent-toolbar jobs-toolbar">
            <div>
              <strong>全部职位</strong>
              <span>24</span>
              <small><Sparkles size={12} />5 个职位需要优先推进</small>
            </div>
            <div className="talent-toolbar-actions">
              <button className="mobile-filter-button" onClick={() => setFiltersOpen(!filtersOpen)}><Filter size={15} />筛选</button>
              <label className="table-search job-table-search"><Search size={14} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索职位、客户或公司" /></label>
              <div className="sort-tabs">
                <button className={sort === "updated" ? "active" : ""} onClick={() => setSort("updated")}>最近更新</button>
                <button className={sort === "matches" ? "active" : ""} onClick={() => setSort("matches")}>AI 匹配</button>
                <button className={sort === "status" ? "active" : ""} onClick={() => setSort("status")}>状态</button>
              </div>
              <button className="icon-button"><ListFilter size={16} /></button>
            </div>
          </div>

          {selectedFilters.length > 0 && (
            <div className="active-filters">
              <span>已选条件</span>
              {selectedFilters.map((filter) => (
                <button key={filter} onClick={() => toggleFilter(filter)}>{filter}<X size={12} /></button>
              ))}
            </div>
          )}

          <div className="talent-table-wrap">
            <table className="talent-table jobs-table">
              <thead>
                <tr>
                  <th className="checkbox-col"><input type="checkbox" aria-label="选择全部职位" /></th>
                  <th>职位</th>
                  <th>客户名称</th>
                  <th>公司</th>
                  <th>JD / 客户文档</th>
                  <th>AI 匹配人才</th>
                  <th>状态</th>
                  <th>最近更新</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {visibleJobs.map((job) => (
                  <tr key={job.id}>
                    <td className="checkbox-col">
                      <input
                        type="checkbox"
                        aria-label={`选择 ${job.title}`}
                        checked={checked.includes(job.id)}
                        onChange={() => setChecked((current) => current.includes(job.id) ? current.filter((id) => id !== job.id) : [...current, job.id])}
                      />
                    </td>
                    <td>
                      <button className="job-title-cell" onClick={() => setActiveJob(job)}>
                        <span className={`job-role-icon job-role-${job.tone}`}><BriefcaseBusiness size={14} /></span>
                        <span><strong>{job.title}</strong><small>{job.city} · {job.salary}</small><em>{job.summary}</em></span>
                      </button>
                    </td>
                    <td><span className="client-cell"><span className="avatar avatar-sm avatar-slate">{job.clientName.slice(0, 1)}</span><span><strong>{job.clientName}</strong><small>{job.clientRole}</small></span></span></td>
                    <td><span className="company-cell"><span className={`company-logo company-${job.tone}`}>{job.companyShort}</span><strong>{job.company}</strong></span></td>
                    <td>
                      <button className="document-cell" onClick={() => setActiveJob(job)}>
                        <FileText size={14} />
                        <span><strong>{job.jdFile}</strong><small>{job.documentCount} 份整合文档</small></span>
                        <ChevronRight size={13} />
                      </button>
                    </td>
                    <td><span className="job-ai-match"><Sparkles size={13} /><span><strong>{job.matchCount}</strong><small>最高 {job.topMatch}% 匹配</small></span></span></td>
                    <td><span className={`job-status status-${job.status}`}>{job.status}</span></td>
                    <td><span className="job-updated"><Clock3 size={12} />{job.updated}<small>{job.owner} 负责</small></span></td>
                    <td><button className="row-more" aria-label={`更多 ${job.title}`}><MoreHorizontal size={17} /></button></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {visibleJobs.length === 0 && <div className="empty-table"><Search size={22} /><strong>没有找到职位</strong><span>试试职位、客户或公司名称</span></div>}
          </div>
          <div className="table-footer">
            <span>显示 1–{visibleJobs.length}，共 24 个职位</span>
            <div><button disabled><ChevronRight className="rotate-180" size={15} /></button><button className="active">1</button><button>2</button><button>3</button><button><ChevronRight size={15} /></button></div>
          </div>
        </section>
      </div>

      {activeJob && (
        <>
          <button className="job-drawer-backdrop" aria-label="关闭职位资料" onClick={() => setActiveJob(null)} />
          <aside className="job-document-drawer" aria-label={`${activeJob.title} 职位资料`}>
            <div className="job-drawer-head">
              <div><span>客户与职位资料</span><small>已整合 {activeJob.documentCount} 份文档</small></div>
              <button className="icon-button" onClick={() => setActiveJob(null)} aria-label="关闭"><X size={17} /></button>
            </div>
            <div className="job-drawer-hero">
              <span className={`job-role-icon job-role-${activeJob.tone}`}><BriefcaseBusiness size={17} /></span>
              <div><h2>{activeJob.title}</h2><p>{activeJob.company} · {activeJob.city} · {activeJob.salary}</p></div>
              <span className={`job-status status-${activeJob.status}`}>{activeJob.status}</span>
            </div>
            <div className="job-drawer-section">
              <h3>客户信息</h3>
              <div className="client-detail-card">
                <span className="avatar avatar-md avatar-slate">{activeJob.clientName.slice(0, 1)}</span>
                <span><strong>{activeJob.clientName}</strong><small>{activeJob.company} · {activeJob.clientRole}</small></span>
                <button><MessageCircle size={14} />联系客户</button>
              </div>
            </div>
            <div className="job-drawer-section">
              <h3>岗位 JD</h3>
              <p className="job-jd-summary">{activeJob.summary}</p>
              <div className="job-meta-grid"><span><MapPin size={12} />{activeJob.city}</span><span><BriefcaseBusiness size={12} />{activeJob.salary}</span><span><UserRound size={12} />负责人：{activeJob.owner}</span></div>
              <div className="job-drawer-tags">{activeJob.tags.map((tag) => <span key={tag}>{tag}</span>)}</div>
            </div>
            <div className="job-drawer-section">
              <h3>JD 与客户文档</h3>
              <button className="drawer-document"><FileText size={16} /><span><strong>{activeJob.jdFile}</strong><small>JD · PDF · 今天更新</small></span><ArrowDown size={14} /></button>
              <button className="drawer-document"><FileText size={16} /><span><strong>{activeJob.company}_客户背景访谈.docx</strong><small>客户文档 · DOCX · 7月29日</small></span><ArrowDown size={14} /></button>
              {activeJob.documentCount > 2 && <button className="drawer-document"><FileText size={16} /><span><strong>候选人画像与沟通口径.pdf</strong><small>客户文档 · PDF · 7月28日</small></span><ArrowDown size={14} /></button>}
            </div>
            <div className="job-drawer-match">
              <span className="ai-mark"><Sparkles size={15} /></span>
              <span><strong>AI 已匹配 {activeJob.matchCount} 位人才</strong><small>最高匹配度 {activeJob.topMatch}% · 按活跃度排序</small></span>
              <button onClick={() => { setActiveJob(null); router.push("/talent"); }}>查看人才<ChevronRight size={13} /></button>
            </div>
          </aside>
        </>
      )}
    </>
  );
}

type WorkspaceKpi = {
  label: string;
  value: string;
  detail: string;
  icon: Icon;
  tone: string;
};

function WorkspaceKpiStrip({ items }: { items: WorkspaceKpi[] }) {
  return (
    <section className="workspace-kpi-grid">
      {items.map((item) => {
        const KpiIcon = item.icon;
        return (
          <article key={item.label}>
            <span className={`workspace-kpi-icon kpi-${item.tone}`}><KpiIcon size={15} /></span>
            <span><small>{item.label}</small><strong>{item.value}</strong></span>
            <em>{item.detail}</em>
          </article>
        );
      })}
    </section>
  );
}

type FocusedTalentRecord = {
  talent: Talent;
  status: "有新动态" | "待跟进" | "跟进中";
  followedAt: string;
  latestTime: string;
  latestSignal: string;
  reason: string;
  matchedRole: string;
  matchScore: number;
  nextAction: string;
};

const focusedTalents: FocusedTalentRecord[] = [];

export function ProjectsPage() {
  const router = useRouter();
  const [search, setSearch] = useState("");
  const [view, setView] = useState<"全部" | "有新动态" | "待跟进">("全部");
  const [followedIds, setFollowedIds] = useState(focusedTalents.map((item) => item.talent.id));
  const [acknowledgedIds, setAcknowledgedIds] = useState<string[]>([]);

  const visibleTalents = useMemo(() => {
    const normalized = search.trim().toLowerCase();
    return focusedTalents.filter((item) => {
      const matchesSearch = [item.talent.name, item.talent.company, item.talent.role, item.matchedRole]
        .join(" ")
        .toLowerCase()
        .includes(normalized);
      return followedIds.includes(item.talent.id) && matchesSearch && (view === "全部" || item.status === view);
    });
  }, [followedIds, search, view]);
  const followedTalentItems = focusedTalents.filter((item) => followedIds.includes(item.talent.id));

  const focusedTalentKpis: WorkspaceKpi[] = [
    { label: "特别关注人选", value: String(followedIds.length), detail: "你的重点人才", icon: Star, tone: "blue" },
    { label: "今日有新动态", value: String(followedTalentItems.filter((item) => item.latestTime.includes("分钟") || item.latestTime.includes("小时")).length), detail: "履历或活跃信号变化", icon: Signal, tone: "violet" },
    { label: "等待跟进", value: String(followedTalentItems.filter((item) => item.status === "待跟进").length), detail: "建议今天优先处理", icon: MessageCircle, tone: "cyan" },
    { label: "近 7 天活跃", value: String(followedTalentItems.length), detail: "全部关注人选", icon: Clock3, tone: "orange" },
  ];

  return (
    <>
      <PageHeading
        title="特别关注人选"
        description="集中查看你重点关注的人才、最新动态、关注原因与下一步跟进安排。"
      >
        <button className="secondary-button" onClick={() => router.push("/talent")}><UsersRound size={15} />查看人才库</button>
        <button className="primary-button" onClick={() => router.push("/talent")}><Plus size={15} />添加关注人选</button>
      </PageHeading>

      <WorkspaceKpiStrip items={focusedTalentKpis} />

      <div className="project-workspace">
        <section className="workspace-panel project-list-panel">
          <div className="workspace-panel-head">
            <div><strong>我特别关注的人选</strong><span>{visibleTalents.length}</span></div>
            <div className="workspace-toolbar">
              <label className="table-search project-search"><Search size={14} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索姓名、公司或职位" /></label>
              <div className="sort-tabs">
                {(["全部", "有新动态", "待跟进"] as const).map((item) => (
                  <button key={item} className={view === item ? "active" : ""} onClick={() => setView(item)}>{item}</button>
                ))}
              </div>
            </div>
          </div>
          <div className="focus-talent-list">
            {visibleTalents.map((item) => {
              const statusClass = item.status === "有新动态" ? "new" : item.status === "待跟进" ? "pending" : "progress";
              const acknowledged = acknowledgedIds.includes(item.talent.id);
              return (
                <article className="focus-talent-card" key={item.talent.id}>
                  <div className="focus-talent-head">
                    <button className="focus-talent-person" onClick={() => router.push(`/talent/${item.talent.id}`)}>
                      <Avatar talent={item.talent} size="lg" online={item.talent.score >= 90} />
                      <span><strong>{item.talent.name}<em>{item.talent.age} 岁</em></strong><small>{item.talent.company} · {item.talent.role} · {item.talent.city}</small><i>{item.followedAt}</i></span>
                    </button>
                    <span className={`focus-talent-status focus-status-${statusClass}`}>{item.status}</span>
                    <button
                      className="focus-star-button"
                      aria-label={`取消关注 ${item.talent.name}`}
                      onClick={() => setFollowedIds((current) => current.filter((id) => id !== item.talent.id))}
                    >
                      <Star size={15} fill="currentColor" />
                    </button>
                  </div>
                  <div className="focus-talent-meta">
                    <span><small>活跃指数</small><strong>{item.talent.score}</strong></span>
                    <span><small>最近活跃</small><strong className="focus-active-time"><i />{item.latestTime}</strong></span>
                    <span><small>适合职位</small><strong>{item.matchedRole}<em>{item.matchScore}% 匹配</em></strong></span>
                  </div>
                  <div className="focus-talent-reason">
                    <Sparkles size={14} />
                    <span><small>关注原因</small><strong>{item.reason}</strong></span>
                  </div>
                  <div className="focus-talent-signal">
                    <Signal size={14} />
                    <span><small>最新动态 · {item.latestTime}</small><strong>{item.latestSignal}</strong></span>
                  </div>
                  <div className="focus-talent-actions">
                    <span><Clock3 size={12} />{item.nextAction}</span>
                    <div>
                      <button
                        className={`secondary-button ${acknowledged ? "contacted-button" : ""}`}
                        onClick={() => setAcknowledgedIds((current) => current.includes(item.talent.id) ? current : [...current, item.talent.id])}
                      >
                        <Check size={13} />{acknowledged ? "已跟进" : "标记已跟进"}
                      </button>
                      <button className="primary-button" onClick={() => router.push(`/talent/${item.talent.id}`)}>查看详情<ChevronRight size={13} /></button>
                    </div>
                  </div>
                </article>
              );
            })}
            {visibleTalents.length === 0 && <div className="empty-table"><Star size={22} /><strong>暂无符合条件的关注人选</strong><span>可以从人才库中添加需要持续关注的人选</span></div>}
          </div>
        </section>

        <aside className="workspace-panel project-priority-panel">
          <div className="workspace-panel-title"><span><Signal size={14} />关注人选动态</span><em>4</em></div>
          <div className="priority-list focus-update-list">
            <button onClick={() => router.push("/talent/zhang-wei")}><span className="priority-time urgent">8分</span><span><strong>更新求职状态</strong><small>张伟 · 浏览 AI 产品总监岗位</small></span><ChevronRight size={13} /></button>
            <button onClick={() => router.push("/talent/lin-xia")}><span className="priority-time">21分</span><span><strong>补充多模态项目经历</strong><small>林夏 · 字节跳动</small></span><ChevronRight size={13} /></button>
            <button onClick={() => router.push("/talent/chen-mo")}><span className="priority-time">47分</span><span><strong>工作经历出现变化</strong><small>陈默 · 阿里云</small></span><ChevronRight size={13} /></button>
            <button onClick={() => router.push("/talent/wang-chen")}><span className="priority-time">4时</span><span><strong>现公司更新为京东</strong><small>王晨 · AI 产品负责人</small></span><ChevronRight size={13} /></button>
          </div>
          <div className="priority-ai-note">
            <Sparkles size={14} />
            <span><strong>AI 关注提醒</strong><small>张伟近期求职意愿明显上升，且已有 3 天未跟进，建议今天优先联系。</small></span>
          </div>
        </aside>
      </div>
    </>
  );
}

type DataConnection = {
  id: string;
  name: string;
  purpose: string;
  lastSync: string;
  icon: Icon;
  tone: string;
  status: "同步正常" | "正在更新" | "需要处理";
};

const dataConnections: DataConnection[] = [];

export function SourcesPage() {
  const router = useRouter();
  const [syncing, setSyncing] = useState(false);
  const [showIssues, setShowIssues] = useState(false);
  const [reconnected, setReconnected] = useState(false);
  const [backendStatus, setBackendStatus] = useState<{ ok: boolean; candidateCount: number; detail?: string } | null>(null);
  const [importDraft, setImportDraft] = useState("");
  const [importing, setImporting] = useState(false);
  const [importMessage, setImportMessage] = useState("");

  const refreshBackendStatus = useCallback(async () => {
    setSyncing(true);
    try {
      const response = await fetch("/api/reloop/status", { cache: "no-store" });
      const payload = await response.json();
      setBackendStatus(payload);
      if (!response.ok || payload.ok === false) {
        setImportMessage(payload.detail || "Reloop 后端暂不可用");
        return false;
      }
      return true;
    } catch {
      setBackendStatus({ ok: false, candidateCount: 0, detail: "前端代理无法连接 Reloop 后端" });
      return false;
    } finally {
      setSyncing(false);
    }
  }, []);

  const reconnectSources = async () => {
    const ok = await refreshBackendStatus();
    if (ok) {
      setReconnected(true);
      setShowIssues(false);
    }
  };

  useEffect(() => {
    const timer = window.setTimeout(() => void refreshBackendStatus(), 0);
    return () => window.clearTimeout(timer);
  }, [refreshBackendStatus]);

  const importText = async () => {
    if (importDraft.trim().length < 10) {
      setImportMessage("请粘贴至少 10 个字符的候选人资料");
      return;
    }
    setImporting(true);
    setImportMessage("");
    try {
      const response = await fetch("/api/reloop/import-text", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ text: importDraft, title: "RE:LOOP 前端录入" }),
      });
      const payload = await response.json();
      if (!response.ok || payload.ok === false) throw new Error(payload.detail || "录入失败");
      setImportDraft("");
      setImportMessage(payload.candidate?.name ? `${payload.candidate.name} 已进入本地候选人队列` : "资料已进入本地候选人队列");
      await refreshBackendStatus();
    } catch (error) {
      setImportMessage(error instanceof Error ? error.message : "录入失败");
    } finally {
      setImporting(false);
    }
  };

  return (
    <>
      <PageHeading
        title="数据连接"
        description="RE:LOOP 会自动从以下来源获取人才资料和近期活跃信号；正常情况下你无需操作。"
      >
        <button className="secondary-button" onClick={() => setShowIssues((current) => !current)}><TriangleAlert size={14} />查看异常</button>
        <button className="primary-button" onClick={refreshBackendStatus} disabled={syncing}>{syncing ? <LoaderCircle className="spin" size={14} /> : <RefreshCw size={14} />}{syncing ? "同步中…" : "检查并同步状态"}</button>
      </PageHeading>

      <section className="live-backend-panel">
        <div className="live-backend-heading">
          <div><span className={`live-backend-dot ${backendStatus?.ok ? "is-ok" : ""}`} /><strong>Reloop 本地后端</strong><small>前端代理 → 解析器 → SQLite outbox</small></div>
          <span className={`live-backend-state ${backendStatus?.ok ? "is-ok" : ""}`}>{backendStatus === null ? "检查中" : backendStatus.ok ? "已连接" : "未连接"}</span>
        </div>
        <div className="live-backend-metrics">
          <span><strong>{backendStatus?.candidateCount ?? "—"}</strong><small>候选人</small></span>
          <span><strong>{backendStatus?.ok ? "18765" : "—"}</strong><small>API 端口</small></span>
          <span><strong>{backendStatus?.ok ? "本地" : "待连接"}</strong><small>数据范围</small></span>
        </div>
        <div className="live-import-box">
          <div><FileText size={15} /><strong>从前端录入候选人</strong><small>资料先进入本地 outbox，不会直接写入 RDS 或飞书。</small></div>
          <textarea value={importDraft} onChange={(event) => setImportDraft(event.target.value)} placeholder="粘贴候选人资料，例如：姓名、电话、邮箱、工作经历、教育经历…" />
          <div className="live-import-actions">
            <span className={importMessage && !importMessage.includes("已进入") ? "is-error" : ""}>{importMessage}</span>
            <button className="primary-button" onClick={importText} disabled={importing}>{importing ? <LoaderCircle className="spin" size={14} /> : <Check size={14} />}{importing ? "录入中…" : "清洗并入队"}</button>
          </div>
        </div>
      </section>

      <section className={`connection-ok-card ${reconnected ? "" : "has-issues"}`}>
        <span className="connection-ok-icon">{reconnected ? <ShieldCheck size={19} /> : <TriangleAlert size={19} />}</span>
        <div>
          <strong>{backendStatus?.ok ? "数据源连接正常" : "等待后端连接"}</strong>
          <p>{backendStatus?.ok ? `云端精品库 ${backendStatus.candidateCount ?? "—"} 条记录。` : "启动 Reloop 后端后自动同步状态。"}</p>
        </div>
        
      </section>


      <div className="connection-simple-grid">
        <section className="workspace-panel connection-list-panel">
          <div className="workspace-panel-title">
            <span><Database size={14} />数据来自哪里</span>
            <em>{dataConnections.length}</em>
          </div>
          <div className="connection-list">
            {dataConnections.map((connection) => {
              const ConnectionIcon = connection.icon;
              return (
                <div className="connection-row" key={connection.id}>
                  <span className={`source-icon source-${connection.tone}`}><ConnectionIcon size={17} /></span>
                  <span>
                    <strong>{connection.name}</strong>
                    <small>{connection.purpose}</small>
                  </span>
                  <span className="connection-last"><small>最近更新</small><strong>{connection.lastSync}</strong></span>
                  <span className={`connection-state state-${reconnected && connection.status === "需要处理" ? "ok" : connection.status === "需要处理" ? "issue" : connection.status === "正在更新" ? "updating" : "ok"}`}><i />{reconnected && connection.status === "需要处理" ? "同步正常" : connection.status}</span>
                </div>
              );
            })}
          </div>
        </section>

        <aside className="workspace-panel connection-help-panel">
          <div className="workspace-panel-title"><span><CircleHelp size={14} />什么时候需要看这里？</span></div>
          <p className="connection-help-copy">只有左下角的同步状态变成黄色或红色时，才需要打开这个页面。</p>
          <div className="connection-help-steps">
            {[
              ["1", "同步长时间停止", "人才资料不再更新"],
              ["2", "人才数量明显异常", "新增或已有资料突然减少"],
              ["3", "需要新增资料来源", "接入新的简历库或名单"],
            ].map(([number, title, detail]) => (
              <div className="connection-help-step" key={number}>
                <span>{number}</span>
                <span><strong>{title}</strong><small>{detail}</small></span>
              </div>
            ))}
          </div>
          <p className="connection-help-note">如果都没有发生，直接返回人才库即可。</p>
          <button className="connection-return-button" onClick={() => router.push("/talent")}>
            返回人才库<ChevronRight size={13} />
          </button>
        </aside>
      </div>
    </>
  );
}

const signalItems: { icon: Icon; title: string; detail: string; time: string; tone: string }[] = [];

export function TalentDetailPage() {
  const router = useRouter();
  const pathname = usePathname();
  const { liveTalents, loading: liveLoading, error: liveError } = useReloopTalents();
  const talentId = pathname.split("/").filter(Boolean).at(-1);
  const allTalents = useMemo(() => mergeTalents(liveTalents), [liveTalents]);
  const talent = allTalents.find((item) => item.id === talentId);
  const [activeTab, setActiveTab] = useState<"profile" | "records">("profile");
  const [note, setNote] = useState("");
  const [savedNotes, setSavedNotes] = useState<string[]>([]);
  const [savedFolder, setSavedFolder] = useState(false);

  if (!talent) {
    return (
      <section className="empty-table detail-empty-state">
        {liveLoading ? <LoaderCircle className="spin" size={22} /> : <TriangleAlert size={22} />}
        <strong>{liveLoading ? "正在加载候选人详情" : "未找到这位候选人"}</strong>
        <span>{liveError || (talentId?.startsWith("reloop-") ? "云端精品库记录不存在或暂不可用。" : "请返回人才库重新选择候选人。")}</span>
        <button className="secondary-button" onClick={() => router.push("/talent")}>返回人才库</button>
      </section>
    );
  }

  const profile = profileForTalent(talent);
  const activity = activityForTalent(talent);

  const saveNote = () => {
    if (!note.trim()) return;
    setSavedNotes((current) => [`刚刚：${note.trim()}`, ...current]);
    setNote("");
  };

  return (
    <>
      <div className="detail-breadcrumb"><button onClick={() => router.push("/talent")}>人才库</button><ChevronRight size={13} /><span>{talent.name}</span></div>
      <section className="detail-hero">
        <div className="detail-person">
          <Avatar talent={talent} size="xl" online />
          <div>
            <div className="detail-name"><h1>{talent.name}</h1><span className="verified"><ShieldCheck size={13} />已验证</span></div>
            <p>{talent.role} <i>·</i> {talent.company}</p>
            <span><MapPin size={13} />{talent.city}<BriefcaseBusiness size={13} />{talent.experience}<Clock3 size={13} />{talent.updated}</span>
            {(talent.phone || talent.email) && (
              <span className="detail-contact">
                {talent.phone && <a href={`tel:${talent.phone}`}><Phone size={13} />{talent.phone}</a>}
                {talent.email && <a href={`mailto:${talent.email}`}><Mail size={13} />{talent.email}</a>}
              </span>
            )}
          </div>
        </div>
        <div className="detail-actions">
          <button className="secondary-button" onClick={() => router.push("/talent")}><ChevronRight className="rotate-180" size={14} />返回人才库</button>
          <button className={savedFolder ? "contacted-button" : "primary-button"} onClick={() => setSavedFolder(true)}>{savedFolder ? <Check size={14} /> : <FolderPlus size={14} />}{savedFolder ? "已加入文件夹" : "加入文件夹"}</button>
        </div>
      </section>

      <div className="detail-stats">
        <div><span>活跃指数</span><strong className="blue-number">{talent.score}</strong><small><TrendingUp size={12} />信号待接入</small></div>
        <div><span>岗位匹配度</span><strong>{talent.score}%</strong><small>{talent.matchRole}</small></div>
        <div><span>质量分</span><strong className="orange-number">{talent.qualityScore == null ? "待回填" : talent.qualityScore}</strong><small>4 要素闸门</small></div>
        <div><span>复核状态</span><strong>{talent.reviewStatus === "approved" ? "已复核" : "待复核"}</strong><small>人工复核后进入推荐</small></div>
        <div><span>人才库来源</span><strong className="source-count">1 <small>个</small></strong><small>{talent.platform || "云端精品库"}</small></div>
      </div>
      <div className="activity-score-explanation"><Signal size={13} /><span><strong>活跃指数如何计算：</strong>综合近 30 天登录、资料更新、技能变化、职位浏览和公开动态，并按信号可信度加权。</span></div>

      <div className="detail-grid">
        <section className="detail-column resume-column">
          <div className="column-tabs">
            <button className={activeTab === "profile" ? "active" : ""} onClick={() => setActiveTab("profile")}>完整履历</button>
            <button className={activeTab === "records" ? "active" : ""} onClick={() => setActiveTab("records")}>附件资料 <span>0</span></button>
          </div>
          {activeTab === "profile" ? (
            <div className="resume-content">
              <div className="resume-block">
                <h3><BriefcaseBusiness size={15} />工作经历</h3>
                {talent.source === "reloop" ? <div className="timeline-entry current">
                  <span className="company-badge badge-moon">{talent.company.slice(0, 1)}</span>
                  <div>
                    <strong>{talent.role}</strong>
                    <p>{talent.company} · 本地 Reloop 解析</p>
                    <small>{profile.currentPeriod}</small>
                    <ul><li>原始资料已保存到本地候选人记录，等待人工复核。</li></ul>
                  </div>
                </div> : <>
                <div className="timeline-entry current">
                  <span className="company-badge badge-moon">M</span>
                  <div>
                    <strong>AI 产品负责人</strong>
                    <p>Moonshot AI · 全职</p>
                    <small>2023.09 – 至今 · 2 年</small>
                    <ul><li>负责企业级 AI Agent 产品从 0 到 1 的规划与商业化</li><li>带领 12 人产品团队，服务 50+ 头部企业客户</li></ul>
                  </div>
                </div>
                <div className="timeline-entry">
                  <span className="company-badge badge-byte">字</span>
                  <div>
                    <strong>高级产品经理</strong>
                    <p>字节跳动 · 飞书</p>
                    <small>2020.06 – 2023.08 · 3 年 3 个月</small>
                    <ul><li>负责智能协同与开放平台产品，主导多个 AI 能力落地</li></ul>
                  </div>
                </div>
                <div className="timeline-entry">
                  <span className="company-badge badge-baidu">百</span>
                  <div>
                    <strong>产品经理</strong>
                    <p>百度 · AI 开放平台</p>
                    <small>2016.07 – 2020.05 · 3 年 11 个月</small>
                  </div>
                </div>
                </>}
              </div>
              <div className="resume-block education-block">
                <h3><Building2 size={15} />教育背景</h3>
                <div><span className="school-badge">{talent.school.slice(0, 1)}</span><span><strong>{talent.school}</strong><p>{profile.degree}</p><small>{profile.educationPeriod}</small></span></div>
              </div>
            </div>
          ) : (
            <div className="attachments"><p>暂无附件，原始简历文件存档于云端。</p></div>
          )}
        </section>

        <section className="detail-column portrait-column">
          <div className="column-title"><span><Sparkles size={15} />人才画像</span><small>{talent.source === "reloop" ? activity.latestSignal : "AI 刚刚更新"}</small></div>
          <div className="ai-summary-card">
            <div><span className="ai-mark"><Sparkles size={15} /></span><strong>AI 人才总结</strong></div>
            <p>{talent.source === "reloop" ? "这条记录已在云端精品库中。字段置信度和工作经历仍需人工复核，复核通过后进入推荐范围。" : "具备完整的 AI 产品 0-1 与规模化经验，对企业级 Agent 商业化有深度认知。职业轨迹稳定上升，近期公开行为显示对新机会的探索意愿明显增强。"}</p>
          </div>
          <div className="portrait-section">
            <h3>核心技能</h3>
            <div className="skill-cloud">
              {talent.keywords && talent.keywords.length > 0
                ? talent.keywords.slice(0, 10).map((kw) => <span key={kw}>{kw}</span>)
                : <span>待补充</span>}
            </div>
          </div>
          <div className="portrait-section">
            <h3>人才标签</h3>
            <div className="talent-tags">{profile.tags.map((tag) => <span key={tag}>{tag}</span>)}</div>
          </div>
<div className="folder-history-card">
            <FolderOpen size={15} />
            <span><strong>收藏与文件夹状态</strong><small>{savedFolder ? "已加入「优先跟进」文件夹 · 刚刚" : "当前未加入文件夹"}</small></span>
          </div>
        </section>

        <aside className="detail-column signal-column">
          <div className="column-title"><span><Signal size={15} />Talent Signal</span><button>最近 30 天<ChevronDown size={13} /></button></div>
          <div className="signal-summary">
            <div><strong>0</strong><span>活跃信号</span></div><div><strong>0</strong><span>高意向信号</span></div>
          </div>
          <div className="signal-timeline">
            {signalItems.map((item) => {
              const SignalIcon = item.icon;
              return (
                <div className="signal-item" key={item.title}>
                  <span className={`signal-icon signal-${item.tone}`}><SignalIcon size={14} /></span>
                  <div><strong>{item.title}</strong><p>{item.detail}</p><time>{item.time}</time></div>
                </div>
              );
            })}
          </div>
          
          <div className="contact-analysis">
            <div className="analysis-title"><Sparkles size={14} /><strong>为什么建议现在联系？</strong></div>
            <ul>
              <li><span>1</span>活跃信号层接入后，这里展示触达时机依据</li>
              <li><span>2</span>完成 JD 匹配后，这里展示大模型生成的触达理由</li>
            </ul>
          </div>
        </aside>
      </div>

      <section className="contact-records">
        <SectionHeader title="联系与跟进记录" meta={`${savedNotes.length} 条记录`}>
          <button className="text-button">查看全部 <ArrowUpRight size={13} /></button>
        </SectionHeader>
        <div className="note-composer">
          <span className="avatar avatar-sm avatar-slate">笑</span>
          <textarea value={note} onChange={(event) => setNote(event.target.value)} placeholder="添加备注、沟通结果或下一步计划…" />
          <div className="note-actions"><span><button><Phone size={14} /></button><button><Mail size={14} /></button><button><MessageCircle size={14} /></button></span><button className="primary-button" onClick={saveNote}>保存记录</button></div>
        </div>
        <div className="saved-notes">
          {savedNotes.map((item, index) => <div key={`${item}-${index}`}><span className="note-dot" /><p>{item}</p><button><MoreHorizontal size={15} /></button></div>)}
        </div>
      </section>
    </>
  );
}



export function InsightsPage() {
  const [period, setPeriod] = useState("全部");
  const { liveTalents } = useReloopTalents();

  const total = liveTalents.length;
  const withPhone = liveTalents.filter((t) => t.phone).length;
  const contactRate = total ? Math.round((withPhone / total) * 100) : 0;
  const todayStr = new Date().toISOString().slice(0, 10);
  const todayNew = liveTalents.filter((t) => (t.collectedAt || "").startsWith(todayStr)).length;
  const pendingReview = liveTalents.filter((t) => t.reviewStatus !== "approved").length;

  const countBy = (pick: (t: Talent) => string | null | undefined) => {
    const counts = new Map<string, number>();
    for (const t of liveTalents) {
      const key = (pick(t) || "").trim();
      if (!key || key.includes("待核") || key === "未知") continue;
      counts.set(key, (counts.get(key) || 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  };
  // 公司名展示级清洗：parser 误提取的长句/含标点碎片不进榜单（展示层过滤，不改数据）
  const looksLikeCompany = (name: string) => name.length <= 12 && !/[。，（）();；、]/.test(name);
  const topCompanies = countBy((t) => t.company).filter(([name]) => looksLikeCompany(name)).slice(0, 5);
  const topSchools = countBy((t) => t.school).filter(([name]) => name.length <= 20 && !/[。，；;]/.test(name)).slice(0, 5);
  const topPlatforms = countBy((t) => t.platform).slice(0, 6);
  const keywordCounts = new Map<string, number>();
  for (const t of liveTalents) for (const kw of t.keywords || []) keywordCounts.set(kw, (keywordCounts.get(kw) || 0) + 1);
  const topKeywords = [...keywordCounts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8);
  const latestTalents = [...liveTalents].sort((a, b) => (b.collectedAt || "").localeCompare(a.collectedAt || "")).slice(0, 4);

  return (
    <>
      <PageHeading title="AI 洞察" description="精品人才库的真实结构与质量概览。">
        <button className="secondary-button"><CalendarDays size={15} />{period}</button>
      </PageHeading>

      <section className="insight-hero">
        <div className="insight-orb"><Sparkles size={24} /></div>
        <div className="insight-hero-copy">
          <span>REAL DATA BRIEF</span>
          <h2>云端精品库 <strong>{total}</strong> 位人才</h2>
          <p>不是每份简历都进库：4 要素质量闸门 + 人工复核，进库即可联系。当前联系方式完备率 {contactRate}%，{pendingReview} 位等待人工复核。</p>
          <div><span><UsersRound size={12} />{total} 位精品人才</span><span><Zap size={12} />{contactRate}% 可联系</span><span><Target size={12} />{todayNew} 位今日新入库</span></div>
        </div>
        <div className="insight-score"><span>联系方式完备率</span><strong>{contactRate}</strong><small>/ 100</small><i><em style={{ width: `${contactRate}%` }} /></i></div>
      </section>

      <section className="insight-kpis">
        {[
          { label: "精品人才总数", value: String(total), icon: UsersRound, tone: "blue" },
          { label: "具备联系方式", value: String(withPhone), icon: MessageCircle, tone: "green" },
          { label: "今日新入库", value: String(todayNew), icon: Zap, tone: "violet" },
          { label: "待人工复核", value: String(pendingReview), icon: ShieldCheck, tone: "cyan" },
        ].map((item) => {
          const ItemIcon = item.icon;
          return (
            <article key={item.label}><span className={`metric-icon metric-${item.tone}`}><ItemIcon size={16} /></span><div><span>{item.label}</span><strong>{item.value}</strong></div></article>
          );
        })}
      </section>

      <section className="insight-main-grid">
        <article className="panel market-map-panel">
          <SectionHeader title="来源渠道分布" meta="按入库条数" />
          <div className="role-heatmap">
            {topPlatforms.map(([name, count], index) => (
              <div key={name}>
                <span className="rank-number">{index + 1}</span>
                <span className="role-copy"><strong>{name}</strong><small>{count} 条</small></span>
                <div className="heat-bar"><i className="heat-warm" style={{ width: `${total ? Math.round((count / total) * 100) : 0}%` }} /></div>
                <strong className="heat-score">{count}</strong>
              </div>
            ))}
            {topPlatforms.length === 0 && <p>等待数据接入</p>}
          </div>
        </article>

        <article className="panel companies-panel">
          <SectionHeader title="人才所在公司 Top 5" meta="精品库真实分布" />
          <div className="company-ranking">
            {topCompanies.map(([name, count], index) => (
              <div key={name}>
                <span className={`company-rank rank-${index + 1}`}>{index + 1}</span>
                <span className="company-logo">{name.slice(0, 1)}</span>
                <span><strong>{name}</strong><small>{count} 人在库</small></span>
                <span className="company-index"><i><em style={{ width: `${total ? Math.round((count / total) * 100) : 0}%` }} /></i><small>{count} 人</small></span>
              </div>
            ))}
            {topCompanies.length === 0 && <p>等待数据接入</p>}
          </div>
        </article>
      </section>

      <section className="rankings-grid">
        <article className="panel top-talent-panel">
          <SectionHeader title="最新入库人才" meta="按入库时间">
            <button className="text-button">全部人才<ChevronRight size={13} /></button>
          </SectionHeader>
          {latestTalents.map((talent, index) => (
            <Link href={`/talent/${talent.id}`} key={talent.id} className="ranking-talent">
              <span className="rank-number">{index + 1}</span><Avatar talent={talent} size="sm" /><span><strong>{talent.name}</strong><small>{talent.company} · {talent.role}</small></span><ChevronRight size={14} />
            </Link>
          ))}
          {latestTalents.length === 0 && <p>等待数据接入</p>}
        </article>

        <article className="panel keywords-panel">
          <SectionHeader title="高频技能关键词" meta="精品库真实词频" />
          <div className="keyword-cloud">
            {topKeywords.map(([kw, count]) => <span className="keyword-md" key={kw}>{kw} <em>{count}</em></span>)}
            {topKeywords.length === 0 && <span>待补充</span>}
          </div>
        </article>

        <article className="panel industries-panel">
          <SectionHeader title="高频院校 Top 5" meta="精品库真实分布" />
          <div className="company-ranking">
            {topSchools.map(([name, count], index) => (
              <div key={name}>
                <span className={`company-rank rank-${index + 1}`}>{index + 1}</span>
                <span className="company-logo">{name.slice(0, 1)}</span>
                <span><strong>{name}</strong><small>{count} 人在库</small></span>
              </div>
            ))}
            {topSchools.length === 0 && <p>等待数据接入</p>}
          </div>
        </article>
      </section>
    </>
  );
}
