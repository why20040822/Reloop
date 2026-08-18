// Reloop 触达工作台 — 真实感 mock 数据（严格对齐后端接口契约）
// TalentOut / PositionOut / RecommendItemOut(score_breakdown 五因子) / InteractionRecord
// 数据设计上覆盖多样场景：不同 base / 公司等级 / 学历 / 稀缺技能 / 活跃度 / 有无互动。

const days = (n) => new Date(Date.now() - n * 86400000).toISOString();

// —— 人才库（对齐 TalentOut）——
export const TALENTS = [
  { id: 101, source_id: "T101", name: "张韵", base_location: "上海", company: "字节跳动", position: "商业分析师", work_years: 6.5, education: "硕士", skills: ["SQL", "Python", "大模型", "商业洞察"], value_score: 0.86, tendency_score: 0.78, last_active_at: days(1), tags: ["商业分析师", "数据分析"] },
  { id: 102, source_id: "T102", name: "李哲", base_location: "深圳", company: "腾讯", position: "数据产品经理", work_years: 8.25, education: "本科", skills: ["数据产品", "SQL", "增长"], value_score: 0.79, tendency_score: 0.5, last_active_at: days(3), tags: ["数据产品", "商业分析师"] },
  { id: 103, source_id: "T103", name: "王楠", base_location: "北京", company: "美团", position: "商业分析", work_years: 4.0, education: "硕士", skills: ["Python", "AB测试", "商业洞察"], value_score: 0.72, tendency_score: 0.62, last_active_at: days(2), tags: ["商业分析师"] },
  { id: 104, source_id: "T104", name: "陈曦", base_location: "杭州", company: "阿里巴巴", position: "策略分析师", work_years: 5.5, education: "硕士", skills: ["SQL", "策略", "量化"], value_score: 0.81, tendency_score: null, last_active_at: days(9), tags: ["策略分析师", "商业分析师"] },
  { id: 105, source_id: "T105", name: "刘思远", base_location: "上海", company: "拼多多", position: "商业分析师", work_years: 3.2, education: "本科", skills: ["SQL", "增长", "商业分析"], value_score: 0.64, tendency_score: 0.71, last_active_at: days(1), tags: ["商业分析师"] },
  { id: 106, source_id: "T106", name: "赵一鸣", base_location: "北京", company: "快手", position: "HRBP", work_years: 7.0, education: "本科", skills: ["组织发展", "招聘", "OD"], value_score: 0.6, tendency_score: 0.4, last_active_at: days(14), tags: ["HRBP"] },
  { id: 107, source_id: "T107", name: "孙悦", base_location: "广州", company: "网易", position: "商业数据分析", work_years: 2.5, education: "本科", skills: ["SQL", "可视化"], value_score: 0.55, tendency_score: 0.58, last_active_at: days(5), tags: ["商业分析师", "数据分析"] },
  { id: 108, source_id: "T108", name: "周render", base_location: "深圳", company: "华为", position: "算法工程师", work_years: 9.0, education: "博士", skills: ["算法", "大模型", "AI训练师"], value_score: 0.93, tendency_score: 0.35, last_active_at: days(20), tags: ["算法工程师"] },
  { id: 109, source_id: "T109", name: "吴倩", base_location: "上海", company: "小红书", position: "增长分析师", work_years: 4.8, education: "硕士", skills: ["增长", "SQL", "商业分析"], value_score: 0.7, tendency_score: 0.66, last_active_at: days(2), tags: ["商业分析师", "增长"] },
  { id: 110, source_id: "T110", name: "郑凯", base_location: "杭州", company: "网易严选", position: "商业分析师", work_years: 5.0, education: "本科", skills: ["SQL", "供应链", "商业分析"], value_score: 0.68, tendency_score: 0.52, last_active_at: days(6), tags: ["商业分析师"] },
  { id: 111, source_id: "T111", name: "马丽", base_location: "北京", company: "京东", position: "HRBP", work_years: 6.0, education: "硕士", skills: ["招聘", "薪酬", "HRBP"], value_score: 0.66, tendency_score: 0.6, last_active_at: days(4), tags: ["HRBP"] },
  { id: 112, source_id: "T112", name: "冯昊", base_location: "成都", company: "字节跳动", position: "商业分析师", work_years: 3.8, education: "本科", skills: ["SQL", "Python", "商业分析"], value_score: 0.62, tendency_score: 0.74, last_active_at: days(1), tags: ["商业分析师"] },
];

// —— 岗位（对齐 PositionOut）——
export const POSITIONS = [
  { id: 1, position_name: "商业分析师", jd_text: "数据分析 SQL Python 业务洞察 商业分析", is_active: true },
  { id: 2, position_name: "HRBP", jd_text: "组织发展 招聘 OD 员工关系", is_active: true },
];

// —— 互动记录（历史关系 + 活跃信号来源）——
export const INTERACTIONS = {
  101: [ { interaction_type: "call", count: 2, summary: "初步沟通职业规划，反馈积极", occurred_at: days(4) }, { interaction_type: "message", count: 5, summary: "微信保持联系", occurred_at: days(1) } ],
  102: [ { interaction_type: "interview", count: 1, summary: "一面通过，等二面排期", occurred_at: days(10) } ],
  105: [ { interaction_type: "message", count: 3, summary: "了解到有跳槽意愿", occurred_at: days(2) } ],
  109: [ { interaction_type: "call", count: 1, summary: "电话约喝咖啡", occurred_at: days(3) } ],
};

// —— 联系理由 & 因子解读文案（离线时后端走模板；这里造真实感样本）——
const REASONS = {
  101: "近期高度活跃且与商业分析师岗位高度匹配，今天优先联系。",
  102: "历史关系深、面试在途，建议约短电话推进。",
  103: "岗位匹配度高、价值分不错，值得主动触达。",
  104: "人才价值突出，但最近活跃度偏低，可先发消息唤醒。",
  105: "有明确跳槽意愿且活跃，窗口期建议尽快联系。",
  109: "增长背景匹配，近期活跃，适合本周内接触。",
  112: "求职意愿强、活跃度高，虽资历尚浅但性价比高。",
};

// 五因子键：activity / match / value / relationship / tendency
const BREAKDOWN = {
  101: { activity: 0.94, match: 0.92, value: 0.86, relationship: 0.71, tendency: 0.78 },
  102: { activity: 0.62, match: 0.85, value: 0.79, relationship: 0.88, tendency: 0.5 },
  103: { activity: 0.7, match: 0.83, value: 0.72, relationship: 0.2, tendency: 0.62 },
  104: { activity: 0.34, match: 0.8, value: 0.81, relationship: 0.2, tendency: 0.5 },
  105: { activity: 0.9, match: 0.74, value: 0.64, relationship: 0.45, tendency: 0.71 },
  109: { activity: 0.82, match: 0.76, value: 0.7, relationship: 0.5, tendency: 0.66 },
  110: { activity: 0.5, match: 0.72, value: 0.68, relationship: 0.2, tendency: 0.52 },
  112: { activity: 0.9, match: 0.7, value: 0.62, relationship: 0.2, tendency: 0.74 },
  107: { activity: 0.55, match: 0.68, value: 0.55, relationship: 0.2, tendency: 0.58 },
};

// 加权乘法模型（复刻后端 priority.weighted_product，权重同 .env 默认）
const W = { activity: 0.3, match: 0.4, value: 0.15, relationship: 0.1, tendency: 0.05 };
function weightedProduct(b) {
  return Math.pow(Math.max(b.activity, 1e-6), W.activity)
    * Math.pow(Math.max(b.match, 1e-6), W.match)
    * Math.pow(Math.max(b.value, 1e-6), W.value)
    * Math.pow(Math.max(b.relationship, 1e-6), W.relationship)
    * Math.pow(Math.max(b.tendency, 1e-6), W.tendency);
}

// 依据岗位关键词粗筛 + 精算，产出 RecommendResultOut 结构
export function computeRecommend(positionName) {
  const pos = POSITIONS.find((p) => p.position_name === positionName) || POSITIONS[0];
  const kw = pos.position_name;
  const pool = TALENTS.length;
  const shortlisted = TALENTS.filter((t) =>
    (t.tags || []).some((x) => x.includes(kw) || kw.includes(x)) ||
    (t.position && (t.position.includes(kw) || kw.includes(t.position)))
  );
  const ranked = shortlisted
    .map((t) => {
      const b = BREAKDOWN[t.id] || { activity: 0.4, match: 0.6, value: t.value_score ?? 0.5, relationship: 0.2, tendency: t.tendency_score ?? 0.5 };
      return { t, b, score: weightedProduct(b) };
    })
    .filter((r) => r.score >= 0.2)
    .sort((a, b) => b.score - a.score);

  const items = ranked.map((r, i) => ({
    rank: i + 1,
    talent_id: r.t.id,
    name: r.t.name,
    company: r.t.company,
    position: r.t.position,
    base_location: r.t.base_location,
    work_years: r.t.work_years,
    education: r.t.education,
    score: Math.round(r.score * 10000) / 10000,
    score_breakdown: Object.fromEntries(Object.entries(r.b).map(([k, v]) => [k, Math.round(v * 10000) / 10000])),
    last_active_at: r.t.last_active_at,
    contact_reason: REASONS[r.t.id] || `近期活跃且与${kw}岗位匹配，建议尽快联系。`,
    status: "pending",
  }));

  return {
    run_id: "run_" + Math.random().toString(16).slice(2, 6).toUpperCase(),
    position: pos.position_name,
    generated_at: new Date().toISOString(),
    total_pool: pool,
    shortlisted: shortlisted.length,
    top3: items.slice(0, 3),
    top10: items.slice(0, 10),
    top_n: items,
  };
}
