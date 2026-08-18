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

const BOSS_SECTION_HEADINGS = [
  '个人优势', '工作经历', '经历概览', '项目经历', '教育经历', '技能专长',
  '求职期望', '求职意向', '个人简介', '基本信息'
];

/**
 * 推荐页简历面板只显示「经历概览」一个分节；用多个“YYYY.MM - YYYY.MM/至今”
 * 时间段作为第二证据，避免漏掉推荐页候选人。
 */
function hasOverviewEvidence(text) {
  if (!text.includes('经历概览')) return false;
  const periods = text.match(/(?:19|20)\d{2}[./-]\d{1,2}\s*[-–—~～至]\s*(?:至今|(?:19|20)\d{2})/g);
  return Boolean(periods && periods.length >= 2);
}

function normalizedLine(value) {
  return String(value || '').replace(/\s+/g, '').replace(/[：:（(]\d+[）)]?$/, '');
}

function visibleElement(element) {
  if (!element || !element.getBoundingClientRect) return false;
  const rect = element.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0;
}

/**
 * BOSS frequently renders a candidate drawer inside /web/chat/index. Find the
 * smallest visible ancestor that contains multiple resume sections so chat
 * history and the candidate list are not sent to ingestion.
 */
export function findBossProfileRoot() {
  if (!document.body) return null;
  const markerElements = [];
  const elements = document.body.querySelectorAll('h1,h2,h3,h4,h5,h6,div,section,span,p');
  for (const element of elements) {
    if (markerElements.length >= 80) break;
    const text = String(element.innerText || '').trim();
    if (text.length > 30 || !visibleElement(element)) continue;
    const normalized = normalizedLine(text);
    if (BOSS_SECTION_HEADINGS.some(heading => normalized === heading || normalized.startsWith(heading))) {
      markerElements.push(element);
    }
  }

  let best = null;
  for (const marker of markerElements) {
    let candidate = marker.parentElement;
    for (let depth = 0; candidate && candidate !== document.body && depth < 10; depth += 1) {
      const text = String(candidate.innerText || '').trim();
      if (text.length >= 200 && text.length <= 60_000 && visibleElement(candidate)) {
        const markerCount = BOSS_SECTION_HEADINGS.filter(heading => text.includes(heading)).length;
        const identityEvidence = /(\d+\s*岁|\d+\s*年|本科|硕士|博士|大专|在职|离职|经理|总监|负责人)/.test(text);
        if ((markerCount >= 2 || hasOverviewEvidence(text)) && identityEvidence) {
          const score = markerCount * 100_000 - text.length;
          if (!best || score > best.score) best = {element: candidate, score, text};
        }
      }
      candidate = candidate.parentElement;
    }
  }
  return best ? best.element : null;
}

export function extractBossProfileText() {
  const root = findBossProfileRoot();
  return root ? String(root.innerText || '').trim() : '';
}

export function extractBossSections() {
  const profileText = extractBossProfileText();
  const text = profileText || (document.body ? document.body.innerText : '');
  const sections = [];
  const addSection = (heading, lines) => {
    if (!heading || !lines.length) return;
    sections.push({heading, text: lines.join('\n')});
  };

  // Parse rendered lines instead of walking every ancestor/child innerText.
  // The latter duplicates experience blocks many times on BOSS React pages.
  const uiNoiseLine = /^(全文|在线简历|附件简历|展开|收起|查看全部|更多|编辑|删除|举报|分享|收藏|投递|立即沟通|聊一聊|发简历)$/;
  const basic = [];
  let currentHeading = '';
  let currentLines = [];
  const pushCurrent = () => {
    if (currentHeading && currentLines.length) {
      addSection(currentHeading, currentLines);
    }
    currentHeading = '';
    currentLines = [];
  };
  for (const rawLine of text.split('\n')) {
    const line = rawLine.replace(/\s+/g, ' ').trim();
    if (!line || uiNoiseLine.test(line)) continue;
    const normalized = normalizedLine(line);
    const heading = BOSS_SECTION_HEADINGS.find(
      item => normalized === item || (normalized.startsWith(item) && normalized.length <= item.length + 4)
    );
    if (heading) {
      pushCurrent();
      // 推荐页的「经历概览」就是工作经历列表，统一成下游解析器认识的标题。
      currentHeading = heading === '经历概览' ? '工作经历' : heading;
      continue;
    }
    if (currentHeading) {
      if (/^(展开|收起|查看全部|更多|编辑|删除|举报|分享|收藏|投递|立即沟通|聊一聊|发简历)$/.test(line)) continue;
      if (line.length >= 2 && !currentLines.includes(line)) currentLines.push(line);
    } else if (basic.length < 20 && !basic.includes(line)) {
      basic.push(line);
    }
  }
  pushCurrent();

  if (basic.length) sections.unshift({heading: '基础信息', text: basic.join('\n')});
  // 清洗后的全文：去掉「全文」等面板标签行，避免后端把标签当成姓名。
  const cleanedText = text
    .split('\n')
    .map(rawLine => rawLine.replace(/\s+/g, ' ').trim())
    .filter(line => line && !uiNoiseLine.test(line))
    .join('\n');
  if (sections.length <= 1) {
    return {
      sections,
      raw_text: cleanedText,
      profile_detected: Boolean(profileText)
    };
  }
  return {sections, raw_text: cleanedText, profile_detected: Boolean(profileText)};
}

/**
 * 推荐页/聊天页简历抽屉的姓名在分节容器之外的头部，findBossProfileRoot 选不到。
 * 在抽屉祖先范围内找 [class*=name] 元素，或「xx先生/女士」行，单独提取姓名。
 */
export function extractBossCandidateName() {
  const root = findBossProfileRoot();
  if (!root) return '';
  const looksLikeName = (value) => {
    const text = String(value || '').replace(/\s+/g, '');
    return /^[一-龥·A-Za-z*]{2,10}(先生|女士)?$/.test(text) &&
      !/公司|职位|招聘|规范|猎头|企业|团队|简历|沟通|推荐/.test(text);
  };
  // 抽屉容器优先：在 drawer/dialog/sider 范围内枚举所有 [class*=name]，
  // 取离分节根最近且形似姓名的。头部可能不在根的祖先链上（兄弟分支）。
  const drawer = root.closest('[class*=drawer], [class*=dialog], [class*=modal], [class*=sider], [class*=slide], [class*=resume]');
  const scopes = [];
  if (drawer) scopes.push(drawer);
  let scope = root;
  for (let depth = 0; scope && scope !== document.body && depth < 6; depth += 1) {
    scopes.push(scope);
    scope = scope.parentElement;
  }
  for (const s of scopes) {
    const candidates = s.querySelectorAll('[class*=name]');
    for (const el of candidates) {
      if (!visibleElement(el)) continue;
      const firstLine = String(el.innerText || '').split('\n')[0].trim();
      if (looksLikeName(firstLine)) return firstLine;
    }
  }
  // 兜底：分节根之前相邻区域的「X先生/X女士」或 2-4 字中文名。
  let header = root.previousElementSibling;
  for (let i = 0; header && i < 3; i += 1, header = header.previousElementSibling) {
    const lines = String(header.innerText || '').split('\n').map(l => l.trim()).filter(Boolean);
    for (const line of lines.slice(0, 5)) {
      if (looksLikeName(line)) return line;
    }
  }
  return '';
}

/**
 * 诊断用：收集抽屉范围内所有 [class*=name] 元素的 class 与文本，
 * 随采集 payload 上云（parsed_json.boss_name_debug），用于定位真实姓名元素。
 * BOSS 页面打开 DevTools 会强制退出，只能靠插件自报结构。
 */
export function collectBossNameDebug() {
  const root = findBossProfileRoot();
  if (!root) return {error: 'no_profile_root'};
  const drawer = root.closest('[class*=drawer], [class*=dialog], [class*=modal], [class*=sider], [class*=slide], [class*=resume]');
  const scopes = [];
  if (drawer) scopes.push(drawer);
  let scope = root;
  for (let depth = 0; scope && scope !== document.body && depth < 6; depth += 1) {
    scopes.push(scope);
    scope = scope.parentElement;
  }
  const seen = new Set();
  const elements = [];
  for (const s of scopes) {
    for (const el of s.querySelectorAll('[class*=name]')) {
      if (elements.length >= 20) break;
      const cls = String(el.className || '').slice(0, 80);
      const text = String(el.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 60);
      const key = cls + '|' + text;
      if (seen.has(key)) continue;
      seen.add(key);
      elements.push({cls, text, visible: visibleElement(el)});
    }
  }
  // 分节根上方兄弟节点的前几行文本（头部候选区）
  const siblings = [];
  let header = root.previousElementSibling;
  for (let i = 0; header && i < 3; i += 1, header = header.previousElementSibling) {
    siblings.push({
      cls: String(header.className || '').slice(0, 80),
      text: String(header.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 120)
    });
  }
  return {
    drawer_cls: drawer ? String(drawer.className || '').slice(0, 80) : '',
    root_cls: String(root.className || '').slice(0, 80),
    elements,
    siblings
  };
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
    findBossProfileRoot,
    extractBossProfileText,
    extractBossSections,
    extractBossCandidateName,
    collectBossNameDebug,
    findBossCandidateLinks
  };
}
