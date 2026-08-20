// 可切换数据层：live（后端 API，默认同源）↔ mock（内置真实感样本）
// 前后端合并部署后, 后端直接伺服本前端, 因此 live 模式 apiBase 留空即同源调用, 无需配 CORS。
// 切换只改配置, 业务视图不动。
import { TALENTS, POSITIONS, INTERACTIONS, computeRecommend } from "./mock.js";

const LS_KEY = "reloop.cfg";
const LS_AUTH = "reloop.auth";

const DEFAULT_CFG = {
  // 数据模式: live=走真实后端 API; mock=用内置样本(离线演示)
  mode: "live",
  // live 模式下: 留空=同源后端(合并部署默认); 填外部后端地址=远程(需后端开 CORS)
  apiBase: "",
  // 数据隔离键（后端 X-Owner-User-Id, 仅未登录时使用）。默认填已同步 358 人的 open_id
  ownerId: "ou_ff894386d0ca340dcc2f7bdc53c57a81",
  locale: "zh-CN",
};

export function getCfg() {
  try { return { ...DEFAULT_CFG, ...JSON.parse(localStorage.getItem(LS_KEY) || "{}") }; }
  catch { return { ...DEFAULT_CFG }; }
}
export function setCfg(patch) {
  const next = { ...getCfg(), ...patch };
  localStorage.setItem(LS_KEY, JSON.stringify(next));
  return next;
}
export function useMock() { return getCfg().mode === "mock"; }

// —— 飞书扫码登录态 ——
export function getAuth() {
  try { return JSON.parse(localStorage.getItem(LS_AUTH) || "null"); } catch { return null; }
}
export function setAuth(auth) {
  localStorage.setItem(LS_AUTH, JSON.stringify(auth));
}
export function clearAuth() {
  localStorage.removeItem(LS_AUTH);
}
export function isAuthed() { return !!getAuth()?.token; }

// —— HTTP 客户端（live 模式）——
async function http(path, { method = "GET", body } = {}) {
  const cfg = getCfg();
  const auth = getAuth();
  // apiBase 留空 -> 同源相对路径(合并部署默认); 填了 -> 走该外部后端
  const base = cfg.apiBase && cfg.apiBase.trim() ? cfg.apiBase.replace(/\/$/, "") : "";
  const headers = { "Content-Type": "application/json" };
  // 已登录走 X-Auth-Token; 未登录回落开发期隔离键
  if (auth?.token) headers["X-Auth-Token"] = auth.token;
  else headers["X-Owner-User-Id"] = cfg.ownerId;
  const res = await fetch(base + path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  if (!res.ok) throw new Error(`${method} ${path} -> ${res.status}`);
  return res.json();
}

// 本地互动记录内存态（mock 模式下 confirm/reject/correct/记互动 用）
const _mockFeedback = {};   // talent_id -> status
const _mockInter = JSON.parse(JSON.stringify(INTERACTIONS));

// —— 统一 API（业务视图只认这一层）——
export const api = {
  async listTalents(keyword = "") {
    if (useMock()) {
      let list = TALENTS.slice();
      if (keyword) list = list.filter((t) => t.name.includes(keyword) || (t.company || "").includes(keyword) || (t.skills || []).some((s) => s.includes(keyword)));
      return list;
    }
    return http("/talents" + (keyword ? `?keyword=${encodeURIComponent(keyword)}` : ""));
  },

  async getTalent(id) {
    if (useMock()) return TALENTS.find((t) => t.id === Number(id)) || null;
    return http(`/talents/${id}`);
  },

  async getInteractions(id) {
    // 真实后端目前无「按人查互动」的 GET 接口（见接口差距分析），live 下可展示空
    if (useMock()) return _mockInter[id] || [];
    return [];
  },

  async addInteraction(id, body) {
    if (useMock()) {
      (_mockInter[id] = _mockInter[id] || []).unshift({ ...body, occurred_at: body.occurred_at || new Date().toISOString() });
      return { ok: true };
    }
    return http(`/talents/${id}/interaction`, { method: "POST", body });
  },

  async listPositions() {
    if (useMock()) return POSITIONS.filter((p) => p.is_active);
    return http("/positions");
  },

  async setPosition(body) {
    if (useMock()) {
      const existing = POSITIONS.find((p) => p.position_name === body.position_name);
      if (existing) { existing.jd_text = body.jd_text || existing.jd_text; existing.is_active = true; return existing; }
      const p = { id: POSITIONS.length + 1, ...body, is_active: true };
      POSITIONS.push(p); return p;
    }
    return http("/positions", { method: "POST", body });
  },

  // 两阶段推荐: 返回 {phase: "final"|"preview", computing, top_n, ...}
  async recommend(positionName) {
    if (useMock()) {
      const r = computeRecommend(positionName);
      r.phase = "final"; r.computing = false; r.cached = true;
      for (const list of [r.top3, r.top10, r.top_n]) for (const it of list) if (_mockFeedback[it.talent_id]) it.status = _mockFeedback[it.talent_id];
      return r;
    }
    return http(`/recommend/compute?position_name=${encodeURIComponent(positionName)}`, { method: "POST" });
  },

  // 轮询精算结果: {status: done|running|failed|idle, phase, top_n, ...}
  async recommendResult(positionName) {
    return http(`/recommend/result?position_name=${encodeURIComponent(positionName)}`);
  },

  async feedback(body) {
    if (useMock()) { if (body.action === "confirm") _mockFeedback[body.talent_id] = "confirmed"; if (body.action === "reject") _mockFeedback[body.talent_id] = "rejected"; return { ok: true }; }
    return http("/recommend/feedback", { method: "POST", body });
  },

  async health() {
    if (useMock()) return { status: "mock" };
    return http("/health");
  },

  // —— 飞书扫码登录 ——
  authRedirectUri() {
    // 扫码/授权成功后飞书重定向回 SPA 回调路由(hash 路由, ?code 挂在 hash 内)
    return `${location.origin}/#/auth/callback`;
  },
  qrcodeUrl() {
    const cfg = getCfg();
    const base = cfg.apiBase && cfg.apiBase.trim() ? cfg.apiBase.replace(/\/$/, "") : "";
    return `${base}/auth/feishu/qrcode?redirect_uri=${encodeURIComponent(this.authRedirectUri())}`;
  },
  // 授权页 URL(在桌面端新窗口打开 -> 飞书官方页显示二维码 ->
  // 手机扫码确认 -> 电脑上的该窗口自动跳回本站回调, 登录态落在当前浏览器)
  async feishuLoginUrl() {
    return http(`/auth/feishu/url?redirect_uri=${encodeURIComponent(this.authRedirectUri())}`);
  },
  async feishuLogin(code) {
    return http("/auth/feishu/login", { method: "POST", body: { code } });
  },
  async me() {
    return http("/auth/me");
  },
  async bindTtc(body) {
    return http("/auth/ttc/bind", { method: "POST", body });
  },
  async syncTtc() {
    return http("/sync/ttc", { method: "POST" });
  },
};
