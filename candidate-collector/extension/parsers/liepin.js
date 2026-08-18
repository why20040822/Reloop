/**
 * 猎聘 (liepin.com) parser.
 */

import { candidateUrlFrom, looksLikeCandidateText, looksLikeNonCandidateLabel, extractSections, makeLinkCollector, CARD_SELECTORS } from './common.js';

export function isLiepinPage(url) {
  return /liepin\.com/.test(new URL(url).hostname);
}

export function findLiepinCandidateLinks(maxItems) {
  const {add, links} = makeLinkCollector();

  const positive = /(resume|candidate|profile|jobhunter)/i;
  const evidence = /(\d+\s*岁|\d+\s*年|本科|硕士|博士|大专|咨询|战略|品牌|产品|渠道)/;
  const liepinSelectors = [
    'a[href*="/resume/"]',
    'a[href*="/candidate/"]',
    'a[href*="/profile/"]',
    'a[href*="/jobhunter/"]'
  ];
  for (const a of document.querySelectorAll(liepinSelectors.join(','))) {
    const href = a.href || '';
    const text = (a.innerText || a.textContent || '').replace(/\s+/g, ' ').trim();
    if (!href || href === location.href || !href.startsWith(location.origin)) continue;
    const card = a.closest('[class*=card],[class*=item],[class*=resume],[class*=candidate],li');
    const cardText = card ? (card.innerText || '').replace(/\s+/g, ' ').trim() : text;
    if (looksLikeNonCandidateLabel(text)) continue;
    if (!looksLikeCandidateText(cardText) && !positive.test(href)) continue;
    let score = 6;
    if (/\/(resume|candidate)\//.test(href)) score += 2;
    if (evidence.test(cardText || text)) score += 3;
    if (card) score += 2;
    add(href, text || cardText.slice(0, 80), score);
  }

  const cards = Array.from(document.querySelectorAll(CARD_SELECTORS)).slice(0, 300);
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

  return links(maxItems);
}

export function extractLiepinSections() {
  return extractSections(LIEPIN_HEADINGS);
}

const LIEPIN_HEADINGS = ['个人优势', '工作经历', '项目经历', '教育经历', '技能证书', '求职意向', '自我评价'];

if (typeof window !== 'undefined') {
  window.__TTC_PARSERS = window.__TTC_PARSERS || {};
  window.__TTC_PARSERS.liepin = { isLiepinPage, findLiepinCandidateLinks, extractLiepinSections };
}
