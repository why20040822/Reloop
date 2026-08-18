// 可切换数据层：mock（内置真实感样本）↔ http（真实 Reloop FastAPI）
// 切换只改配置，业务视图不动。后端上公网 + 开 CORS 后，把 apiBase 填成后端地址即可切真数据。
import { TALENTS, POSITIONS, INTERACTIONS, computeRecommend } from "./mock.js";

const LS_KEY = "reloop.cfg";
const DEFAULT_CFG = {
  // 空 = mock 模式；填后端地址（如 https://your-reloop.example.com）= 真实 API 模式
  apiBase: "",
  // 数据隔离键（后端 X-Owner-User-Id）。默认填已同步 358 人的 open_id
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
export function isMock() { return !getCfg().apiBase.trim(); }

// —— HTTP 客户端（真实模式）——
async function http(path, { method = "GET", body } = {}) {
  const cfg = getCfg();
  const res = await fetch(cfg.apiBase.replace(/\/$/, "") + path, {
    method,
    headers: {
      "Content-Type": "application/json",
      "X-Owner-User-Id": cfg.ownerId,
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${method} ${path} -> ${res.status}`);
  return res.json();
}

// 本地互动记录内存态（mock 模式下 confirm/reject/correct/记互动 用）
const _mockFeedback = {};   // talent_id -> status
const _mockInter = JSON.parse(JSON.stringify(INTERACTIONS));

// —— 统一 API（业务视图只认这一层）——
export const api = {
  async listTalents(keyword = "") {
    if (isMock()) {
      let list = TALENTS.slice();
      if (keyword) list = list.filter((t) => t.name.includes(keyword) || (t.company || "").includes(keyword) || (t.skills || []).some((s) => s.includes(keyword)));
      return list;
    }
    return http("/talents" + (keyword ? `?keyword=${encodeURIComponent(keyword)}` : ""));
  },

  async getTalent(id) {
    if (isMock()) return TALENTS.find((t) => t.id === Number(id)) || null;
    return http(`/talents/${id}`);
  },

  async getInteractions(id) {
    // 真实后端目前无「按人查互动」的 GET 接口（见接口差距分析），mock 下可展示
    if (isMock()) return _mockInter[id] || [];
    return [];
  },

  async addInteraction(id, body) {
    if (isMock()) {
      (_mockInter[id] = _mockInter[id] || []).unshift({ ...body, occurred_at: body.occurred_at || new Date().toISOString() });
      return { ok: true };
    }
    return http(`/talents/${id}/interaction`, { method: "POST", body });
  },

  async listPositions() {
    if (isMock()) return POSITIONS.filter((p) => p.is_active);
    return http("/positions");
  },

  async setPosition(body) {
    if (isMock()) {
      const existing = POSITIONS.find((p) => p.position_name === body.position_name);
      if (existing) { existing.jd_text = body.jd_text || existing.jd_text; existing.is_active = true; return existing; }
      const p = { id: POSITIONS.length + 1, ...body, is_active: true };
      POSITIONS.push(p); return p;
    }
    return http("/positions", { method: "POST", body });
  },

  async recommend(positionName) {
    if (isMock()) {
      const r = computeRecommend(positionName);
      // 应用本地反馈状态
      for (const list of [r.top3, r.top10, r.top_n]) for (const it of list) if (_mockFeedback[it.talent_id]) it.status = _mockFeedback[it.talent_id];
      return r;
    }
    return http(`/recommend/compute?position_name=${encodeURIComponent(positionName)}`, { method: "POST" });
  },

  async feedback(body) {
    if (isMock()) { if (body.action === "confirm") _mockFeedback[body.talent_id] = "confirmed"; if (body.action === "reject") _mockFeedback[body.talent_id] = "rejected"; return { ok: true }; }
    return http("/recommend/feedback", { method: "POST", body });
  },

  async health() {
    if (isMock()) return { status: "mock" };
    return http("/health");
  },
};
