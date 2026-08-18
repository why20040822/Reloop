/**
 * 脉脉 (maimai.cn) parser.
 *
 * Currently uses generic card/link detection tuned for Maimai list layouts.
 */

import { candidateUrlFrom, looksLikeCandidateText, looksLikeNonCandidateLabel, extractSections, makeLinkCollector, CARD_SELECTORS } from './common.js';

export function isMaimaiPage(url) {
  return /maimai\.cn/.test(new URL(url).hostname);
}

const MAIMAI_HEADINGS = ['个人资料', '工作经历', '教育经历', '项目经历', '技能', '自我评价', '个人简介'];

export function extractMaimaiSections() {
  return extractSections(MAIMAI_HEADINGS);
}

export function findMaimaiCandidateLinks(maxItems) {
  const {add, links} = makeLinkCollector();

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

if (typeof window !== 'undefined') {
  window.__TTC_PARSERS = window.__TTC_PARSERS || {};
  window.__TTC_PARSERS.maimai = { isMaimaiPage, findMaimaiCandidateLinks, extractMaimaiSections };
}
