// DOM 工具: 转义 / 主视图容器 / loading / 日期格式化
import { t, getLocale } from "../state.js";

export const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

export const view = () => document.getElementById("view");

export function loading() { view().innerHTML = `<div class="spinner">${t("loading")}…</div>`; }

export function fmtDate(v) {
  if (!v) return "—";
  const d = new Date(v);
  return isNaN(d) ? String(v) : d.toLocaleDateString(getLocale());
}
