export type Talent = {
  id: number;
  name: string;
  base_location?: string | null;
  company?: string | null;
  position?: string | null;
  work_years?: number | null;
  education?: string | null;
  skills?: string[] | null;
  value_score?: number | null;
  tendency_score?: number | null;
  last_active_at?: string | null;
  tags?: string[] | null;
  notes?: string | null;
};
export type JDAnalysis = {
  company_name?: string | null;
  title: string;
  summary: string;
  responsibilities: string[];
  required_skills: string[];
  preferred_skills: string[];
  experience: string;
  education: string;
  location: string;
  industry_keywords: string[];
  salary_range: string;
  team_size: string;
  reporting_line: string;
  language_requirements: string[];
};
export type Position = { id: number; position_name: string; company_name?: string | null; jd_text?: string | null; jd_analysis?: JDAnalysis | null; jd_analysis_version?: string | null; is_active: boolean };
export type JDParseResponse = { analysis: JDAnalysis; source_text: string };
export type Interaction = { interaction_type: string; summary?: string | null; occurred_at: string };
export type Recommendation = {
  rank: number;
  talent_id: number;
  name: string;
  company?: string | null;
  position?: string | null;
  base_location?: string | null;
  work_years?: number | null;
  education?: string | null;
  score: number;
  contact_reason?: string | null;
  status?: "pending" | "confirmed" | "rejected";
};
export type RecommendResult = {
  phase?: "preview" | "final";
  computing?: boolean;
  cached?: boolean;
  top_n?: Recommendation[];
  status?: "idle" | "running" | "done" | "failed";
};
export type SyncStatus = {
  status: "idle" | "running" | "done" | "failed" | "not_found";
  current?: number;
  total?: number;
  processed?: number;
  synced?: number;
  message?: string;
  error?: string;
};
export type CurrentUser = {
  user_id: string;
  display_name: string;
  pool_count: number;
  ttc_connected: boolean;
  ttc_bound_name?: string | null;
  ttc_space_id?: string | null;
};

type Config = { mode: "live" | "mock"; apiBase: string; ownerId: string };
type Auth = { token: string; user: { user_id: string; display_name: string } };

const CFG_KEY = "reloop.cfg";
const AUTH_KEY = "reloop.auth";
const DEEPSEEK_API_KEY = "reloop.deepseekApiKey";
export const AUTH_CHANGE_EVENT = "reloop:auth-change";
const LOCAL_API = "http://127.0.0.1:8000";
const defaultConfig: Config = { mode: "live", apiBase: "", ownerId: "guest_shared" };

function staticPreview() {
  return location.protocol === "file:" ||
    ((location.hostname === "localhost" || location.hostname === "127.0.0.1") && location.port === "3000");
}

function apiBase() {
  const explicit = config.read().apiBase.trim();
  if (explicit) return explicit.replace(/\/$/, "");
  return staticPreview() ? LOCAL_API : "";
}

export function canSendDeepseekApiKey(requestUrl: string, browserOrigin: string) {
  try { return new URL(requestUrl, browserOrigin).origin === browserOrigin; }
  catch { return false; }
}

export const config = {
  read(): Config {
    try {
      const stored: unknown = JSON.parse(localStorage.getItem(CFG_KEY) || "{}");
      if (!stored || typeof stored !== "object") return { ...defaultConfig };
      const value = stored as Partial<Config>;
      return {
        mode: value.mode === "mock" ? "mock" : "live",
        apiBase: typeof value.apiBase === "string" ? value.apiBase : defaultConfig.apiBase,
        ownerId: typeof value.ownerId === "string" ? value.ownerId : defaultConfig.ownerId,
      };
    }
    catch { return { ...defaultConfig }; }
  },
  write(patch: Partial<Config>): Config {
    const next = { ...this.read(), ...patch };
    localStorage.setItem(CFG_KEY, JSON.stringify(next));
    return next;
  },
  auth(): Auth | null {
    try { return JSON.parse(localStorage.getItem(AUTH_KEY) || "null"); }
    catch { return null; }
  },
  setAuth(auth: Auth) {
    localStorage.setItem(AUTH_KEY, JSON.stringify(auth));
    window.dispatchEvent(new Event(AUTH_CHANGE_EVENT));
  },
  clearAuth() {
    localStorage.removeItem(AUTH_KEY);
    window.dispatchEvent(new Event(AUTH_CHANGE_EVENT));
  },
};

export const deepseekApiKey = {
  read(): string {
    try { return (localStorage.getItem(DEEPSEEK_API_KEY) || "").trim(); }
    catch { return ""; }
  },
  write(value: string) {
    try { localStorage.setItem(DEEPSEEK_API_KEY, value.trim()); }
    catch { /* Browser storage may be unavailable in privacy-restricted contexts. */ }
  },
  clear() {
    try { localStorage.removeItem(DEEPSEEK_API_KEY); }
    catch { /* Browser storage may be unavailable in privacy-restricted contexts. */ }
  },
};

function isMock() { return config.read().mode === "mock"; }

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const auth = config.auth();
  const headers: Record<string, string> = { "Content-Type": "application/json", ...(init.headers as Record<string, string> || {}) };
  if (auth?.token) headers["X-Auth-Token"] = auth.token;
  else headers["X-Owner-User-Id"] = config.read().ownerId;

  let response: Response;
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 15000);
  try {
    response = await fetch(apiBase() + path, { ...init, headers, signal: init.signal || controller.signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("请求超时，请检查后端地址或网络连接后重试。");
    }
    throw new Error(`无法连接工作台服务（${apiBase() || location.origin}）。请先启动 RE:LOOP 后端。`);
  } finally {
    window.clearTimeout(timeout);
  }
  if (!response.ok) {
    let detail = "";
    try {
      const body = await response.clone().json();
      detail = body.detail || body.message || body.error || "";
    } catch { detail = (await response.text()).trim(); }
    if (response.status === 401 && auth?.token) config.clearAuth();
    throw new Error(detail || `${init.method || "GET"} ${path} → ${response.status}`);
  }
  return response.json() as Promise<T>;
}

const mockTalents: Talent[] = [
  { id: 1, name: "张韵", base_location: "上海", company: "字节跳动", position: "商业分析师", work_years: 8, education: "复旦大学", skills: ["商业分析", "增长", "SQL"], value_score: .86, tendency_score: .78, last_active_at: new Date(Date.now() - 3600000).toISOString(), tags: ["已关注"] },
  { id: 2, name: "李哲", base_location: "深圳", company: "腾讯", position: "数据产品经理", work_years: 7, education: "中山大学", skills: ["数据策略", "A/B Test"], value_score: .82, tendency_score: .74, last_active_at: new Date(Date.now() - 10800000).toISOString() },
];
let mockPositions: Position[] = [{ id: 1, company_name: "北辰智能（演示）", position_name: "AI 产品经理（演示）", jd_text: "负责业务分析、增长策略与经营复盘", jd_analysis: { company_name: "北辰智能（演示）", title: "AI 产品经理（演示）", summary: "负责业务分析、增长策略与经营复盘。", responsibilities: ["业务分析", "增长策略", "经营复盘"], required_skills: ["SQL", "商业分析"], preferred_skills: ["Python"], experience: "3 年以上", education: "本科及以上", location: "上海", industry_keywords: ["互联网", "增长"], salary_range: "面议", team_size: "待确认", reporting_line: "业务负责人", language_requirements: ["中文"] }, is_active: true }];
const mockInteractions = new Map<number, Interaction[]>();

export const api = {
  health: () => request<{ status: string }>("/health"),
  async listTalents(keyword = "") {
    if (isMock()) return mockTalents.filter((talent) => JSON.stringify(talent).includes(keyword));
    return request<Talent[]>(`/talents${keyword ? `?keyword=${encodeURIComponent(keyword)}` : ""}`);
  },
  async listFollowed() {
    if (isMock()) return mockTalents.filter((talent) => talent.tags?.includes("已关注"));
    return request<Talent[]>("/talents/followed/list");
  },
  async getTalent(id: number) {
    if (isMock()) return mockTalents.find((talent) => talent.id === id) || null;
    return request<Talent>(`/talents/${id}`);
  },
  async getInteractions(id: number) {
    if (isMock()) return mockInteractions.get(id) || [];
    return request<Interaction[]>(`/talents/${id}/interactions`);
  },
  async addInteraction(id: number, body: Omit<Interaction, "occurred_at">) {
    if (isMock()) {
      mockInteractions.set(id, [{ ...body, occurred_at: new Date().toISOString() }, ...(mockInteractions.get(id) || [])]);
      return { ok: true };
    }
    return request<{ ok: boolean }>(`/talents/${id}/interaction`, { method: "POST", body: JSON.stringify(body) });
  },
  async followTalent(id: number) {
    if (isMock()) return { ok: true };
    return request<{ ok: boolean; followed?: boolean }>(`/talents/${id}/follow`, { method: "POST" });
  },
  async listPositions() { return isMock() ? mockPositions.filter((item) => item.is_active) : request<Position[]>("/positions"); },
  async parseJd(jdText: string, images: string[] = []) {
    if (isMock()) return { analysis: { title: "待确认岗位", summary: jdText.trim() || "已从图片提取职位描述", responsibilities: ["根据 JD 执行岗位职责"], required_skills: ["待确认"], preferred_skills: ["待确认"], experience: "待确认", education: "待确认", location: "待确认", industry_keywords: ["待确认"], salary_range: "待确认", team_size: "待确认", reporting_line: "待确认", language_requirements: ["中文"] }, source_text: jdText.trim() || "已从图片提取职位描述" } satisfies JDParseResponse;
    const requestKey = deepseekApiKey.read();
    const parseUrl = `${apiBase()}/positions/parse-jd`;
    if (requestKey && !canSendDeepseekApiKey(parseUrl, location.origin)) {
      throw new Error("DeepSeek API Key 仅能发送到同源工作台服务。请移除跨域后端地址或清除浏览器密钥。");
    }
    return request<JDParseResponse>("/positions/parse-jd", {
      method: "POST",
      headers: requestKey ? { "X-DeepSeek-Api-Key": requestKey } : undefined,
      body: JSON.stringify({ jd_text: jdText, images }),
    });
  },
  async setPosition(body: Pick<Position, "position_name" | "company_name" | "jd_text" | "jd_analysis"> & { replacement_position_id?: number }) {
    if (isMock()) {
      const { replacement_position_id: replacementId, ...positionBody } = body;
      const found = mockPositions.find((item) => item.position_name === positionBody.position_name && item.company_name === positionBody.company_name);
      if (replacementId != null && replacementId !== found?.id) {
        mockPositions = mockPositions.filter((item) => item.id !== replacementId);
      }
      if (found) return Object.assign(found, positionBody);
      const created = { id: Date.now(), ...positionBody, is_active: true };
      mockPositions = [created, ...mockPositions];
      return created;
    }
    return request<Position>("/positions", { method: "POST", body: JSON.stringify(body) });
  },
  async deletePosition(id: number) {
    if (isMock()) { mockPositions = mockPositions.filter((item) => item.id !== id); return { ok: true }; }
    return request<{ ok: boolean }>(`/positions/${id}`, { method: "DELETE" });
  },
  recommend(position: number | string, sortBy = "match", activity?: number, match?: number) {
    if (isMock()) return Promise.resolve<RecommendResult>({ phase: "final", cached: true, top_n: mockTalents.map((talent, index) => ({ rank: index + 1, talent_id: talent.id, name: talent.name, company: talent.company, position: talent.position, base_location: talent.base_location, work_years: talent.work_years, education: talent.education, score: .9 - index * .12, contact_reason: "综合匹配稳定，建议结合近期动态推进。" })) });
    const query = new URLSearchParams({ sort_by: sortBy });
    query.set(typeof position === "number" ? "position_id" : "position_name", String(position));
    if (activity != null) query.set("w_activity", String(activity));
    if (match != null) query.set("w_match", String(match));
    return request<RecommendResult>(`/recommend/compute?${query}`, { method: "POST" });
  },
  recommendationResult(position: number | string, sortBy = "match", activity?: number, match?: number) {
    const query = new URLSearchParams({ sort_by: sortBy });
    query.set(typeof position === "number" ? "position_id" : "position_name", String(position));
    if (activity != null) query.set("w_activity", String(activity));
    if (match != null) query.set("w_match", String(match));
    return request<RecommendResult>(`/recommend/result?${query}`);
  },
  feedback(body: { talent_id: number; action: "confirm" | "reject" | "correct" | "fav" | "unfav"; corrected_tag?: string; note?: string }) {
    return request<{ ok: boolean }>("/recommend/feedback", { method: "POST", body: JSON.stringify(body) });
  },
  syncTtc: () => request<{ sync_id: string; status: "running" }>("/sync/ttc", { method: "POST" }),
  syncStatus: (syncId: string) => request<SyncStatus>(`/sync/ttc/status?sync_id=${encodeURIComponent(syncId)}`),
  me: () => request<CurrentUser>("/auth/me"),
  feishuLoginUrl: () => request<{ url: string }>("/auth/feishu/url"),
  feishuLogin: (handle: string) => request<Auth>("/auth/feishu/login", { method: "POST", body: JSON.stringify({ handle }) }),
  ttcLoginUrl: () => request<{ url: string }>("/auth/ttc/login-url"),
};
