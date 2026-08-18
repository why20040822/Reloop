(function () {
/**
 * TTC (app.ttcadvisory.com) parser.
 *
 * TTC is a React SPA. The parser tries several strategies:
 * 1. Look for links to candidate detail pages (/app/talent/{id}).
 * 2. Extract structured sections from the detail page.
 * 3. Fall back to generic card detection on list/search pages.
 */

const { candidateUrlFrom, looksLikeCandidateText, looksLikeNonCandidateLabel, normalizeUrl } = window.__TTC_PARSERS.common;

function isTtcPage(url) {
  try {
    return /app\.ttcadvisory\.com/.test(new URL(url).hostname);
  } catch {
    return false;
  }
}

function extractTtcPersonLeadsId(url) {
  try {
    const u = new URL(url);
    if (u.protocol !== 'https:' || u.hostname !== 'app.ttcadvisory.com') return null;
    const match = u.pathname.match(/\/app\/talent\/((?:PL)?\d+)/i);
    if (match) return match[1];
    const hashMatch = u.hash.match(/\/talent\/((?:PL)?\d+)/i);
    if (hashMatch) return hashMatch[1];
  } catch {
    return null;
  }
  return null;
}

function findTtcCandidateLinks(maxItems) {
  const seen = new Map();
  const add = (url, label, score) => {
    if (!url) return;
    const clean = normalizeUrl(url, location.href);
    if (!clean || clean === location.href) return;
    const compactLabel = (label || '').replace(/\s+/g, '');
    const negativeLabel = /(下载APP|下载App|登录|注册|帮助|隐私|协议|企业服务|职位管理|招聘者)/;
    const negativeUrl = /(download|desktop|client|app-download|appdownload|login|register|privacy|terms|help|about|contact|setting|app\.html|\/app\/\/$)/i;
    if (negativeLabel.test(compactLabel) || negativeUrl.test(clean)) return;
    const old = seen.get(clean);
    if (!old || score > old.score) seen.set(clean, {url: clean, label: String(label || clean).slice(0, 80), score});
  };

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
  const cardSelectors = [
    '[class*=candidate]', '[class*=talent]', '[class*=card]', '[class*=item]',
    '[role=row]', '[role=link]', '[data-url]', '[data-href]'
  ];
  const cards = Array.from(document.querySelectorAll(cardSelectors.join(','))).slice(0, 300);
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

  return Array.from(seen.values()).sort((a, b) => b.score - a.score).slice(0, maxItems);
}

function extractTtcSections() {
  const text = document.body ? document.body.innerText : '';
  const headings = ['基本信息', '个人简介', '工作经历', '教育经历', '项目经历', '技能', '求职意向'];
  const sections = [];
  const addSection = (heading, lines) => {
    if (!heading || !lines.length) return;
    sections.push({heading, text: lines.join('\n')});
  };

  // Top basic info.
  const basic = [];
  const h1 = document.querySelector('h1');
  if (h1) basic.push(h1.innerText.trim());
  const nameEl = document.querySelector('[class*=name]');
  if (nameEl) {
    const t = nameEl.innerText.trim();
    if (t && t.length <= 40 && !basic.includes(t)) basic.push(t);
  }
  const bodyStart = text.split('\n').slice(0, 80);
  for (const line of bodyStart) {
    const t = line.trim();
    if (/\d+岁/.test(t) || /\d+年经验/.test(t) || /本科|硕士|博士|大专/.test(t) || /1[3-9]\d{9}/.test(t)) {
      if (!basic.includes(t)) basic.push(t);
    }
  }
  if (basic.length) {
    sections.push({heading: '基础信息', text: basic.slice(0, 15).join('\n')});
  }

  // Section aggregation by heading.
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
      if (/^(展开|收起|查看全部|更多|编辑|删除|举报|分享|收藏|投递|立即沟通|聊一聊|发简历|下载|导出)$/.test(t)) continue;
      if (t.length >= 8 && !currentLines.includes(t)) currentLines.push(t);
    }
  }
  pushCurrent();

  if (sections.length <= 1) return {sections: [{heading: '全文', text}]};
  return {sections};
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
})();
