/**
 * 脉脉 (maimai.cn) parser.
 *
 * Currently uses generic card/link detection tuned for Maimai list layouts.
 */

import { candidateUrlFrom, looksLikeCandidateText, looksLikeNonCandidateLabel, normalizeUrl } from './common.js';

export function isMaimaiPage(url) {
  return /maimai\.cn/.test(new URL(url).hostname);
}

export function findMaimaiCandidateLinks(maxItems) {
  const seen = new Map();
  const add = (url, label, score) => {
    if (!url) return;
    const clean = normalizeUrl(url, location.href);
    if (!clean || clean === location.href) return;
    const compactLabel = (label || '').replace(/\s+/g, '');
    const negativeLabel = /(桌面客户端|下载APP|下载App|下载客户端|打开APP|打开App|登录|注册|帮助|隐私|协议|企业服务|职位管理|招聘者)/;
    const negativeUrl = /(download|desktop|client|app-download|appdownload|login|register|privacy|terms|help|about|contact|company|job\/detail|chat|message|setting|job_list|app\.html|\/app\/)/i;
    if (negativeLabel.test(compactLabel) || negativeUrl.test(clean)) return;
    const old = seen.get(clean);
    if (!old || score > old.score) seen.set(clean, {url: clean, label: String(label || clean).slice(0, 80), score});
  };

  const positive = /(profile|user|talent|candidate|resume)/i;
  const evidence = /(\d+\s*岁|\d+\s*年|本科|硕士|博士|大专|咨询|战略|品牌|产品|渠道)/;
  const maimaiSelectors = [
    'a[href*="/profile/"]',
    'a[href*="/user/"]',
    'a[href*="/talent/"]',
    'a[href*="/candidate/"]',
    'a[href*="/resume/"]'
  ];
  for (const a of document.querySelectorAll(maimaiSelectors.join(','))) {
    const href = a.href || '';
    const text = (a.innerText || a.textContent || '').replace(/\s+/g, ' ').trim();
    if (!href || href === location.href || !href.startsWith(location.origin)) continue;
    const card = a.closest('[class*=card],[class*=item],[class*=profile],[class*=user],[class*=talent],li');
    const cardText = card ? (card.innerText || '').replace(/\s+/g, ' ').trim() : text;
    if (looksLikeNonCandidateLabel(text)) continue;
    if (!looksLikeCandidateText(cardText) && !positive.test(href)) continue;
    let score = 6;
    if (/\/(profile|user|talent)\//.test(href)) score += 2;
    if (evidence.test(cardText || text)) score += 3;
    if (card) score += 2;
    add(href, text || cardText.slice(0, 80), score);
  }

  const cardSelectors = [
    '[class*=candidate]', '[class*=resume]', '[class*=talent]', '[class*=profile]', '[class*=person]',
    '[class*=user]', '[class*=card]', '[class*=item]', '[role=link]', '[data-url]', '[data-href]'
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
    if (positive.test(href)) score += 4;
    if (evidence.test(cardText)) score += 4;
    if (/工作经历|教育经历|求职|期望|在职|离职/.test(cardText)) score += 2;
    if (score < 6) continue;
    add(href, cardText.slice(0, 80), score);
  }

  return Array.from(seen.values()).sort((a, b) => b.score - a.score).slice(0, maxItems);
}

export function extractMaimaiSections() {
  const text = document.body ? document.body.innerText : '';
  const headings = ['个人资料', '工作经历', '教育经历', '项目经历', '技能', '自我评价', '个人简介'];
  const sections = [];
  const addSection = (heading, lines) => {
    if (!heading || !lines.length) return;
    sections.push({heading, text: lines.join('\n')});
  };

  // 顶部基础信息
  const basic = [];
  const h1 = document.querySelector('h1');
  if (h1) basic.push(h1.innerText.trim());
  const nameEl = document.querySelector('[class*=name]');
  if (nameEl) {
    const t = nameEl.innerText.trim();
    if (t && t.length <= 40 && !basic.includes(t)) basic.push(t);
  }
  const bodyStart = text.split('\n').slice(0, 60);
  for (const line of bodyStart) {
    const t = line.trim();
    if (/\d+岁/.test(t) || /\d+年经验/.test(t) || /本科|硕士|博士|大专/.test(t)) {
      if (!basic.includes(t)) basic.push(t);
    }
  }
  if (basic.length) {
    sections.push({heading: '基础信息', text: basic.slice(0, 12).join('\n')});
  }

  // 按分节标题聚合
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
      if (/^(展开|收起|查看全部|更多|编辑|删除|举报|分享|收藏|投递|立即沟通|聊一聊|发简历|下载)$/.test(t)) continue;
      if (t.length >= 8 && !currentLines.includes(t)) currentLines.push(t);
    }
  }
  pushCurrent();

  if (sections.length <= 1) return {sections: [{heading: '全文', text}]};
  return {sections};
}

if (typeof window !== 'undefined') {
  window.__TTC_PARSERS = window.__TTC_PARSERS || {};
  window.__TTC_PARSERS.maimai = { isMaimaiPage, findMaimaiCandidateLinks, extractMaimaiSections };
}
