const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

let mode = 'v2';
let queue = [];
let currentIndex = -1;
let currentDetail = null;

function toast(msg, ok = true) {
  const el = $('toast');
  el.textContent = msg;
  el.style.background = ok ? '#0d6f63' : '#a3342f';
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 2500);
}

async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  const j = await r.json().catch(() => ({ detail: r.statusText }));
  if (!r.ok) throw new Error(j.detail || j.error || 'request failed');
  return j;
}

function setMode(m) {
  mode = m;
  $('tab-v2').classList.toggle('active', m === 'v2');
  $('tab-v1').classList.toggle('active', m === 'v1');
  currentIndex = -1;
  currentDetail = null;
  loadQueue();
}

async function loadQueue() {
  try {
    const endpoint = mode === 'v2' ? '/api/review/queue' : '/api/review-v1/queue';
    const data = await api(endpoint + '?limit=50');
    queue = data.items || [];
    $('queue-count').textContent = data.count || 0;
    renderQueue();
    if (queue.length && currentIndex < 0) selectItem(0);
    else if (!queue.length) clearDetail();
  } catch (e) {
    toast(e.message, false);
  }
}

function renderQueue() {
  const container = $('queue-list');
  if (!queue.length) {
    container.innerHTML = '<div class="empty">暂无待复核记录</div>';
    return;
  }
  container.innerHTML = queue.map((item, idx) => {
    const active = idx === currentIndex ? 'active' : '';
    const name = esc(item.name || '未识别');
    const sub = esc([item.current_company, item.current_title].filter(Boolean).join(' · ')) || '公司/职位待核';
    return `<div class="queue-item ${active}" onclick="selectItem(${idx})"><b>${name}</b><small>${sub}</small></div>`;
  }).join('');
}

async function selectItem(idx) {
  currentIndex = idx;
  renderQueue();
  const item = queue[idx];
  if (!item) return;
  const id = item.id;
  $('current-index').textContent = `${idx + 1} / ${queue.length}`;
  try {
    const endpoint = mode === 'v2' ? `/api/review/${id}` : `/api/review-v1/${id}`;
    currentDetail = await api(endpoint);
    renderDetail(id);
  } catch (e) {
    toast(e.message, false);
  }
}

function clearDetail() {
  $('attachment-preview').innerHTML = '<div class="empty">选择左侧记录查看附件</div>';
  $('raw-text').textContent = '选择左侧记录查看文本';
  $('review-form').reset();
  $('work-experiences').innerHTML = '';
  $('confidence-summary').textContent = '';
  document.querySelectorAll('.conf-badge').forEach(b => { b.textContent = ''; b.className = 'conf-badge'; });
}

function confidenceClass(c) {
  if (c === null || c === undefined || c === '') return '';
  const v = parseFloat(c);
  if (v >= 0.8) return 'high';
  if (v >= 0.5) return 'mid';
  return 'low';
}

function renderDetail(id) {
  const candidate = currentDetail.candidate || {};
  const confidences = {};
  (candidate.field_confidences || []).forEach(fc => confidences[fc.field] = fc.confidence);

  // Attachment preview
  const attUrl = mode === 'v2' ? `/api/review/${id}/attachment` : `/api/review-v1/${id}/attachment`;
  const mime = candidate.attachment_mime_type || 'application/pdf';
  if (mime.startsWith('image/')) {
    $('attachment-preview').innerHTML = `<img src="${attUrl}" alt="附件">`;
  } else {
    $('attachment-preview').innerHTML = `<iframe src="${attUrl}"></iframe>`;
  }

  // Raw text
  $('raw-text').textContent = candidate.raw_text || currentDetail.raw_text || '（无文本）';

  // Form fields
  const setField = (key, val) => {
    const el = $(key);
    if (el) el.value = val || '';
    const badge = document.querySelector(`.conf-badge[data-field="${key}"]`);
    if (badge) {
      const c = confidences[key];
      if (c !== undefined && c !== '') {
        badge.textContent = Math.round(parseFloat(c) * 100) + '%';
        badge.className = 'conf-badge ' + confidenceClass(c);
      } else {
        badge.textContent = '';
        badge.className = 'conf-badge';
      }
    }
  };

  setField('name', candidate.name);
  setField('phone', candidate.phone);
  setField('email', candidate.email);
  setField('current_company', candidate.current_company);
  setField('current_title', candidate.current_title);
  setField('school', candidate.school);
  setField('expected_salary', candidate.expected_salary);

  // Education
  const edu = candidate.education || {};
  $('education_school').value = edu.school || '';
  $('education_degree').value = edu.degree || '';
  $('education_major').value = edu.major || '';
  $('education_graduation_year').value = edu.graduation_year || '';

  // Work experiences
  renderExperiences(candidate.work_experiences || []);

  // Summary
  const pc = candidate.parse_confidence;
  $('confidence-summary').textContent = pc !== null && pc !== undefined ? `整体置信度 ${Math.round(pc * 100)}%` : '';
}

function renderExperiences(exps) {
  const container = $('work-experiences');
  container.innerHTML = exps.map((e, idx) => `
    <div class="exp-group" data-idx="${idx}">
      <input class="exp-company" placeholder="公司" value="${esc(e.company || '')}">
      <input class="exp-role" placeholder="职位" value="${esc(e.role || '')}">
      <div class="row">
        <input class="exp-period" placeholder="时间段" value="${esc(e.period || '')}" style="flex:1">
        <button type="button" class="secondary" onclick="removeExperience(${idx})">删除</button>
      </div>
    </div>
  `).join('');
}

function addExperience() {
  const container = $('work-experiences');
  const idx = container.children.length;
  const div = document.createElement('div');
  div.className = 'exp-group';
  div.dataset.idx = idx;
  div.innerHTML = `
    <input class="exp-company" placeholder="公司">
    <input class="exp-role" placeholder="职位">
    <div class="row">
      <input class="exp-period" placeholder="时间段" style="flex:1">
      <button type="button" class="secondary" onclick="removeExperience(${idx})">删除</button>
    </div>
  `;
  container.appendChild(div);
}

function removeExperience(idx) {
  const groups = Array.from(document.querySelectorAll('.exp-group'));
  if (groups[idx]) groups[idx].remove();
}

function collectCorrections() {
  const corrections = {};
  ['name', 'phone', 'email', 'current_company', 'current_title', 'school', 'expected_salary'].forEach(key => {
    const el = $(key);
    if (el && el.value.trim()) corrections[key] = el.value.trim();
  });

  const exps = [];
  document.querySelectorAll('.exp-group').forEach(g => {
    const company = g.querySelector('.exp-company').value.trim();
    const role = g.querySelector('.exp-role').value.trim();
    const period = g.querySelector('.exp-period').value.trim();
    if (company || role || period) exps.push({ company, role, period });
  });
  if (exps.length) corrections.work_experiences = exps;

  const eduSchool = $('education_school').value.trim();
  const eduDegree = $('education_degree').value.trim();
  const eduMajor = $('education_major').value.trim();
  const eduYear = $('education_graduation_year').value.trim();
  if (eduSchool || eduDegree || eduMajor || eduYear) {
    corrections.education = {};
    if (eduSchool) corrections.education.school = eduSchool;
    if (eduDegree) corrections.education.degree = eduDegree;
    if (eduMajor) corrections.education.major = eduMajor;
    if (eduYear) corrections.education.graduation_year = parseInt(eduYear, 10);
  }

  return corrections;
}

async function approve() {
  if (!currentDetail) return;
  const id = queue[currentIndex].id;
  const corrections = collectCorrections();
  try {
    const endpoint = mode === 'v2' ? `/api/review/${id}/approve` : `/api/review-v1/${id}/approve`;
    const resp = await api(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(corrections),
    });
    toast(resp.action === 'approved' ? '已通过并写入飞书' : '已更新');
    queue.splice(currentIndex, 1);
    if (currentIndex >= queue.length) currentIndex = queue.length - 1;
    renderQueue();
    if (currentIndex >= 0) selectItem(currentIndex);
    else clearDetail();
  } catch (e) {
    toast(e.message, false);
  }
}

function skip() {
  if (currentIndex + 1 < queue.length) selectItem(currentIndex + 1);
  else toast('已到最后一条');
}

function reject() {
  $('reject-dialog').showModal();
}

function closeReject() {
  $('reject-dialog').close();
}

async function confirmReject() {
  if (!currentDetail) return;
  const id = queue[currentIndex].id;
  const reason = $('reject-reason').value.trim();
  try {
    const endpoint = mode === 'v2' ? `/api/review/${id}/reject` : `/api/review-v1/${id}/reject`;
    await api(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason }),
    });
    toast('已驳回');
    $('reject-dialog').close();
    $('reject-reason').value = '';
    queue.splice(currentIndex, 1);
    if (currentIndex >= queue.length) currentIndex = queue.length - 1;
    renderQueue();
    if (currentIndex >= 0) selectItem(currentIndex);
    else clearDetail();
  } catch (e) {
    toast(e.message, false);
  }
}

loadQueue();
