/**
 * Shared parsers utilities for the TTC candidate collector extension.
 *
 * These helpers are used across all platform-specific parsers to identify
 * candidate cards vs. UI noise, normalize URLs, and detect anti-bot pages.
 */

export const RISK_WORDS = [
  '安全验证', '请输入验证码', '访问过于频繁', '操作过于频繁',
  '异常访问', '请完成验证', '登录后查看', '账号登录', '登录后使用',
  '请登录', '滑块验证', '人机验证', '验证身份', '访问验证',
  'captcha', 'verify you are human'
];

export const NON_CANDIDATE_LABELS = [
  '桌面客户端', '下载APP', '下载 App', '下载客户端', '手机扫码',
  '打开APP', '打开 App', '登录', '注册', '帮助中心', '隐私政策',
  '用户协议', '职位管理', '招聘者', '企业服务'
];

export const CANDIDATE_EVIDENCE = /(\d+\s*岁|\d+\s*年|本科|硕士|博士|大专|统招|在职|离职|求职|期望|工作经历|教育经历|咨询|战略|品牌|产品|渠道|运营|市场|经理|总监|负责人)/;

export const SUPPORTED_HOSTS = [
  'zhipin.com', 'liepin.com', 'maimai.cn',
  'linkedin.com', '51job.com', 'zhaopin.com'
];

export function supportedHost(url) {
  try {
    const host = new URL(url).hostname;
    return SUPPORTED_HOSTS.some(domain => host === domain || host.endsWith('.' + domain));
  } catch {
    return false;
  }
}

export function looksLikeNonCandidateLabel(label) {
  const text = (label || '').replace(/\s+/g, '');
  return !text || NON_CANDIDATE_LABELS.some(word => text.includes(word.replace(/\s+/g, '')));
}

export function looksLikeCandidateText(text) {
  return CANDIDATE_EVIDENCE.test(text || '');
}

export function detectRisk(text, title, url) {
  const t = (text || '').toLowerCase();
  const titleL = (title || '').toLowerCase();
  const urlL = (url || '').toLowerCase();
  return RISK_WORDS.find(word =>
    t.includes(word.toLowerCase()) ||
    titleL.includes(word.toLowerCase()) ||
    urlL.includes(word.toLowerCase())
  ) || '';
}

export function normalizeUrl(url, base) {
  try {
    return new URL(url, base).href;
  } catch (_error) {
    return '';
  }
}

export function candidateUrlFrom(el) {
  if (!el) return '';
  const direct = el.matches && el.matches('a[href]') ? el : el.querySelector && el.querySelector('a[href]');
  if (direct && direct.href) return normalizeUrl(direct.href, location.href);
  const closest = el.closest && el.closest('a[href]');
  if (closest && closest.href) return normalizeUrl(closest.href, location.href);
  const attrs = ['data-url', 'data-href', 'data-link', 'data-path', 'data-target-url'];
  for (const attr of attrs) {
    const value = el.getAttribute && el.getAttribute(attr);
    if (value) return normalizeUrl(value, location.href);
  }
  if (el.dataset) {
    for (const value of Object.values(el.dataset)) {
      if (typeof value === 'string' && /\/|https?:|#/.test(value)) {
        const url = normalizeUrl(value, location.href);
        if (url) return url;
      }
    }
  }
  return '';
}

export function platformFromUrl(url) {
  try {
    const host = new URL(url).hostname;
    if (host.includes('zhipin.com')) return 'boss';
    if (host.includes('liepin.com')) return 'liepin';
    if (host.includes('maimai.cn')) return 'maimai';
    if (host.includes('linkedin.com')) return 'linkedin';
    if (host.includes('51job.com')) return '51job';
    if (host.includes('zhaopin.com')) return 'zhaopin';
  } catch {
    return 'generic';
  }
  return 'generic';
}

// Expose helpers on window so injected page scripts can use them.
if (typeof window !== 'undefined') {
  window.__TTC_PARSERS = window.__TTC_PARSERS || {};
  window.__TTC_PARSERS.common = {
    RISK_WORDS,
    NON_CANDIDATE_LABELS,
    CANDIDATE_EVIDENCE,
    SUPPORTED_HOSTS,
    supportedHost,
    looksLikeNonCandidateLabel,
    looksLikeCandidateText,
    detectRisk,
    normalizeUrl,
    candidateUrlFrom,
    platformFromUrl
  };
}
