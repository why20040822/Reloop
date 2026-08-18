/**
 * TTC (app.ttcadvisory.com) parser.
 *
 * TTC is a React SPA. The parser tries several strategies:
 * 1. Look for links to candidate detail pages (/app/talent/{id}).
 * 2. Extract structured sections from the detail page.
 * 3. Fall back to generic card detection on list/search pages.
 */

import { candidateUrlFrom, looksLikeCandidateText, looksLikeNonCandidateLabel, normalizeUrl, extractSections, makeLinkCollector, CARD_SELECTORS } from './common.js';

export function isTtcPage(url) {
  try {
    return /app\.ttcadvisory\.com/.test(new URL(url).hostname);
  } catch {
    return false;
  }
}

export function extractTtcPersonLeadsId(url) {
  try {
    const u = new URL(url);
    const match = u.pathname.match(/\/app\/talent\/(\d+)/);
    if (match) return match[1];
    const hashMatch = u.hash.match(/\/talent\/(\d+)/);
    if (hashMatch) return hashMatch[1];
  } catch {
    return null;
  }
  return null;
}

export function findTtcCandidateLinks(maxItems) {
  const {add, links} = makeLinkCollector();

  // Strategy 1: direct detail-page links.
  for (const a of document.querySelectorAll('a[href*="/app/talent/"], a[href*="/talent/"]')) {
    const href = a.href || '';
    const text = (a.innerText || a.textContent || '').replace(/\s+/g, ' ').trim();
    if (!href || href === location.href) continue;
    const pid = extractTtcPersonLeadsId(href);
    if (!pid) continue;
    const card = a.closest('[class*=card],[class*=item],[class*=row],[class*=candidate],[class*=talent],li,tr');
    const cardText = card ? (card.innerText || '').replace(/\s+/g, ' ').trim() : text;
    if (looksLikeNonCandidateLabel(text)) continue;
    let score = 8;
    if (looksLikeCandidateText(cardText || text)) score += 3;
    if (card) score += 2;
    add(href, text || cardText.slice(0, 80), score);
  }

  // Strategy 2: clickable rows/cards that open a detail drawer.
  const rowSelectors = [
    '[class*=candidate-list] [class*=row]',
    '[class*=talent-list] [class*=item]',
    '[class*=search-result] [class*=card]',
    '[data-person-leads-id]',
    '[data-candidate-id]',
    '[data-talent-id]'
  ];
  for (const el of document.querySelectorAll(rowSelectors.join(','))) {
    const pid = el.getAttribute('data-person-leads-id') || el.getAttribute('data-candidate-id') || el.getAttribute('data-talent-id');
    const href = pid ? normalizeUrl(`/app/talent/${pid}`, location.href) : candidateUrlFrom(el);
    const cardText = (el.innerText || '').replace(/\s+/g, ' ').trim();
    if (!cardText || looksLikeNonCandidateLabel(cardText)) continue;
    if (!looksLikeCandidateText(cardText) && !pid) continue;
    let score = 5;
    if (pid) score += 4;
    if (looksLikeCandidateText(cardText)) score += 3;
    add(href, cardText.slice(0, 80), score);
  }

  // Strategy 3: generic cards that contain TTC-like candidate evidence.
  const cards = Array.from(document.querySelectorAll(CARD_SELECTORS)).slice(0, 300);
  for (const card of cards) {
    const cardText = (card.innerText || card.textContent || '').replace(/\s+/g, ' ').trim();
    if (cardText.length < 8 || cardText.length > 2500) continue;
    if (looksLikeNonCandidateLabel(cardText)) continue;
    if (!looksLikeCandidateText(cardText)) continue;
    const href = candidateUrlFrom(card);
    if (!href) continue;
    let score = 4;
    if (extractTtcPersonLeadsId(href)) score += 4;
    if (/\d+年|本科|硕士|博士|经理|总监|负责人/.test(cardText)) score += 2;
    if (score < 6) continue;
    add(href, cardText.slice(0, 80), score);
  }

  return links(maxItems);
}

const TTC_HEADINGS = ['基本信息', '个人简介', '工作经历', '教育经历', '项目经历', '技能', '求职意向'];

export function extractTtcSections() {
  return extractSections(TTC_HEADINGS, {scanLines: 80, basicMax: 15, withPhone: true});
}

if (typeof window !== 'undefined') {
  window.__TTC_PARSERS = window.__TTC_PARSERS || {};
  window.__TTC_PARSERS.ttc = {
    isTtcPage,
    extractTtcPersonLeadsId,
    findTtcCandidateLinks,
    extractTtcSections,
  };
}
