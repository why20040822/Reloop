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
};

export const talents: Talent[] = [
  {
    id: "zhang-wei",
    name: "张伟",
    initials: "张",
    age: 34,
    company: "Moonshot AI",
    role: "AI 产品负责人",
    experience: "10 年 · 百度 → 京东 → Moonshot AI",
    school: "北京大学 · 信息管理",
    matchRole: "AI 产品总监",
    score: 96,
    updated: "12 分钟前",
    login: "今天 09:42",
    level: "S",
    city: "北京",
    industry: "人工智能",
    color: "indigo",
  },
  {
    id: "lin-xia",
    name: "林夏",
    initials: "林",
    age: 32,
    company: "字节跳动",
    role: "大模型算法专家",
    experience: "8 年 · 商汤科技 → 字节跳动",
    school: "上海交通大学 · 计算机科学",
    matchRole: "LLM 算法负责人",
    score: 93,
    updated: "28 分钟前",
    login: "今天 10:16",
    level: "S",
    city: "上海",
    industry: "互联网",
    color: "cyan",
  },
  {
    id: "chen-mo",
    name: "陈默",
    initials: "陈",
    age: 36,
    company: "阿里云",
    role: "解决方案架构师",
    experience: "12 年 · IBM → 华为云 → 阿里云",
    school: "浙江大学 · 软件工程",
    matchRole: "AI 平台架构师",
    score: 89,
    updated: "1 小时前",
    login: "今天 08:55",
    level: "A",
    city: "杭州",
    industry: "云计算",
    color: "violet",
  },
  {
    id: "xu-qing",
    name: "许晴",
    initials: "许",
    age: 30,
    company: "小红书",
    role: "商业化产品经理",
    experience: "7 年 · 美团 → 小红书",
    school: "复旦大学 · 新闻传播",
    matchRole: "增长产品负责人",
    score: 87,
    updated: "2 小时前",
    login: "昨天 22:31",
    level: "A",
    city: "上海",
    industry: "互联网",
    color: "rose",
  },
  {
    id: "zhou-ye",
    name: "周野",
    initials: "周",
    age: 38,
    company: "腾讯",
    role: "数据科学负责人",
    experience: "14 年 · 微软亚洲研究院 → 腾讯",
    school: "清华大学 · 自动化",
    matchRole: "数据智能总监",
    score: 84,
    updated: "3 小时前",
    login: "今天 07:48",
    level: "A",
    city: "深圳",
    industry: "互联网",
    color: "amber",
  },
  {
    id: "li-na",
    name: "李娜",
    initials: "李",
    age: 35,
    company: "Momenta",
    role: "高级招聘经理",
    experience: "11 年 · 猎聘 → 蔚来 → Momenta",
    school: "南京大学 · 人力资源管理",
    matchRole: "人才战略负责人",
    score: 81,
    updated: "昨天",
    login: "昨天 18:02",
    level: "B",
    city: "苏州",
    industry: "自动驾驶",
    color: "emerald",
  },
  {
    id: "wang-chen",
    name: "王晨",
    initials: "王",
    age: 29,
    company: "京东",
    role: "AI 产品负责人",
    experience: "8 年 · 百度 → 京东",
    school: "武汉大学 · 信息系统",
    matchRole: "AI 产品总监",
    score: 90,
    updated: "4 小时前",
    login: "今天 07:16",
    level: "A",
    city: "北京",
    industry: "互联网",
    color: "rose",
  },
  {
    id: "zhao-min",
    name: "赵敏",
    initials: "赵",
    age: 33,
    company: "百度",
    role: "大模型招聘负责人",
    experience: "10 年 · 猎聘 → 商汤科技 → 百度",
    school: "中国人民大学 · 人力资源管理",
    matchRole: "人才战略负责人",
    score: 88,
    updated: "7 小时前",
    login: "今天 06:28",
    level: "A",
    city: "北京",
    industry: "人工智能",
    color: "cyan",
  },
  {
    id: "liu-yang",
    name: "刘洋",
    initials: "刘",
    age: 31,
    company: "快手",
    role: "AI 基础设施工程师",
    experience: "9 年 · 网易 → 快手",
    school: "北京航空航天大学 · 计算机科学",
    matchRole: "AI 平台架构师",
    score: 86,
    updated: "昨天",
    login: "昨天 21:06",
    level: "A",
    city: "北京",
    industry: "互联网",
    color: "indigo",
  },
  {
    id: "gu-xuan",
    name: "顾轩",
    initials: "顾",
    age: 37,
    company: "华为云",
    role: "企业解决方案总监",
    experience: "13 年 · SAP → 华为云",
    school: "同济大学 · 软件工程",
    matchRole: "企业服务销售总监",
    score: 83,
    updated: "2 天前",
    login: "2 天前 18:20",
    level: "B",
    city: "深圳",
    industry: "企业服务",
    color: "amber",
  },
  {
    id: "sun-ning",
    name: "孙宁",
    initials: "孙",
    age: 29,
    company: "美团",
    role: "增长产品经理",
    experience: "7 年 · 滴滴 → 美团",
    school: "南开大学 · 市场营销",
    matchRole: "增长产品负责人",
    score: 82,
    updated: "3 天前",
    login: "3 天前 20:41",
    level: "B",
    city: "北京",
    industry: "互联网",
    color: "violet",
  },
  {
    id: "he-jing",
    name: "何静",
    initials: "何",
    age: 35,
    company: "小鹏汽车",
    role: "智能驾驶算法专家",
    experience: "12 年 · 博世 → 小鹏汽车",
    school: "哈尔滨工业大学 · 自动化",
    matchRole: "智能驾驶平台架构师",
    score: 80,
    updated: "6 天前",
    login: "6 天前 09:12",
    level: "B",
    city: "广州",
    industry: "自动驾驶",
    color: "emerald",
  },
];

const navSections: { label?: string; items: { label: string; href: string; icon: Icon; badge?: string }[] }[] = [
  {
    items: [
      { label: "总览", href: "/", icon: Grid2X2 },
      { label: "人才库", href: "/talent", icon: UsersRound, badge: "2,846" },
      { label: "AI 洞察", href: "/insights", icon: WandSparkles, badge: "12" },
    ],
  },
  {
    label: "工作空间",
    items: [
      { label: "特别关注人选", href: "/projects", icon: Star, badge: "4" },
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
    login: "本地 Reloop",
    level: score >= 90 ? "S" : score >= 75 ? "A" : "B",
    city: candidate.current_location || candidate.location || "城市待核",
    industry: "待分类",
    color: liveTalentColors[index % liveTalentColors.length],
    source: "reloop",
  };
}

function mergeTalents(liveTalents: Talent[]): Talent[] {
  const liveIds = new Set(liveTalents.map((talent) => talent.id));
  return [...liveTalents, ...talents.filter((talent) => !liveIds.has(talent.id))];
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
              <strong>发现 3 条数据异常</strong>
              <small>4 个来源 · 点击查看</small>
            </span>
          </span>
          <ChevronRight size={14} />
        </button>
        <div className="sidebar-bottom">
          <button><CircleHelp size={17} />帮助中心</button>
          <button><Settings size={17} />设置</button>
          <div className="profile-mini">
            <span className="avatar avatar-sm avatar-slate">M</span>
            <span><strong>米娅</strong><small>管理员</small></span>
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

const recentActiveTalents = [
  {
    talent: talents[0],
    activeMinutes: 8,
    active: "8 分钟前",
    latestSignal: "更新求职状态，并浏览 AI 产品总监岗位",
  },
  {
    talent: talents[1],
    activeMinutes: 21,
    active: "21 分钟前",
    latestSignal: "登录脉脉，并补充多模态项目经历",
  },
  {
    talent: talents[2],
    activeMinutes: 47,
    active: "47 分钟前",
    latestSignal: "更新工作经历，近期公开互动频次上升",
  },
  {
    talent: talents[3],
    activeMinutes: 132,
    active: "2 小时前",
    latestSignal: "连续浏览增长产品岗位，并收藏 1 个职位",
  },
  {
    talent: talents[4],
    activeMinutes: 690,
    active: "11 小时前",
    latestSignal: "新增数据智能项目经历与团队管理标签",
  },
  {
    talent: talents[5],
    activeMinutes: 8460,
    active: "5 天前",
    latestSignal: "更新个人简介，并调整期望工作城市",
  },
  {
    talent: talents[6],
    activeMinutes: 240,
    active: "4 小时前",
    latestSignal: "工作经历由百度更新为京东 AI 产品负责人",
  },
  {
    talent: talents[7],
    activeMinutes: 420,
    active: "7 小时前",
    latestSignal: "登录脉脉，并查看多个人才战略负责人岗位",
  },
  {
    talent: talents[8],
    activeMinutes: 1560,
    active: "昨天",
    latestSignal: "新增 LLM、RAG 与 AI Agent 技能标签",
  },
  {
    talent: talents[9],
    activeMinutes: 2880,
    active: "2 天前",
    latestSignal: "更新企业 AI 解决方案项目与管理范围",
  },
  {
    talent: talents[10],
    activeMinutes: 4560,
    active: "3 天前",
    latestSignal: "重新开放工作机会，并浏览增长负责人职位",
  },
  {
    talent: talents[11],
    activeMinutes: 8640,
    active: "6 天前",
    latestSignal: "补充端到端智驾项目经历与算法技能",
  },
];

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

const todayActiveMetric = {
  label: "今日新增活跃人才",
  value: "128",
  change: "+18.4%",
  detail: "较昨日增加 20 人",
  href: "/talent?status=active&period=1d&sort=recent",
};

export function DashboardPage() {
  const router = useRouter();
  const [period, setPeriod] = useState("今天");
  const sortedRecentTalents = useMemo(
    () => [...recentActiveTalents].sort((a, b) => a.activeMinutes - b.activeMinutes),
    [],
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
              <span><strong>{item.talent.name}</strong><em>{item.talent.age} 岁</em></span>
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
            <strong>{item.active}活跃</strong>
            <small>近 7 天内</small>
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
                eyebrow="2026 年 8 月 3 日 · 星期一"
                title="早上好，米娅"
                description="今天捕捉到 248 条新信号，以下人才刚刚出现动态。"
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
              <strong>今天捕捉到<br />248 条新信号</strong>
              <p>让静态人才库，重新开始流动。</p>
            </article>
            <button
              className="today-active-highlight editorial-anchor-note"
              onClick={() => router.push(todayActiveMetric.href)}
            >
              <span className="today-active-icon"><Zap size={17} /></span>
              <span className="today-active-copy">
                <small>{todayActiveMetric.label}</small>
                <strong>{todayActiveMetric.value}</strong>
              </span>
              <span className="today-active-change"><TrendingUp size={13} />{todayActiveMetric.change}</span>
              <span className="today-active-detail">{todayActiveMetric.detail}</span>
              <span className="today-active-action">查看今天新增的人才 <ArrowUpRight size={14} /></span>
            </button>
          </div>
        </div>
      </div>

      <section className="recommend-section active-focus-section active-talent-stage" id="recent-talents">
        <SectionHeader title="最近活跃人才" meta="近 7 天 · 按活跃时间排序 · 可上下滑动">
          <div className="section-actions">
            <span className="live-pill"><i />持续更新</span>
            <button
              className="text-button"
              onClick={() => router.push("/talent?status=active&period=7d&sort=recent")}
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
          <span className="active-column-time">最近活跃</span>
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
          <button className="primary-button" onClick={() => router.push("/talent?status=active&period=7d&sort=recent")}>
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

const talentActivityDetails: Record<string, { latestSignal: string; activeTime: string; followStatus: "待跟进" | "跟进中" | "已收藏"; activeRank: number }> = {
  "zhang-wei": { latestSignal: "更新求职状态并浏览 AI 产品总监岗位", activeTime: "8 分钟前", followStatus: "待跟进", activeRank: 1 },
  "lin-xia": { latestSignal: "登录脉脉并新增多模态技能", activeTime: "21 分钟前", followStatus: "已收藏", activeRank: 2 },
  "chen-mo": { latestSignal: "工作经历出现变化", activeTime: "47 分钟前", followStatus: "跟进中", activeRank: 3 },
  "xu-qing": { latestSignal: "浏览增长产品负责人岗位", activeTime: "2 小时前", followStatus: "待跟进", activeRank: 4 },
  "zhou-ye": { latestSignal: "新增数据智能项目经历", activeTime: "昨天 21:18", followStatus: "已收藏", activeRank: 5 },
  "li-na": { latestSignal: "更新个人简介和期望城市", activeTime: "昨天 18:02", followStatus: "跟进中", activeRank: 6 },
  "wang-chen": { latestSignal: "工作经历由百度更新为京东", activeTime: "4 小时前", followStatus: "待跟进", activeRank: 7 },
  "zhao-min": { latestSignal: "登录脉脉并浏览人才战略岗位", activeTime: "7 小时前", followStatus: "已收藏", activeRank: 8 },
  "liu-yang": { latestSignal: "新增 LLM、RAG、AI Agent 技能", activeTime: "昨天 21:06", followStatus: "待跟进", activeRank: 9 },
  "gu-xuan": { latestSignal: "更新企业 AI 解决方案项目", activeTime: "2 天前", followStatus: "跟进中", activeRank: 10 },
  "sun-ning": { latestSignal: "重新开放工作机会", activeTime: "3 天前", followStatus: "待跟进", activeRank: 11 },
  "he-jing": { latestSignal: "补充端到端智驾项目经历", activeTime: "6 天前", followStatus: "已收藏", activeRank: 12 },
};

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

const talentCardProfiles: Record<string, TalentCardProfile> = {
  "zhang-wei": { degree: "硕士", advantage: "企业级 AI 产品 0–1、Agent 商业化与团队管理经验", tags: ["AI Agent", "名企经历", "产品负责人"], currentPeriod: "2023.08 – 至今", previousPeriod: "2020.03 – 2023.07", previousCompany: "京东", previousRole: "AI 产品经理", educationPeriod: "2011 – 2015" },
  "lin-xia": { degree: "硕士", advantage: "大模型训练、多模态算法与完整模型上线经验", tags: ["多模态", "LLM", "算法负责人"], currentPeriod: "2022.06 – 至今", previousPeriod: "2019.02 – 2022.05", previousCompany: "商汤科技", previousRole: "算法专家", educationPeriod: "2010 – 2014" },
  "chen-mo": { degree: "本科", advantage: "云平台架构、企业 AI 交付及大型客户解决方案经验", tags: ["云计算", "解决方案", "架构设计"], currentPeriod: "2021.09 – 至今", previousPeriod: "2017.06 – 2021.08", previousCompany: "华为云", previousRole: "云解决方案架构师", educationPeriod: "2007 – 2011" },
  "xu-qing": { degree: "硕士", advantage: "内容增长、商业化产品与用户生命周期运营经验", tags: ["增长产品", "商业化", "内容平台"], currentPeriod: "2021.04 – 至今", previousPeriod: "2018.02 – 2021.03", previousCompany: "美团", previousRole: "高级产品经理", educationPeriod: "2012 – 2016" },
  "zhou-ye": { degree: "博士", advantage: "数据科学、推荐系统与规模化团队管理经验", tags: ["数据智能", "推荐系统", "团队管理"], currentPeriod: "2019.05 – 至今", previousPeriod: "2013.07 – 2019.04", previousCompany: "微软亚洲研究院", previousRole: "主管研究员", educationPeriod: "2004 – 2008" },
  "li-na": { degree: "本科", advantage: "科技公司高端招聘、人才战略与组织搭建经验", tags: ["高端招聘", "人才战略", "智能汽车"], currentPeriod: "2022.03 – 至今", previousPeriod: "2018.06 – 2022.02", previousCompany: "蔚来", previousRole: "招聘负责人", educationPeriod: "2007 – 2011" },
  "wang-chen": { degree: "硕士", advantage: "搜索与 AI 产品复合背景，近期完成关键职业跃迁", tags: ["搜索产品", "AI 产品", "履历更新"], currentPeriod: "2025.08 – 至今", previousPeriod: "2021.04 – 2025.08", previousCompany: "百度", previousRole: "商业产品经理", educationPeriod: "2014 – 2018" },
  "zhao-min": { degree: "本科", advantage: "大模型团队招聘、人才地图与核心岗位攻坚经验", tags: ["人才地图", "大模型招聘", "名企经历"], currentPeriod: "2022.01 – 至今", previousPeriod: "2018.05 – 2021.12", previousCompany: "商汤科技", previousRole: "招聘经理", educationPeriod: "2009 – 2013" },
  "liu-yang": { degree: "硕士", advantage: "AI 基础设施、分布式训练与推理平台工程经验", tags: ["AI Infra", "分布式系统", "RAG"], currentPeriod: "2020.07 – 至今", previousPeriod: "2017.04 – 2020.06", previousCompany: "网易", previousRole: "资深后端工程师", educationPeriod: "2011 – 2015" },
  "gu-xuan": { degree: "本科", advantage: "企业软件售前、行业方案与大型客户拓展经验", tags: ["企业服务", "解决方案", "大客户"], currentPeriod: "2018.09 – 至今", previousPeriod: "2013.03 – 2018.08", previousCompany: "SAP", previousRole: "资深解决方案顾问", educationPeriod: "2006 – 2010" },
  "sun-ning": { degree: "本科", advantage: "本地生活增长、用户策略与跨业务协同经验", tags: ["增长策略", "用户运营", "本地生活"], currentPeriod: "2021.02 – 至今", previousPeriod: "2018.07 – 2021.01", previousCompany: "滴滴", previousRole: "增长产品经理", educationPeriod: "2013 – 2017" },
  "he-jing": { degree: "硕士", advantage: "端到端智驾、感知算法与量产项目落地经验", tags: ["智能驾驶", "感知算法", "量产经验"], currentPeriod: "2020.04 – 至今", previousPeriod: "2014.06 – 2020.03", previousCompany: "博世", previousRole: "高级算法工程师", educationPeriod: "2006 – 2010" },
};

function profileForTalent(talent: Talent): TalentCardProfile {
  return talentCardProfiles[talent.id] ?? {
    degree: "学历待核",
    advantage: "来自 Reloop 本地解析，等待人工复核",
    tags: ["本地导入", talent.source === "reloop" ? "Reloop" : "待核验"],
    currentPeriod: "当前经历待核",
    previousPeriod: "",
    previousCompany: "",
    previousRole: "",
    educationPeriod: "待核",
  };
}

function activityForTalent(talent: Talent) {
  return talentActivityDetails[talent.id] ?? {
    latestSignal: "已进入 Reloop 本地候选人队列",
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
  const allTalents = useMemo(() => mergeTalents(liveTalents), [liveTalents]);

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
      if (selectedFilters.includes("近 24 小时") && detail.activeRank > 4) return false;
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

      {liveError && <div className="live-backend-notice warning"><TriangleAlert size={14} />{liveError}，当前展示本地样例数据</div>}

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
                  <em>{Math.floor(32 + value.length * 17)}</em>
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
              <small><Sparkles size={12} />{liveTalents.length ? `Reloop 已接入 ${liveTalents.length} 条本地候选人` : "AI 发现 36 位优先人才"}</small>
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

const jobs: JobRecord[] = [
  {
    id: "ai-product-director",
    title: "AI 产品总监",
    clientName: "陈雨",
    clientRole: "人才总监",
    company: "星海智能",
    companyShort: "星",
    city: "北京",
    salary: "80–120 万",
    owner: "米娅",
    status: "急招",
    jdFile: "星海智能_AI产品总监_JD_v3.pdf",
    documentCount: 3,
    updated: "今天 09:26",
    matchCount: 36,
    topMatch: 94,
    summary: "负责企业级 AI Agent 产品战略、0–1 产品落地与商业化，管理 10 人以上产品团队。",
    tags: ["AI Agent", "企业服务", "产品战略", "团队管理"],
    tone: "indigo",
  },
  {
    id: "llm-algorithm-lead",
    title: "LLM 算法负责人",
    clientName: "周正",
    clientRole: "联合创始人",
    company: "远景科技",
    companyShort: "远",
    city: "上海",
    salary: "100–150 万",
    owner: "米娅",
    status: "招聘中",
    jdFile: "远景科技_LLM算法负责人_JD.pdf",
    documentCount: 2,
    updated: "今天 08:42",
    matchCount: 28,
    topMatch: 97,
    summary: "负责大模型训练、推理优化与多模态算法团队，要求有完整模型上线经验。",
    tags: ["LLM", "多模态", "推理优化", "团队管理"],
    tone: "cyan",
  },
  {
    id: "autonomous-driving-architect",
    title: "智能驾驶平台架构师",
    clientName: "林悦",
    clientRole: "招聘负责人",
    company: "智驾未来",
    companyShort: "智",
    city: "深圳",
    salary: "90–130 万",
    owner: "李然",
    status: "急招",
    jdFile: "智驾未来_平台架构师_JD_v2.pdf",
    documentCount: 4,
    updated: "昨天 18:16",
    matchCount: 21,
    topMatch: 91,
    summary: "搭建智能驾驶数据与模型平台，负责云边协同架构和大规模工程化交付。",
    tags: ["平台架构", "云边协同", "自动驾驶", "工程化"],
    tone: "violet",
  },
  {
    id: "growth-product-lead",
    title: "增长产品负责人",
    clientName: "吴桐",
    clientRole: "业务 VP",
    company: "云帆数据",
    companyShort: "云",
    city: "杭州",
    salary: "60–90 万",
    owner: "周倩",
    status: "招聘中",
    jdFile: "云帆数据_增长产品负责人_JD.pdf",
    documentCount: 2,
    updated: "昨天 15:08",
    matchCount: 42,
    topMatch: 95,
    summary: "负责企业 SaaS 产品增长、商业化转化与客户生命周期，推动规模化收入增长。",
    tags: ["SaaS", "商业化", "用户增长", "数据驱动"],
    tone: "rose",
  },
  {
    id: "enterprise-sales-director",
    title: "企业服务销售总监",
    clientName: "顾航",
    clientRole: "创始人",
    company: "矩阵云",
    companyShort: "矩",
    city: "北京",
    salary: "70–100 万",
    owner: "李然",
    status: "待确认",
    jdFile: "矩阵云_销售总监_初版JD.docx",
    documentCount: 2,
    updated: "7月29日",
    matchCount: 19,
    topMatch: 88,
    summary: "负责大客户销售体系与重点行业拓展，需要成熟的企业软件客户资源。",
    tags: ["大客户销售", "企业软件", "渠道", "团队搭建"],
    tone: "amber",
  },
  {
    id: "data-science-manager",
    title: "数据科学经理",
    clientName: "沈清",
    clientRole: "HRBP",
    company: "北辰零售",
    companyShort: "北",
    city: "上海",
    salary: "55–80 万",
    owner: "周倩",
    status: "暂停",
    jdFile: "北辰零售_数据科学经理_JD.pdf",
    documentCount: 3,
    updated: "7月28日",
    matchCount: 31,
    topMatch: 89,
    summary: "建设零售预测、推荐与经营分析模型，带领数据科学团队支持业务决策。",
    tags: ["数据科学", "零售", "推荐系统", "业务分析"],
    tone: "emerald",
  },
];

const jobFilterGroups = [
  { label: "职位状态", values: ["急招", "招聘中", "待确认", "暂停"] },
  { label: "客户公司", values: ["星海智能", "远景科技", "智驾未来", "云帆数据"] },
  { label: "城市", values: ["北京", "上海", "深圳", "杭州"] },
  { label: "负责人", values: ["米娅", "李然", "周倩"] },
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
                  <em>{jobs.filter((job) => [job.status, job.company, job.city, job.owner].some((item) => item === value)).length || Math.max(2, value.length)}</em>
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

const focusedTalents: FocusedTalentRecord[] = [
  {
    talent: talents[0],
    status: "待跟进",
    followedAt: "关注于 7月29日",
    latestTime: "8 分钟前",
    latestSignal: "更新求职状态，并连续浏览 AI 产品总监岗位",
    reason: "AI 产品经验与当前重点岗位高度匹配，近期求职意愿明显上升。",
    matchedRole: "AI 产品总监",
    matchScore: 94,
    nextAction: "建议今天 18:00 前首次联系",
  },
  {
    talent: talents[1],
    status: "有新动态",
    followedAt: "关注于 7月30日",
    latestTime: "21 分钟前",
    latestSignal: "登录脉脉，并补充多模态项目经历",
    reason: "大模型算法背景稀缺，新增经历与 LLM 算法负责人岗位高度相关。",
    matchedRole: "LLM 算法负责人",
    matchScore: 91,
    nextAction: "查看新增经历后更新推荐报告",
  },
  {
    talent: talents[2],
    status: "跟进中",
    followedAt: "关注于 7月26日",
    latestTime: "47 分钟前",
    latestSignal: "工作经历出现变化，公开互动频次持续上升",
    reason: "具备云平台与企业级 AI 交付经验，正在验证新的职业动向。",
    matchedRole: "AI 平台架构师",
    matchScore: 87,
    nextAction: "明天 10:30 进行第二次沟通",
  },
  {
    talent: talents[6],
    status: "待跟进",
    followedAt: "关注于 8月1日",
    latestTime: "4 小时前",
    latestSignal: "工作经历由百度更新为京东 AI 产品负责人",
    reason: "刚发生明确履历变化，适合持续观察其新岗位稳定度与流动信号。",
    matchedRole: "AI 产品负责人",
    matchScore: 90,
    nextAction: "本周内确认新岗位入职情况",
  },
];

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

const dataConnections: DataConnection[] = [
  {
    id: "private-crm",
    name: "人才库",
    purpose: "同步已有简历与历史人才资料",
    lastSync: "刚刚",
    icon: Database,
    tone: "blue",
    status: "同步正常",
  },
  {
    id: "public-pool",
    name: "Boss 人才数据",
    purpose: "补全公司、职位与技能信息",
    lastSync: "10 分钟前",
    icon: Globe2,
    tone: "cyan",
    status: "需要处理",
  },
  {
    id: "maimai-signals",
    name: "脉脉活跃信号",
    purpose: "识别近期资料更新与活跃行为",
    lastSync: "2 分钟前",
    icon: Signal,
    tone: "violet",
    status: "同步正常",
  },
  {
    id: "resume-import",
    name: "公开职业信息",
    purpose: "补全人才最新公司、职位与公开经历",
    lastSync: "正在更新",
    icon: Globe2,
    tone: "orange",
    status: "正在更新",
  },
];

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
          <strong>{reconnected ? "数据异常已处理，所有来源同步正常" : "发现 3 条数据异常，需要处理"}</strong>
          <p>{reconnected ? "最近一次更新于刚刚完成。" : "Boss 人才数据连接不稳定，可能影响部分人才资料更新。"}</p>
        </div>
        <button className="connection-alert-action" onClick={() => setShowIssues((current) => !current)}>{showIssues ? "收起异常" : "查看异常"}<ChevronRight size={12} /></button>
      </section>

      {showIssues && !reconnected && (
        <section className="connection-issue-panel">
          <div><TriangleAlert size={16} /><span><strong>Boss 人才数据有 3 条记录未更新</strong><small>不会影响其他数据来源，重新连接后会自动补齐。</small></span></div>
          <button onClick={reconnectSources} disabled={syncing}><RefreshCw size={13} />{syncing ? "连接中…" : "重新连接"}</button>
        </section>
      )}

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

const signalItems = [
  { icon: Globe2, title: "登录脉脉", detail: "移动端登录 · 停留约 8 分钟", time: "今天 09:42", tone: "blue" },
  { icon: BriefcaseBusiness, title: "浏览 AI 产品总监岗位", detail: "查看岗位详情 3 次", time: "昨天 21:16", tone: "violet" },
  { icon: FileText, title: "更新个人简介", detail: "新增「企业级 AI 产品」相关描述", time: "7月27日 14:30", tone: "green" },
  { icon: Tag, title: "新增技能", detail: "AI Agent · RAG · GTM", time: "7月25日 10:08", tone: "amber" },
  { icon: MessageCircle, title: "发布行业动态", detail: "关于 Agent 产品落地的思考", time: "7月21日 19:20", tone: "cyan" },
  { icon: UserRound, title: "新增关注公司", detail: "MiniMax · 百川智能", time: "7月18日 11:45", tone: "rose" },
];

export function TalentDetailPage() {
  const router = useRouter();
  const pathname = usePathname();
  const { liveTalents, loading: liveLoading, error: liveError } = useReloopTalents();
  const talentId = pathname.split("/").filter(Boolean).at(-1);
  const allTalents = useMemo(() => mergeTalents(liveTalents), [liveTalents]);
  const talent = allTalents.find((item) => item.id === talentId);
  const [activeTab, setActiveTab] = useState<"profile" | "records">("profile");
  const [note, setNote] = useState("");
  const [savedNotes, setSavedNotes] = useState(["7月26日：对 AI 原生工作流和 0-1 产品机会感兴趣。"]);
  const [savedFolder, setSavedFolder] = useState(false);

  if (!talent) {
    return (
      <section className="empty-table detail-empty-state">
        {liveLoading ? <LoaderCircle className="spin" size={22} /> : <TriangleAlert size={22} />}
        <strong>{liveLoading ? "正在加载候选人详情" : "未找到这位候选人"}</strong>
        <span>{liveError || (talentId?.startsWith("reloop-") ? "本地 Reloop 记录不存在或暂不可用。" : "请返回人才库重新选择候选人。")}</span>
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
          </div>
        </div>
        <div className="detail-actions">
          <button className="secondary-button" onClick={() => router.push("/talent")}><ChevronRight className="rotate-180" size={14} />返回人才库</button>
          <button className={savedFolder ? "contacted-button" : "primary-button"} onClick={() => setSavedFolder(true)}>{savedFolder ? <Check size={14} /> : <FolderPlus size={14} />}{savedFolder ? "已加入文件夹" : "加入文件夹"}</button>
        </div>
      </section>

      <div className="detail-stats">
        <div><span>活跃指数</span><strong className="blue-number">{talent.score}</strong><small><TrendingUp size={12} />{talent.source === "reloop" ? "本地解析评分" : "近 7 天 +14"}</small></div>
        <div><span>岗位匹配度</span><strong>{talent.source === "reloop" ? `${talent.score}%` : "94%"}</strong><small>{talent.matchRole}</small></div>
        <div><span>跳槽可能性</span><strong className="orange-number">高</strong><small>未来 30 天</small></div>
        <div><span>最佳联系时间</span><strong>今天</strong><small>18:30–20:00</small></div>
        <div><span>人才库来源</span><strong className="source-count">3 <small>个</small></strong><small>私域 · 脉脉 · LinkedIn</small></div>
      </div>
      <div className="activity-score-explanation"><Signal size={13} /><span><strong>活跃指数如何计算：</strong>综合近 30 天登录、资料更新、技能变化、职位浏览和公开动态，并按信号可信度加权。</span></div>

      <div className="detail-grid">
        <section className="detail-column resume-column">
          <div className="column-tabs">
            <button className={activeTab === "profile" ? "active" : ""} onClick={() => setActiveTab("profile")}>完整履历</button>
            <button className={activeTab === "records" ? "active" : ""} onClick={() => setActiveTab("records")}>附件资料 <span>2</span></button>
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
            <div className="attachments">
              <div><FileText size={18} /><span><strong>张伟_个人简历_2026.pdf</strong><small>1.8 MB · 更新于 7月27日</small></span><button>查看</button></div>
              <div><FileText size={18} /><span><strong>AI产品案例集.pdf</strong><small>8.4 MB · 更新于 6月12日</small></span><button>查看</button></div>
            </div>
          )}
        </section>

        <section className="detail-column portrait-column">
          <div className="column-title"><span><Sparkles size={15} />人才画像</span><small>{talent.source === "reloop" ? activity.latestSignal : "AI 刚刚更新"}</small></div>
          <div className="ai-summary-card">
            <div><span className="ai-mark"><Sparkles size={15} /></span><strong>AI 人才总结</strong></div>
            <p>{talent.source === "reloop" ? "这条记录已由 Reloop 后端解析并进入本地 outbox。字段置信度和工作经历仍需人工复核，当前不代表外部系统已写入。" : "具备完整的 AI 产品 0-1 与规模化经验，对企业级 Agent 商业化有深度认知。职业轨迹稳定上升，近期公开行为显示对新机会的探索意愿明显增强。"}</p>
          </div>
          <div className="portrait-section">
            <h3>核心技能</h3>
            <div className="skill-cloud">
              <span className="strong">AI Agent <em>92</em></span><span className="strong">产品战略 <em>90</em></span><span>RAG</span><span>企业服务</span><span>GTM</span><span>团队管理</span><span>大模型</span>
            </div>
          </div>
          <div className="portrait-section">
            <h3>人才标签</h3>
            <div className="talent-tags"><span>连续创业公司经历</span><span>AI 商业化</span><span>技术背景</span><span>管理者</span></div>
          </div>
          <div className="portrait-section">
            <h3>适合职位</h3>
            <div className="talent-tags"><span>AI 产品总监 · 94%</span><span>Agent 产品负责人 · 91%</span><span>企业 AI 产品负责人 · 88%</span></div>
          </div>
          <div className="folder-history-card">
            <FolderOpen size={15} />
            <span><strong>收藏与文件夹状态</strong><small>{savedFolder ? "已加入「优先跟进」文件夹 · 刚刚" : "历史收藏 2 次 · 当前未加入文件夹"}</small></span>
          </div>
          <div className="portrait-section radar-section">
            <h3>能力雷达</h3>
            <div className="radar-chart">
              <svg viewBox="0 0 240 210" aria-label="人才能力雷达图">
                <polygon className="radar-grid outer" points="120,16 210,68 210,142 120,194 30,142 30,68" />
                <polygon className="radar-grid" points="120,45 180,80 180,130 120,165 60,130 60,80" />
                <polygon className="radar-grid" points="120,75 150,92 150,118 120,135 90,118 90,92" />
                <line x1="120" y1="16" x2="120" y2="194" /><line x1="30" y1="68" x2="210" y2="142" /><line x1="210" y1="68" x2="30" y2="142" />
                <polygon className="radar-value" points="120,27 199,73 190,132 120,178 43,136 48,78" />
                <circle cx="120" cy="27" r="3" /><circle cx="199" cy="73" r="3" /><circle cx="190" cy="132" r="3" /><circle cx="120" cy="178" r="3" /><circle cx="43" cy="136" r="3" /><circle cx="48" cy="78" r="3" />
              </svg>
              <span className="radar-label label-product">产品判断</span><span className="radar-label label-tech">技术理解</span><span className="radar-label label-market">商业化</span><span className="radar-label label-lead">领导力</span><span className="radar-label label-innovate">创新力</span><span className="radar-label label-execute">执行力</span>
            </div>
          </div>
        </section>

        <aside className="detail-column signal-column">
          <div className="column-title"><span><Signal size={15} />Talent Signal</span><button>最近 30 天<ChevronDown size={13} /></button></div>
          <div className="signal-summary">
            <div><strong>12</strong><span>活跃信号</span></div><div><strong>4</strong><span>高意向信号</span></div><span className="hot-badge"><Zap size={12} />热度上升</span>
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
          <button className="show-more-signals">查看全部 12 条信号<ChevronDown size={13} /></button>
          <div className="contact-analysis">
            <div className="analysis-title"><Sparkles size={14} /><strong>为什么建议现在联系？</strong></div>
            <ul>
              <li><span>1</span>近期连续浏览目标岗位，求职探索进入活跃期</li>
              <li><span>2</span>新增技能与目标岗位要求高度重合</li>
              <li><span>3</span>当前公司同职级人才流动指数上升 23%</li>
            </ul>
            <div className="best-direction"><span>推荐沟通方向</span><p>从「企业级 Agent 商业化」切入，强调业务自主权与 0-1 产品空间。</p></div>
          </div>
        </aside>
      </div>

      <section className="contact-records">
        <SectionHeader title="联系与跟进记录" meta={`${savedNotes.length} 条记录`}>
          <button className="text-button">查看全部 <ArrowUpRight size={13} /></button>
        </SectionHeader>
        <div className="note-composer">
          <span className="avatar avatar-sm avatar-slate">M</span>
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

const companyData = [
  { name: "字节跳动", value: 92, count: "128 人", change: "+32%" },
  { name: "阿里云", value: 81, count: "96 人", change: "+24%" },
  { name: "百度", value: 73, count: "84 人", change: "+18%" },
  { name: "小红书", value: 65, count: "71 人", change: "+15%" },
  { name: "理想汽车", value: 54, count: "58 人", change: "+12%" },
];

export function InsightsPage() {
  const [period, setPeriod] = useState("最近 7 天");
  const [generated, setGenerated] = useState(false);

  return (
    <>
      <PageHeading title="AI 洞察" description="把分散的人才动态变成可行动的招聘情报。">
        <button className="secondary-button" onClick={() => setPeriod(period === "最近 7 天" ? "最近 30 天" : "最近 7 天")}><CalendarDays size={15} />{period}<ChevronDown size={14} /></button>
        <button className="primary-button" onClick={() => setGenerated(true)}><Sparkles size={15} />{generated ? "报告已更新" : "重新生成洞察"}</button>
      </PageHeading>

      <section className={`insight-hero ${generated ? "pulse-once" : ""}`}>
        <div className="insight-orb"><Sparkles size={24} /></div>
        <div className="insight-hero-copy">
          <span>AI EXECUTIVE BRIEF</span>
          <h2>本周人才流动热度上升 <strong>18.6%</strong></h2>
          <p>大模型产品、AI 应用算法和企业服务销售成为最活跃的三类人才。字节跳动与阿里云的中高层人才公开活跃信号显著增加，建议优先跟进 36 位高匹配候选人。</p>
          <div><span><Zap size={12} />248 条新信号</span><span><UsersRound size={12} />128 位活跃人才</span><span><Target size={12} />36 位立即联系</span></div>
        </div>
        <div className="insight-score"><span>市场流动指数</span><strong>78</strong><small>/ 100</small><i><em style={{ width: "78%" }} /></i></div>
      </section>

      <section className="insight-kpis">
        {[
          { label: "新增活跃人才", value: "486", change: "+18.6%", icon: UsersRound, tone: "blue" },
          { label: "岗位活跃度", value: "72.4", change: "+8.2%", icon: BriefcaseBusiness, tone: "violet" },
          { label: "人才流动公司", value: "64", change: "+12 家", icon: Building2, tone: "cyan" },
          { label: "立即联系人才", value: "36", change: "8 位 S 级", icon: MessageCircle, tone: "green" },
        ].map((item) => {
          const ItemIcon = item.icon;
          return (
            <article key={item.label}><span className={`metric-icon metric-${item.tone}`}><ItemIcon size={16} /></span><div><span>{item.label}</span><strong>{item.value}</strong></div><small><TrendingUp size={11} />{item.change}</small></article>
          );
        })}
      </section>

      <section className="insight-main-grid">
        <article className="panel market-map-panel">
          <SectionHeader title="岗位人才活跃度" meta="按近 7 天信号量">
            <button className="compact-select">活跃指数<ChevronDown size={13} /></button>
          </SectionHeader>
          <div className="role-heatmap">
            {[
              { role: "大模型产品", count: 128, score: 94, change: "+26%", tone: "hot" },
              { role: "AI 应用算法", count: 106, score: 89, change: "+21%", tone: "hot" },
              { role: "企业服务销售", count: 84, score: 82, change: "+18%", tone: "warm" },
              { role: "数据科学", count: 72, score: 76, change: "+12%", tone: "warm" },
              { role: "智能驾驶", count: 58, score: 68, change: "+8%", tone: "cool" },
            ].map((role, index) => (
              <div key={role.role}>
                <span className="rank-number">{index + 1}</span>
                <span className="role-copy"><strong>{role.role}</strong><small>{role.count} 位活跃人才</small></span>
                <div className="heat-bar"><i className={`heat-${role.tone}`} style={{ width: `${role.score}%` }} /></div>
                <strong className="heat-score">{role.score}</strong>
                <span className="positive-change">{role.change}</span>
              </div>
            ))}
          </div>
        </article>

        <article className="panel companies-panel">
          <SectionHeader title="人才流动公司 Top 5" meta="公开信号趋势">
            <button className="text-button">查看榜单<ArrowUpRight size={13} /></button>
          </SectionHeader>
          <div className="company-ranking">
            {companyData.map((company, index) => (
              <div key={company.name}>
                <span className={`company-rank rank-${index + 1}`}>{index + 1}</span>
                <span className="company-logo">{company.name.slice(0, 1)}</span>
                <span><strong>{company.name}</strong><small>{company.count}近期活跃</small></span>
                <span className="company-index"><i><em style={{ width: `${company.value}%` }} /></i><small>流动指数 {company.value}</small></span>
                <span className="positive-change">{company.change}</span>
              </div>
            ))}
          </div>
        </article>
      </section>

      <section className="rankings-grid">
        <article className="panel top-talent-panel">
          <SectionHeader title="Top Active Talent" meta="联系优先级最高">
            <button className="text-button">全部人才<ChevronRight size={13} /></button>
          </SectionHeader>
          {talents.slice(0, 4).map((talent, index) => (
            <Link href={`/talent/${talent.id}`} key={talent.id} className="ranking-talent">
              <span className="rank-number">{index + 1}</span><Avatar talent={talent} size="sm" online={index < 2} /><span><strong>{talent.name}</strong><small>{talent.company} · {talent.role}</small></span><ScoreRing score={talent.score} size="sm" /><ChevronRight size={14} />
            </Link>
          ))}
        </article>

        <article className="panel keywords-panel">
          <SectionHeader title="Top Keywords" meta="人才资料新增词频" />
          <div className="keyword-cloud">
            <span className="keyword-xl">AI Agent <em>128</em></span><span className="keyword-lg">RAG <em>96</em></span><span className="keyword-md">多模态 <em>84</em></span><span className="keyword-lg">大模型应用 <em>78</em></span><span className="keyword-sm">GTM <em>62</em></span><span className="keyword-md">企业服务 <em>58</em></span><span className="keyword-sm">具身智能 <em>45</em></span><span className="keyword-xs">推理优化 <em>38</em></span>
          </div>
          <div className="keyword-note"><Sparkles size={14} /><span><strong>AI Agent</strong> 连续 3 周增长，是当前最强人才趋势信号。</span></div>
        </article>

        <article className="panel industries-panel">
          <SectionHeader title="Top Industries" meta="人才活跃分布" />
          <div className="donut-wrap">
            <div className="donut"><span><strong>486</strong><small>活跃人才</small></span></div>
            <div className="donut-legend">
              <div><span><i className="dot-blue" />人工智能</span><strong>34.8%</strong></div>
              <div><span><i className="dot-violet" />企业服务</span><strong>23.6%</strong></div>
              <div><span><i className="dot-cyan" />互联网</span><strong>18.2%</strong></div>
              <div><span><i className="dot-green" />智能汽车</span><strong>13.4%</strong></div>
              <div><span><i className="dot-gray" />其他</span><strong>10.0%</strong></div>
            </div>
          </div>
        </article>
      </section>
    </>
  );
}
