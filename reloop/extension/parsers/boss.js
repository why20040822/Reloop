/**
 * BOSS 直聘 (zhipin.com) parser.
 */

import { candidateUrlFrom, looksLikeCandidateText, looksLikeNonCandidateLabel, normalizeUrl } from './common.js';

export function isBossPage(url) {
  return /zhipin\.com/.test(new URL(url).hostname) && /geek|jobhunter|candidate|resume/i.test(url);
}

export function isBossManagementPage(url) {
  return /zhipin\.com/.test(new URL(url).hostname) &&
    /\/chat\/|\/manage\/|\/tools\/|\/prop\/|\/vip\/|\/data\/|\/job_list\/| ka=action/.test(url);
}

export function extractBossSections() {
  const text = document.body ? document.body.innerText : '';
  const headings = ['个人优势', '工作经历', '项目经历', '教育经历', '技能专长', '求职期望'];
  const sections = [];
  const addSection = (heading, lines) => {
    if (!heading || !lines.length) return;
    sections.push({heading, text: lines.join('\n')});
  };

  // 1. 顶部基础信息
  const basic = [];
  const h1 = document.querySelector('h1');
  if (h1) basic.push(h1.innerText.trim());
  const infoEls = document.querySelectorAll(
    '.info-label, .base-info, .job-info, [class*="info"] .text, [class*="base"] .text, .name-box .label'
  );
  for (const el of infoEls) {
    const t = (el.innerText || '').trim();
    if (t && t.length <= 80 && !basic.includes(t)) basic.push(t);
  }
  const bodyStart = text.split('\n').slice(0, 60);
  for (const line of bodyStart) {
    const t = line.trim();
    if (/\d+岁/.test(t) || /\d+年经验/.test(t) || /本科|硕士|博士/.test(t)) {
      if (!basic.includes(t)) basic.push(t);
    }
  }
  if (basic.length) {
    sections.push({heading: '基础信息', text: basic.slice(0, 12).join('\n')});
  }

  // 2. 按分节标题聚合
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
  let currentHeading = '';
  let currentLines = [];
  const pushCurrent = () => {
    if (currentHeading && currentLines.length) {
      addSection(currentHeading, currentLines);
    }
    currentHeading = '';
    currentLines = [];
  };
  while (walker.nextNode()) {
    const el = walker.currentNode;
    if (!el.innerText) continue;
    const t = el.innerText.trim();
    if (!t || t.length > 3000) continue;
    const isHeading = headings.includes(t) || headings.some(h => t.startsWith(h + ' '));
    if (isHeading && t.length <= 20) {
      pushCurrent();
      currentHeading = t.replace(/\s+/g, '');
      continue;
    }
    if (currentHeading) {
      if (/^(展开|收起|查看全部|更多|编辑|删除|举报|分享|收藏|投递|立即沟通|聊一聊|发简历)$/.test(t)) continue;
      if (t.length >= 8 && !currentLines.includes(t)) currentLines.push(t);
    }
  }
  pushCurrent();

  if (sections.length <= 1) return {sections: [{heading: '全文', text}]};
  return {sections};
}

export function findBossCandidateLinks(maxItems) {
  const seen = new Map();
  const add = (url, label, score) => {
    if (!url) return;
    const clean = normalizeUrl(url, location.href);
    if (!clean) return;
    if (clean === location.href) return;
    const compactLabel = (label || '').replace(/\s+/g, '');
    const negativeLabel = /(桌面客户端|下载APP|下载App|下载客户端|打开APP|打开App|登录|注册|帮助|隐私|协议|企业服务|职位管理|招聘者)/;
    const negativeUrl = /(download|desktop|client|app-download|appdownload|login|register|privacy|terms|help|about|contact|company|job\/detail|chat|message|setting|job_list|app\.html|\/app\/)/i;
    if (negativeLabel.test(compactLabel) || negativeUrl.test(clean)) return;
    const old = seen.get(clean);
    if (!old || score > old.score) seen.set(clean, {url: clean, label: String(label || clean).slice(0, 80), score});
  };

  const bossNegative = /(\/chat\/|\/message\/|\/manage\/|\/tools\/|\/prop\/|\/vip\/|\/data\/|\/company\/|\/job_detail\/)/i;
  for (const a of document.querySelectorAll('a[href*="/geek/"], a[href*="/jobhunter/"]')) {
    const href = a.href ? a.href.split('#')[0] : '';
    if (!href || bossNegative.test(href)) continue;
    const pathMatch = href.match(/\/(geek|jobhunter)\/([^/]+)/);
    if (!pathMatch) continue;
    const segment = pathMatch[2];
    if (/^(manage|recommend|tools|prop|data|vip|setting|help)$/i.test(segment)) continue;
    const text = (a.innerText || a.textContent || '').replace(/\s+/g, ' ').trim();
    const card = a.closest('[class*="card"], [class*="item"], [class*="geek"], [class*="recommend"], li');
    const cardText = card ? (card.innerText || '').replace(/\s+/g, ' ').trim() : '';
    if (!looksLikeCandidateText(cardText || text)) continue;
    let score = 10;
    if (/\d+岁/.test(cardText || text)) score += 3;
    if (/\d+年/.test(cardText || text)) score += 3;
    if (/(本科|硕士|博士)/.test(cardText || text)) score += 2;
    add(href, text || cardText.slice(0, 60), score);
  }

  // Fallback to generic card selectors.
  const cardSelectors = [
    '[class*=candidate]', '[class*=resume]', '[class*=geek]', '[class*=talent]',
    '[class*=jobhunter]', '[class*=recommend]', '[class*=profile]', '[class*=person]',
    '[class*=user]', '[class*=card]', '[class*=item]', '[role=link]', '[data-url]',
    '[data-href]', '[data-link]', '[data-path]'
  ];
  const cards = Array.from(document.querySelectorAll(cardSelectors.join(','))).slice(0, 300);
  for (const card of cards) {
    const cardText = (card.innerText || card.textContent || '').replace(/\s+/g, ' ').trim();
    if (cardText.length < 8 || cardText.length > 2500) continue;
    if (looksLikeNonCandidateLabel(cardText)) continue;
    if (!looksLikeCandidateText(cardText)) continue;
    const href = candidateUrlFrom(card);
    if (!href || !href.startsWith(location.origin)) continue;
    let score = 4;
    if (/geek|jobhunter|candidate|resume/i.test(href)) score += 4;
    if (/\d+\s*岁|\d+\s*年|本科|硕士|博士/.test(cardText)) score += 4;
    if (/工作经历|教育经历|求职|期望|在职|离职/.test(cardText)) score += 2;
    if (score < 6) continue;
    add(href, cardText.slice(0, 80), score);
  }

  return Array.from(seen.values()).sort((a, b) => b.score - a.score).slice(0, maxItems);
}

if (typeof window !== 'undefined') {
  window.__TTC_PARSERS = window.__TTC_PARSERS || {};
  window.__TTC_PARSERS.boss = {
    isBossPage,
    isBossManagementPage,
    extractBossSections,
    findBossCandidateLinks
  };
}
