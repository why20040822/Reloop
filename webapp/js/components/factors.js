// 双因子(活跃度+匹配度)展示组件: 条形图 + "为什么联系"文案
import { t } from "../state.js";

const FACTOR_KEYS = ["activity", "match"];
const factorLabel = (k) => t("factor_" + k);

// 双因子条形图(详情展开态)
export function dualFactorBars(bd) {
  return `<div class="dual-factors">${FACTOR_KEYS.map((k) => {
    const v = Math.max(0, Math.min(1, bd?.[k] ?? 0));
    return `<div class="df-item"><span class="df-label">${factorLabel(k)}</span><span class="df-bar"><span class="df-fill" style="width:${(v * 100).toFixed(0)}%"></span></span><span class="df-val">${v.toFixed(2)}</span></div>`;
  }).join("")}</div>`;
}

export function factorBars(bd) {
  return `<div class="factors">${FACTOR_KEYS.map((k) => {
    const v = Math.max(0, Math.min(1, bd?.[k] ?? 0));
    return `<div class="factor"><span>${factorLabel(k)}</span><span class="bar"><span class="fill" style="width:${(v * 100).toFixed(0)}%"></span></span><span class="fnum">${v.toFixed(2)}</span></div>`;
  }).join("")}</div>`;
}

export function whyReason(bd) {
  if (!bd) return "";
  const act = bd.activity ?? 0;
  const match = bd.match ?? 0;
  if (act >= match) return `${t("factor_activity")} ${act.toFixed(2)} ${t("why_high")}；${t("factor_match")} ${match.toFixed(2)} ${t("why_low")}。`;
  return `${t("factor_match")} ${match.toFixed(2)} ${t("why_high")}；${t("factor_activity")} ${act.toFixed(2)} ${t("why_low")}。`;
}
