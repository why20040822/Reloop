// 全局共享状态 + i18n 助手(单一可变源, 视图/路由共用)
import { getCfg, setCfg } from "../data/provider.js";
import { STRINGS } from "../i18n.js";

// —— 可变全局状态(跨视图共享, 集中在此避免模块级 let 的导入只读限制) ——
export const S = {
  CURRENT_POSITION: null,
  SORT_BY: "match",
  W_ACTIVITY: 0.5,
  W_MATCH: 0.5,
  homeSeq: 0,
};

let LOCALE = getCfg().locale || "zh-CN";

export function getLocale() { return LOCALE; }
export function setLocale(loc) { LOCALE = loc; setCfg({ locale: loc }); }

// i18n 取值(带 {var} 插值)
export const t = (k, vars) => {
  let s = (STRINGS[LOCALE] && STRINGS[LOCALE][k]) || STRINGS["zh-CN"][k] || k;
  if (vars) Object.entries(vars).forEach(([key, val]) => { s = s.replace(`{${key}}`, val); });
  return s;
};
