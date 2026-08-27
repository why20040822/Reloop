// Section Cards — KPI 统计卡行(对应 shadcn dashboard-01 section-cards.tsx:
// 内容区第一屏 = 关键指标卡片行, 随后才是图表/表格)
import { t } from "../state.js";

// reco: 推荐结果(含 total_pool/shortlisted); pending: 待确认条数
export function sectionCards(reco, items) {
  const pending = (items || []).filter((i) => (i.status || "pending") === "pending").length;
  const cards = [
    { label: t("stat_pool"), value: reco.total_pool ?? "—" },
    { label: t("stat_short"), value: reco.shortlisted ?? (items || []).length },
    { label: t("stat_pending") || "待确认", value: pending },
  ];
  return `<div class="stats">${cards.map((c) => `<div class="stat"><span>${c.label}</span><strong>${c.value}</strong></div>`).join("")}</div>`;
}
