/* ═══════════════════════════════════════════
   로또 대시보드 JavaScript
   ═══════════════════════════════════════════ */

/* ── 로또 독립 유틸: app.js 의존 최소화 ── */
const _testlottoResolveApiUrl = (typeof resolveApiUrl === 'function')
    ? resolveApiUrl
    : function(path) { return path; };

const _testlottoBrainDisplayNames = {
  stat: '🧚 통계요정',
  markov: '🌊 흐름술사',
  review: '📖 복습왕',
};

const _testlottoBrainDescriptions = {
  stat: '빈도·끝수·이월수 (미래예측)',
  markov: '전이·동반출현 (미래예측)',
  review: '전회차 복습 학습형 (미래예측)',
};

function testlottoGetBrainDisplayName(tag) {
  return _testlottoBrainDisplayNames[tag] || tag;
}

function testlottoGetBrainDescription(tag) {
  return _testlottoBrainDescriptions[tag] || '';
}

// ── 탭 전환 ──
function switchTestlottoTab(tabName) {
  document.querySelectorAll('.lotto-tab-content').forEach((el) => { el.style.display = 'none'; });
  document.querySelectorAll('.lotto-sub-tab').forEach((el) => { el.classList.remove('active'); });
  const target = document.getElementById('lotto-tab-' + tabName);
  if (target) target.style.display = 'block';
  const btn = document.querySelector(`[data-lotto-tab="${tabName}"]`);
  if (btn) btn.classList.add('active');

  if (tabName === 'predictions') {
    initTestlottoDrawSearch();
  }
  if (tabName === 'stats') loadStats();
  if (tabName === 'draws') loadDraws();
}

// ── 회차 검색 + 저장 예측(6두뇌 탭) ──
let _testlottoDrawList = [];
let _testlottoDrawDates = {};
let _testlottoPredRowsCache = null;
let _testlottoDetailDrawNo = null;
let _testlottoDetailRows = null;
let _testlottoPredFetchSeq = 0;
let _testlottoCurrentBrainTab = 'stat';

/** 역대 1·2·3등 조건 필터용 brain_tag 집합(null=미로드). */
let _testlottoBrainEliteTagSet = null;

/** 대시보드 brain_power → 태그별 맵(null=미구축). */
let _testlottoBrainPowerByTag = null;

function setLottoBrainPowerCache(brainPower) {
  const map = {};
  (brainPower || []).forEach((b) => {
    const k = String(b.brain || '').toLowerCase();
    if (k) map[k] = b;
  });
  _testlottoBrainPowerByTag = map;
}

async function ensureLottoBrainPowerLoaded() {
  if (_testlottoBrainPowerByTag) return;
  try {
    const res = await fetch(_testlottoResolveApiUrl('/api/testlotto/dashboard-summary'));
    if (!res.ok) return;
    const data = await res.json();
    setLottoBrainPowerCache(data.brain_power);
  } catch (e) {
    console.warn('brain_power cache:', e);
  }
}

/** 카톡 복사용: 해당 뇌 역대 1~5등 적중 한 줄(플레인 텍스트). */
function lottoKakaoBrainRecordLine(tag) {
  const m = _testlottoBrainPowerByTag || {};
  const b = m[String(tag).toLowerCase()] || {};
  const n1 = Number(b.rank1 || 0);
  const n2 = Number(b.rank2 || 0);
  const n3 = Number(b.rank3 || 0);
  const n4 = Number(b.rank4 || 0);
  const n5 = Number(b.rank5 || 0);
  return (
    `  📊 역대 전적: 🥇1등 ${n1}회 🥈2등 ${n2}회 🥉3등 ${n3}회 🎯4등 ${n4}회 ✅5등 ${n5}회\n`
  );
}

/** 역대 1~5등 적중 횟수 나노 한 줄(HTML). */
function lottoBrainTierNanoHtml(tag) {
  const m = _testlottoBrainPowerByTag || {};
  const b = m[String(tag).toLowerCase()];
  if (!b) return '';
  const n1 = Number(b.rank1 || 0);
  const n2 = Number(b.rank2 || 0);
  const n3 = Number(b.rank3 || 0);
  const n4 = Number(b.rank4 || 0);
  const n5 = Number(b.rank5 || 0);
  const txt = [n1, n2, n3, n4, n5].join('·');
  return (
    '<span class="lotto-brain-nano" title="역대 적중: 1등·2등·3등·4등·5등(3개일치)">' +
    txt +
    '</span>'
  );
}

const TESTLOTTO_BRAIN_LIST = [
  { tag: 'stat', name: '통계요정', icon: '🧚', color: '#3b82f6' },
  { tag: 'markov', name: '흐름술사', icon: '🌊', color: '#10b981' },
  { tag: 'review', name: '복습왕', icon: '📖', color: '#f59e0b' },
];

function lottoFormatDow(dateStr) {
  if (!dateStr) return '';
  try {
    const d = new Date(dateStr);
    const dows = ['일', '월', '화', '수', '목', '금', '토'];
    return dows[d.getDay()] || '';
  } catch (e) {
    return '';
  }
}

async function loadTestlottoDrawList() {
  try {
    const r = await fetch(_testlottoResolveApiUrl('/api/testlotto/predictions?limit=20000'));
    const data = await r.json();
    const rows = data && data.predictions ? data.predictions : [];
    _testlottoPredRowsCache = rows;
    const set = new Set(rows.map((p) => p.target_draw_no).filter((n) => n != null));

    const dr = await fetch(_testlottoResolveApiUrl('/api/testlotto/draws?limit=10000'));
    const dj = await dr.json();
    const draws = (dj && dj.draws) ? dj.draws : [];
    draws.forEach((d) => {
      if (d && d.draw_no != null && d.draw_no !== '') {
        const n = parseInt(d.draw_no, 10);
        if (Number.isFinite(n) && n > 0) {
          set.add(n);
          _testlottoDrawDates[n] = d.draw_date;
        }
      }
    });
    _testlottoDrawList = Array.from(set).filter((n) => Number.isFinite(n) && n > 0).sort((a, b) => b - a);

    const sel = document.getElementById('testlottoDrawSelect');
    if (sel) {
      sel.innerHTML = _testlottoDrawList.map((no) => {
        const date = _testlottoDrawDates[no] || '?';
        const dow = lottoFormatDow(date);
        return `<option value="${no}">${no}회 (${date} ${dow})</option>`;
      }).join('');
    }
    return true;
  } catch (e) {
    console.error('회차 목록 로드 실패:', e);
    return false;
  }
}

function initTestlottoDrawSearch() {
  const sel = document.getElementById('testlottoDrawSelect');
  if (!sel) return;
  if (_testlottoDrawList.length > 0) return;
  loadTestlottoDrawList().then(() => {
    if (!_testlottoDrawList.length) return;
    const latest = _testlottoDrawList[0];
    const input = document.getElementById('testlottoPredictDrawNo');
    if (input && !input.value) {
      input.value = latest;
      sel.value = String(latest);
      testlottoLoadSavedPrediction(latest);
    }
  });
}

function testlottoSelectDraw(drawNo) {
  const no = parseInt(drawNo, 10);
  if (!no) return;
  const input = document.getElementById('testlottoPredictDrawNo');
  if (input) input.value = String(no);
  testlottoLoadSavedPrediction(no, { softLoading: true });
}

/** 복습·학습 상세페이지 (새 탭) */
function testlottoOpenDetailPage() {
  const input = document.getElementById('testlottoPredictDrawNo');
  const drawNo = parseInt(input?.value, 10) || _testlottoDetailDrawNo || _testlottoDrawList[0] || 20;
  const q = `draw=${drawNo}&brain=stat&mode=single`;
  // /testlotto-detail 은 서버 재기동 후 사용; static 경로는 항상 동작
  const url = `/static/testlotto-detail.html?${q}`;
  const w = window.open(url, '_blank', 'noopener,noreferrer');
  if (!w) {
    window.location.href = url;
  }
}
window.testlottoOpenDetailPage = testlottoOpenDetailPage;

function testlottoNavDraw(delta) {
  if (!_testlottoDrawList.length) return;
  const input = document.getElementById('testlottoPredictDrawNo');
  const sel = document.getElementById('testlottoDrawSelect');
  const cur = input ? parseInt(input.value, 10) : NaN;
  const base = Number.isFinite(cur) ? cur : _testlottoDrawList[0];
  const idx = _testlottoDrawList.indexOf(base);
  const step = delta > 0 ? -1 : 1; // 최신순: 오른쪽(▶)은 과거로
  const nextIdx = Math.max(0, Math.min(_testlottoDrawList.length - 1, (idx >= 0 ? idx : 0) + step));
  const nextNo = _testlottoDrawList[nextIdx];
  if (input) input.value = String(nextNo);
  if (sel) sel.value = String(nextNo);
  testlottoLoadSavedPrediction(nextNo, { softLoading: true });
}

async function testlottoLoadSavedPrediction(drawNo, options) {
  const d = parseInt(drawNo, 10);
  const fromTab = options && options.fromTab;
  const softLoading = options && options.softLoading;
  const container = document.getElementById('testlottoPredictionResults');
  if (!container || !Number.isFinite(d) || d < 1) {
    return;
  }
  if (fromTab && _testlottoDetailDrawNo === d && Array.isArray(_testlottoDetailRows) && _testlottoDetailRows.length) {
    await renderPredictionsByBrain(d, _testlottoDetailRows);
    return;
  }
  const hasRichUi = !!container.querySelector('.lotto-brain-tabs, .lotto-result-header');
  const useSoftShell = !!(softLoading && hasRichUi);
  const seq = ++_testlottoPredFetchSeq;
  if (useSoftShell) {
    container.classList.add('testlotto-results-pending');
    container.setAttribute('aria-busy', 'true');
  } else {
    container.classList.remove('testlotto-results-pending');
    container.removeAttribute('aria-busy');
    container.innerHTML = '<p style="color: #888;">로딩 중...</p>';
  }
  try {
    const r = await fetch(_testlottoResolveApiUrl('/api/testlotto/predictions/draw/' + d));
    const data = await r.json();
    if (seq !== _testlottoPredFetchSeq) {
      return;
    }
    const rows = (data && data.predictions) ? data.predictions : [];
    if (!rows.length) {
      _testlottoDetailDrawNo = null;
      _testlottoDetailRows = null;
      container.classList.remove('testlotto-results-pending');
      container.removeAttribute('aria-busy');
      container.innerHTML = `<p style="color: #888;">${d}회차 저장된 예측 없음. \"두뇌 예측\" 버튼으로 실행하세요.</p>`;
      return;
    }
    _testlottoDetailDrawNo = d;
    _testlottoDetailRows = rows;
    _testlottoPredRowsCache = (_testlottoPredRowsCache || []).filter((p) => parseInt(p.target_draw_no, 10) !== d);
    _testlottoPredRowsCache = rows.concat(_testlottoPredRowsCache || []);
    await renderPredictionsByBrain(d, rows);
  } catch (e) {
    if (seq !== _testlottoPredFetchSeq) {
      return;
    }
    container.classList.remove('testlotto-results-pending');
    container.removeAttribute('aria-busy');
    container.innerHTML = `<p style="color: #f88;">로드 실패: ${e.message}</p>`;
  }
}

function testlottoSwitchBrainTab(brainTag) {
  _testlottoCurrentBrainTab = String(brainTag || '').toLowerCase();
  const drawNo = parseInt(document.getElementById('testlottoPredictDrawNo').value, 10);
  if (drawNo) {
    testlottoLoadSavedPrediction(drawNo, { fromTab: true });
  }
}

function lottoMiniBallBg(num) {
  const n = parseInt(num, 10);
  if (!n) return '#555';
  if (n <= 10) return '#fbc400';
  if (n <= 20) return '#69c8f2';
  if (n <= 30) return '#ff7272';
  if (n <= 40) return '#aaa';
  return '#b0d840';
}

function renderMiniBall(num, isHit, extraClass) {
  const n = parseInt(num, 10);
  const bg = lottoMiniBallBg(n);
  const hitClass = isHit ? 'is-hit' : '';
  const ex = extraClass ? String(extraClass) : '';
  return `<span class="lotto-mini-ball ${hitClass} ${ex}" style="background:${bg};">${n}</span>`;
}

function renderBrainSetCard(row, idx) {
  const nums = [row.num1, row.num2, row.num3, row.num4, row.num5, row.num6].map((n) => parseInt(n, 10));
  const matched = row.matched_count;
  const bonus = row.bonus_matched;

  let rank = '';
  let rankClass = 'rank-none';
  if (matched === 6) { rank = '🏆 1등!'; rankClass = 'rank-1'; }
  else if (matched === 5 && bonus === 1) { rank = '🥈 2등'; rankClass = 'rank-2'; }
  else if (matched === 5) { rank = '🥉 3등'; rankClass = 'rank-3'; }
  else if (matched === 4) { rank = '4등'; rankClass = 'rank-4'; }
  else if (matched === 3) { rank = '5등'; rankClass = 'rank-5'; }
  else if (matched >= 0) { rank = '미당첨'; rankClass = 'rank-none'; }
  else { rank = '추첨 전'; rankClass = 'rank-pending'; }

  const actuals = [row.actual_1, row.actual_2, row.actual_3, row.actual_4, row.actual_5, row.actual_6].filter((x) => x != null);
  const actualSet = new Set(actuals.map((n) => parseInt(n, 10)));

  const ballsHtml = nums.map((n) => renderMiniBall(n, actualSet.has(n))).join('');

  let conf = '-';
  if (row.confidence != null && row.confidence !== '') {
    const v = Number(row.confidence);
    if (Number.isFinite(v)) {
      // DB가 0~1 또는 이미 % (예: 97.9) 둘 다 대응
      conf = (v <= 1 ? (v * 100) : v).toFixed(1) + '%';
    }
  }

  let sourceBadge = '';
  const reasoning = String(row.reasoning || '');
  const srcMatch = reasoning.match(/출처:(SEL4|V3)/);
  if (srcMatch) {
    const src = srcMatch[1];
    const srcClass = src === 'V3' ? 'lotto-set-src-v3' : 'lotto-set-src-sel4';
    const srcLabel = src === 'V3' ? 'v3 기여' : 'SEL4';
    sourceBadge = `<span class="lotto-set-source ${srcClass}">${srcLabel}</span>`;
  }

  return `
    <div class="lotto-set-card ${rankClass}">
      <div class="lotto-set-header">
        <span class="lotto-set-idx">#${idx}</span>
        <span class="lotto-set-rank">${rank}</span>
        ${sourceBadge}
        <span class="lotto-set-conf">신뢰도 ${conf}</span>
      </div>
      <div class="lotto-set-balls">${ballsHtml}</div>
    </div>
  `;
}

async function ensureBrainEliteTagsLoaded() {
  if (_testlottoBrainEliteTagSet !== null) {
    return true;
  }
  try {
    const r = await fetch(_testlottoResolveApiUrl('/api/testlotto/brain/elite-tags'));
    if (!r.ok) {
      throw new Error(String(r.status));
    }
    const data = await r.json();
    _testlottoBrainEliteTagSet = new Set((data.tags || []).map((t) => String(t).toLowerCase()));
    return true;
  } catch (e) {
    console.warn('brain elite-tags:', e);
    return false;
  }
}

async function testlottoOnEliteBrainToggle() {
  _testlottoBrainEliteTagSet = null;
  const d = _testlottoDetailDrawNo;
  const rows = _testlottoDetailRows;
  if (d && rows && rows.length) {
    await renderPredictionsByBrain(d, rows);
  }
}

async function renderPredictionsByBrain(drawNo, rows) {
  const container = document.getElementById('testlottoPredictionResults');
  if (!container) return;
  await ensureLottoBrainPowerLoaded();
  container.classList.remove('testlotto-results-pending');
  container.removeAttribute('aria-busy');
  const date = _testlottoDrawDates[drawNo] || '?';
  const dow = lottoFormatDow(date);
  const first = rows[0] || {};
  const hasActual = first.actual_1 != null;

  let actualHtml = '';
  if (hasActual) {
    const balls = [first.actual_1, first.actual_2, first.actual_3, first.actual_4, first.actual_5, first.actual_6];
    actualHtml = `
      <div class="lotto-actual-row">
        <span class="lotto-actual-label">실제 당첨번호:</span>
        <span class="lotto-actual-balls">
          ${balls.map((n) => renderMiniBall(n, false, 'is-actual')).join('')}
        </span>
        <span class="lotto-actual-bonus">+ 보너스 ${renderMiniBall(first.actual_bonus, false, 'is-actual is-bonus')}</span>
      </div>
    `;
  } else {
    actualHtml = '<div class="lotto-actual-row lotto-no-actual">아직 추첨 전입니다</div>';
  }

  const byBrain = {};
  rows.forEach((r) => {
    const tag = String(r.brain_tag || 'legacy').toLowerCase();
    if (!byBrain[tag]) byBrain[tag] = [];
    byBrain[tag].push(r);
  });

  const eliteCb = document.getElementById('testlottoEliteBrainToggle');
  const eliteOn = !!(eliteCb && eliteCb.checked);

  let brainListForTabs = TESTLOTTO_BRAIN_LIST;
  if (eliteOn) {
    const ok = await ensureBrainEliteTagsLoaded();
    if (ok) {
      brainListForTabs = TESTLOTTO_BRAIN_LIST.filter((b) => _testlottoBrainEliteTagSet.has(b.tag));
    }
  }

  if (eliteOn && brainListForTabs.length === 0) {
    container.innerHTML = `
      <div class="lotto-result-header">
        <h3>${drawNo}회 (${date} ${dow})</h3>
        ${actualHtml}
      </div>
      <p class="lotto-elite-empty">역대 (1등≥1·2등≥1·3등≥5 동시) 또는 3등만 15회 이상인 뇌가 없습니다. 필터를 끄면 전체를 볼 수 있습니다.</p>
    `;
    return;
  }

  if (!_testlottoCurrentBrainTab || _testlottoCurrentBrainTab === 'legacy') {
    _testlottoCurrentBrainTab = 'hyena';
  }
  const allowedTags = new Set(brainListForTabs.map((b) => b.tag));
  if (eliteOn && allowedTags.size && !allowedTags.has(_testlottoCurrentBrainTab)) {
    _testlottoCurrentBrainTab = brainListForTabs[0].tag;
  }
  if (!byBrain[_testlottoCurrentBrainTab]) {
    const firstTag = Object.keys(byBrain)[0];
    _testlottoCurrentBrainTab = firstTag || (brainListForTabs[0] && brainListForTabs[0].tag) || 'hyena';
  }

  const tabsHtml = brainListForTabs.map((b) => {
    const cnt = (byBrain[b.tag] || []).length;
    const active = b.tag === _testlottoCurrentBrainTab ? 'active' : '';
    const disabled = cnt === 0 ? 'disabled' : '';
    const nano = lottoBrainTierNanoHtml(b.tag);
    return `
      <button class="lotto-brain-tab ${active} ${disabled}"
              data-brain="${b.tag}"
              style="--brain-color: ${b.color};"
              onclick="testlottoSwitchBrainTab('${b.tag}')"
              ${disabled ? 'disabled' : ''}>
        <span class="lotto-brain-tab-head">
          <span class="lotto-brain-icon">${b.icon}</span>
          <span class="lotto-brain-name">${testlottoGetBrainDisplayName(b.tag)}</span>
          <span class="lotto-brain-cnt">${cnt}</span>
        </span>
        ${nano}
      </button>
    `;
  }).join('');

  const selectedRows = byBrain[_testlottoCurrentBrainTab] || [];
  const cardsHtml = selectedRows.length
    ? selectedRows.map((r, i) => renderBrainSetCard(r, i + 1)).join('')
    : '<p style="color:#888; padding: 16px;">이 두뇌는 이 회차에 예측 데이터가 없습니다.</p>';

  container.innerHTML = `
    <div class="lotto-result-header">
      <h3>${drawNo}회 (${date} ${dow})</h3>
      ${actualHtml}
    </div>
    <div class="lotto-brain-tabs">${tabsHtml}</div>
    <div class="lotto-brain-cards" id="hyodoBrainCards">${cardsHtml}</div>
  `;
}

/** 세트 순번(#1~#5) → 카톡용 이모지 */
const _testlottoKakaoSetEmoji = ['', '🥇', '🥈', '🥉', '4️⃣', '5️⃣'];

function lottoClipboardWriteText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(text);
  }
  return new Promise((resolve, reject) => {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    try {
      if (document.execCommand('copy')) {
        resolve();
      } else {
        reject(new Error('execCommand copy failed'));
      }
    } catch (e) {
      reject(e);
    } finally {
      document.body.removeChild(ta);
    }
  });
}

/**
 * 1군 두뇌예측: 현재 불러온 예측(_testlottoDetailRows)을 카카오톡용 텍스트로 복사.
 * 고적중 필터·뇌 탭 목록과 동일한 뇌 순서(TESTLOTTO_BRAIN_LIST)로 전 뇌 출력(화면은 한 탭만 보여도 전 뇌 포함).
 */
async function testlottoCopyKakaoText() {
  const rows = _testlottoDetailRows;
  const drawNo = _testlottoDetailDrawNo;
  if (!rows || !rows.length || !drawNo) {
    alert('먼저 회차를 선택한 뒤 "두뇌 예측"을 눌러 예측을 불러오세요.');
    return;
  }

  let brainListForTabs = TESTLOTTO_BRAIN_LIST;
  const eliteCb = document.getElementById('testlottoEliteBrainToggle');
  const eliteOn = !!(eliteCb && eliteCb.checked);
  if (eliteOn) {
    const ok = await ensureBrainEliteTagsLoaded();
    if (ok && _testlottoBrainEliteTagSet) {
      brainListForTabs = TESTLOTTO_BRAIN_LIST.filter((b) => _testlottoBrainEliteTagSet.has(b.tag));
    }
    if (brainListForTabs.length === 0) {
      alert('고적중 뇌만 필터가 켜져 있으나 표시할 뇌가 없습니다.');
      return;
    }
  }

  const byBrain = {};
  rows.forEach((r) => {
    const tag = String(r.brain_tag || 'legacy').toLowerCase();
    if (!byBrain[tag]) byBrain[tag] = [];
    byBrain[tag].push(r);
  });

  await ensureLottoBrainPowerLoaded();

  const first = rows[0] || {};
  const hasActual = first.actual_1 != null;
  const statusLabel = hasActual ? '추첨 후' : '추첨 전';

  let body = '';
  brainListForTabs.forEach((b) => {
    const list = byBrain[b.tag];
    if (!list || !list.length) {
      return;
    }
    body += '\n';
    body += testlottoGetBrainDisplayName(b.tag);
    body += '\n';
    list.forEach((row, i) => {
      const idx = i + 1;
      const emoji = _testlottoKakaoSetEmoji[idx] || '📌';
      const nums = [row.num1, row.num2, row.num3, row.num4, row.num5, row.num6].map((n) => {
        const v = parseInt(n, 10);
        return Number.isFinite(v) ? String(v).padStart(2, '0') : '00';
      });
      body += `  ${emoji} #${idx}  ${nums.join(' - ')}\n`;
    });
    body += lottoKakaoBrainRecordLine(b.tag);
  });

  if (!body.trim()) {
    alert('복사할 예측 행이 없습니다.');
    return;
  }

  const text = ''
    + '🎱 나의 지식 도서관 AI 예측\n'
    + '━━━━━━━━━━━━━━━━━━\n'
    + `📌 ${drawNo}회 (${statusLabel})\n`
    + '━━━━━━━━━━━━━━━━━━\n'
    + body
    + '\n━━━━━━━━━━━━━━━━━━\n'
    + '🧠 1군 6뇌 AI 예측 시스템\n'
    + '━━━━━━━━━━━━━━━━━━';

  try {
    await lottoClipboardWriteText(text);
    alert('📋 카톡용 텍스트가 복사되었습니다!');
  } catch (e) {
    console.warn('testlottoCopyKakaoText', e);
    alert('복사에 실패했습니다. 브라우저 권한·HTTPS를 확인하세요.');
  }
}

/** 1~5등 적중 요약 모달 — 읽기 전용 API 연동 */
let _testlottoTierWinsEscHandler = null;

function lottoCloseTierWinsModal() {
  const modal = document.getElementById('lottoTierWinsModal');
  if (modal) {
    modal.hidden = true;
    modal.setAttribute('aria-hidden', 'true');
  }
  if (_testlottoTierWinsEscHandler) {
    document.removeEventListener('keydown', _testlottoTierWinsEscHandler);
    _testlottoTierWinsEscHandler = null;
  }
}

function lottoTierWinsRankTitleClass(rank) {
  if (rank === 1) return 'lotto-tier-wins-rank-title lotto-tier-wins-rank-title--r1';
  if (rank === 2) return 'lotto-tier-wins-rank-title lotto-tier-wins-rank-title--r2';
  if (rank === 3) return 'lotto-tier-wins-rank-title lotto-tier-wins-rank-title--r3';
  if (rank === 4) return 'lotto-tier-wins-rank-title lotto-tier-wins-rank-title--r4';
  if (rank === 5) return 'lotto-tier-wins-rank-title lotto-tier-wins-rank-title--r5';
  return 'lotto-tier-wins-rank-title';
}

function lottoRenderTierWinsModalContent(data) {
  const body = document.getElementById('lottoTierWinsModalBody');
  const title = document.getElementById('lottoTierWinsModalTitle');
  if (!body || !title) return;
  const drawNo = data.draw_no;
  const dateHint = data.draw_date ? ` · ${data.draw_date}` : '';
  title.textContent = `${drawNo}회차 · 1~5등 적중 세트${dateHint}`;

  let actualLine = '';
  if (data.actual_numbers && data.actual_numbers.length === 6) {
    const balls = data.actual_numbers.map((n) => renderMiniBall(n, false)).join('');
    const bonusHtml = data.bonus != null
      ? `<span class="lotto-tier-wins-bonus-wrap">+ 보너스 ${renderMiniBall(data.bonus, false, 'is-bonus')}</span>`
      : '';
    actualLine = `
      <div class="lotto-tier-wins-actual">
        <span class="lotto-tier-wins-actual-label">실제 당첨번호</span>
        <span class="lotto-tier-wins-balls">${balls}</span>
        ${bonusHtml}
      </div>`;
  }

  const items = data.items || [];
  if (!items.length) {
    body.innerHTML = actualLine
      + '<p class="lotto-tier-wins-empty">이 회차에 저장된 1~5등 적중 예측이 없습니다. 미추첨·미채점이거나 해당 회차 예측이 없을 수 있습니다.</p>';
    return;
  }

  const byRank = { 1: [], 2: [], 3: [], 4: [], 5: [] };
  items.forEach((it) => {
    const rk = it.rank;
    if (byRank[rk]) byRank[rk].push(it);
  });

  const rankTitles = { 1: '1등', 2: '2등', 3: '3등', 4: '4등', 5: '5등' };
  let html = actualLine + '<div class="lotto-tier-wins-sections">';
  for (let r = 1; r <= 5; r++) {
    const list = byRank[r];
    if (!list.length) continue;
    html += `<section class="lotto-tier-wins-rank"><h3 class="${lottoTierWinsRankTitleClass(r)}">${rankTitles[r]}</h3><ul class="lotto-tier-wins-list">`;
    list.forEach((it) => {
      const nums = (it.nums || []).map((n) => renderMiniBall(n, false)).join('');
      const tag = String(it.brain_tag || '').toLowerCase();
      const brain = testlottoGetBrainDisplayName(tag);
      html += `<li class="lotto-tier-wins-item"><span class="lotto-tier-wins-brain">${brain}</span><span class="lotto-tier-wins-balls-row">${nums}</span></li>`;
    });
    html += '</ul></section>';
  }
  html += '</div>';
  body.innerHTML = html;
}

async function lottoRefreshTierWinsModalContent() {
  const input = document.getElementById('testlottoPredictDrawNo');
  const d = input ? parseInt(input.value, 10) : NaN;
  const body = document.getElementById('lottoTierWinsModalBody');
  const title = document.getElementById('lottoTierWinsModalTitle');
  const jump = document.getElementById('lottoTierWinsJumpInput');
  if (!body) return;
  if (!Number.isFinite(d) || d < 1) {
    body.innerHTML = '<p class="lotto-tier-wins-empty">회차가 올바르지 않습니다.</p>';
    return;
  }
  if (jump) jump.value = String(d);
  body.innerHTML = '<p class="lotto-tier-wins-loading">불러오는 중…</p>';
  if (title) title.textContent = `${d}회차 · 불러오는 중…`;
  try {
    const r = await fetch(_testlottoResolveApiUrl(`/api/testlotto/predictions/draw/${d}/tier-wins`));
    if (!r.ok) throw new Error(String(r.status));
    const data = await r.json();
    lottoRenderTierWinsModalContent(data);
    const dn = data && data.draw_no != null ? parseInt(data.draw_no, 10) : d;
    if (jump && Number.isFinite(dn)) jump.value = String(dn);
  } catch (e) {
    console.warn('tier-wins:', e);
    body.innerHTML = `<p class="lotto-tier-wins-error">불러오기 실패: ${String(e.message)}</p>`;
    if (title) title.textContent = `${d}회차`;
  }
}

async function testlottoOpenTierWinsModal() {
  const input = document.getElementById('testlottoPredictDrawNo');
  const jump = document.getElementById('lottoTierWinsJumpInput');
  const d = input ? parseInt(input.value, 10) : NaN;
  if (!Number.isFinite(d) || d < 1) {
    alert('회차를 입력하거나 목록에서 선택하세요.');
    return;
  }
  const modal = document.getElementById('lottoTierWinsModal');
  if (!modal) return;
  if (_testlottoTierWinsEscHandler) {
    document.removeEventListener('keydown', _testlottoTierWinsEscHandler);
    _testlottoTierWinsEscHandler = null;
  }
  if (jump) jump.value = String(d);
  modal.hidden = false;
  modal.setAttribute('aria-hidden', 'false');
  await lottoRefreshTierWinsModalContent();
  _testlottoTierWinsEscHandler = (e) => {
    if (e.key === 'Escape') lottoCloseTierWinsModal();
  };
  document.addEventListener('keydown', _testlottoTierWinsEscHandler);
}

async function lottoTierWinsModalNav(delta) {
  if (!_testlottoDrawList.length) {
    await lottoRefreshTierWinsModalContent();
    return;
  }
  const input = document.getElementById('testlottoPredictDrawNo');
  const sel = document.getElementById('testlottoDrawSelect');
  const cur = input ? parseInt(input.value, 10) : NaN;
  const base = Number.isFinite(cur) ? cur : _testlottoDrawList[0];
  const idx = _testlottoDrawList.indexOf(base);
  const step = delta > 0 ? -1 : 1;
  const nextIdx = Math.max(0, Math.min(_testlottoDrawList.length - 1, (idx >= 0 ? idx : 0) + step));
  const nextNo = _testlottoDrawList[nextIdx];
  if (input) input.value = String(nextNo);
  if (sel) sel.value = String(nextNo);
  await testlottoLoadSavedPrediction(nextNo, { softLoading: true });
  await lottoRefreshTierWinsModalContent();
}

async function lottoTierWinsModalGoDraw() {
  const jump = document.getElementById('lottoTierWinsJumpInput');
  const d = jump ? parseInt(jump.value, 10) : NaN;
  if (!Number.isFinite(d) || d < 1) {
    alert('올바른 회차 번호를 입력하세요.');
    return;
  }
  const input = document.getElementById('testlottoPredictDrawNo');
  const sel = document.getElementById('testlottoDrawSelect');
  if (input) input.value = String(d);
  if (sel) {
    const opt = sel.querySelector(`option[value="${d}"]`);
    if (opt) sel.value = String(d);
  }
  await testlottoLoadSavedPrediction(d, { softLoading: true });
  await lottoRefreshTierWinsModalContent();
}

/** ISO(YYYY-MM-DD) → 2026년4월25일 (엔진 `draw_date_for_draw_no`와 동일) */
function formatLottoDateKr(isoDate) {
  if (!isoDate || typeof isoDate !== 'string') {
    return '';
  }
  const p = isoDate.split('T')[0].split('-');
  if (p.length !== 3) {
    return isoDate;
  }
  const y = parseInt(p[0], 10);
  const m = parseInt(p[1], 10);
  const d = parseInt(p[2], 10);
  if (Number.isNaN(y) || Number.isNaN(m) || Number.isNaN(d)) {
    return isoDate;
  }
  return `${y}년${m}월${d}일`;
}

function lottoSetActionStatusText(el, text, color) {
  if (!el) {
    return;
  }
  el.className = 'lotto-action-status';
  el.textContent = text;
  el.style.color = color || '';
}

function lottoSetActionStatusNoNew(el, isoDate) {
  if (!el) {
    return;
  }
  const line2 = formatLottoDateKr(isoDate) || '다음 추첨일(추정)을 알 수 없습니다';
  el.className = 'lotto-action-status lotto-action-status--no-new';
  el.removeAttribute('style');
  el.innerHTML = '<div class="lotto-action-status__title">신규 회차 없음</div>'
    + '<div class="lotto-action-status__date">' + line2 + '</div>';
}

// ── 데이터 수집 ──
async function lottoFetchAll() {
  const status = lottoGetActiveStatusEl();
  const btn = document.getElementById('btnFetchAll');
  btn.disabled = true;
  lottoSetActionStatusText(status, '힌트 불러오는 중…', '#f0c040');
  try {
    try {
      const hintRes = await fetch(_testlottoResolveApiUrl('/api/testlotto/collection-hint'));
      const hint = await hintRes.json();
      if (hint && hint.max_draw_no > 0) {
        // 이미 과거 데이터가 있다면 "전체 수집"은 실수 방지용으로 잠금 처리.
        // (사용자는 과거 기록을 보유한 상태라고 가정)
        lottoSetActionStatusText(
          status,
          '이미 로또 데이터가 있습니다(최대 ' + hint.max_draw_no + '회). "전체 데이터 수집"은 잠금 처리되었습니다. 필요 시 관리자에게 문의하세요.',
          '#f0c040',
        );
        alert('이미 과거 로또 데이터가 있어서 "전체 데이터 수집"은 잠금 처리되었습니다.');
        btn.disabled = false;
        return;
      } else {
        lottoSetActionStatusText(status, 'DB가 비어 있습니다. 전체 수집 요청 중…', '#f0c040');
      }
    } catch (hintErr) {
      lottoSetActionStatusText(status, '전체 수집 요청 중… (힌트 생략)', '#f0c040');
    }
    const res = await fetch(_testlottoResolveApiUrl('/api/testlotto/fetch-all'), { method: 'POST' });
    const data = await res.json();
    lottoSetActionStatusText(
      status,
      (data && data.message) ? data.message : '수집 시작됨. 완료 요약을 불러옵니다…',
      '#4ade80',
    );

    var attempts = 0;
    var poll = setInterval(async function() {
      attempts += 1;
      try {
        const lr = await fetch(_testlottoResolveApiUrl('/api/testlotto/last-fetch-all'));
        const j = await lr.json();
        var r = j && j.result;
        if (r && r.user_message) {
          if (r.status === 'running') {
            if (attempts >= 200) {
              clearInterval(poll);
              lottoSetActionStatusText(status, '응답이 지연되고 있습니다. 잠시 후 당첨 이력 탭을 확인하세요.', '#f0c040');
              btn.disabled = false;
              loadDraws();
            }
            return;
          }
          clearInterval(poll);
          lottoSetActionStatusText(
            status,
            r.user_message,
            (r.ok === false) ? '#f87171' : (r.tail_unavailable > 0 && (r.fetched || 0) === 0) ? '#f0c040' : '#4ade80',
          );
          loadDraws();
          loadBrainStatus();
          btn.disabled = false;
          return;
        }
        if (attempts >= 200) {
          clearInterval(poll);
          lottoSetActionStatusText(status, '완료 요약을 가져오지 못했습니다. 당첨 이력 탭을 확인하세요.', '#f0c040');
          loadDraws();
          loadBrainStatus();
          btn.disabled = false;
        }
      } catch (err) {
        clearInterval(poll);
        lottoSetActionStatusText(status, '상태 조회 실패: ' + err.message, '#f87171');
        btn.disabled = false;
      }
    }, 500);
  } catch (e) {
    lottoSetActionStatusText(status, '수집 실패: ' + e.message, '#f87171');
    btn.disabled = false;
  }
}

async function lottoFetchLatest() {
  const status = lottoGetActiveStatusEl();
  try {
    const res = await fetch(_testlottoResolveApiUrl('/api/testlotto/fetch-latest'), { method: 'POST' });
    const data = await res.json();
    if (data.draw) {
      lottoSetActionStatusText(status, `${data.draw.draw_no}회차 수집 완료!`, '#4ade80');
      loadDraws();
    } else {
      const iso = data && data.next_draw_date;
      if (iso) {
        lottoSetActionStatusNoNew(status, iso);
      } else {
        try {
          const hRes = await fetch(_testlottoResolveApiUrl('/api/testlotto/collection-hint'));
          const hint = await hRes.json();
          if (hint && hint.next_draw_date) {
            lottoSetActionStatusNoNew(status, hint.next_draw_date);
          } else {
            lottoSetActionStatusText(status, '신규 회차 없음', 'var(--text-secondary)');
          }
        } catch (hintEx) {
          lottoSetActionStatusText(status, '신규 회차 없음', 'var(--text-secondary)');
        }
      }
    }
  } catch (e) {
    lottoSetActionStatusText(status, '수집 실패: ' + e.message, '#f87171');
  }
}

// ── 두뇌 예측 ──
async function testlottoPredict() {
  const input = document.getElementById('testlottoPredictDrawNo');
  const drawNo = parseInt(input.value, 10);
  if (!drawNo || drawNo < 1) {
    alert('회차 번호를 입력하세요.');
    return;
  }
  const status = document.getElementById('testlottoActionStatus');
  lottoSetActionStatusText(status, '두뇌 풀가동 중... (약 30초~1분)', '#f0c040');

  try {
    const res = await fetch(_testlottoResolveApiUrl(`/api/testlotto/predict/${drawNo}`), { method: 'POST' });
    const data = await res.json();

    if (data.error) {
      lottoSetActionStatusText(status, data.error, '#f87171');
      return;
    }

    lottoSetActionStatusText(status, `${drawNo}회차 예측 완료!`, '#4ade80');
    // 업그레이드 UI(회차 드롭다운)가 있으면 6두뇌 탭 렌더만 사용(깜빡임 방지)
    const sel = document.getElementById('testlottoDrawSelect');
    if (!sel) {
      renderPredictions(data);
    }
    try {
      // 업그레이드 UI에서는 캐시를 기다리지 말고, 응답(data)로 즉시 렌더한다.
      if (sel) {
        const actuals = Array.isArray(data.actual_numbers) ? data.actual_numbers : null;
        const bonus = (data.actual_bonus != null) ? data.actual_bonus : null;
        const rows = (data.all_predictions || []).map((p) => {
          const nums = p.nums || [];
          const base = {
            target_draw_no: drawNo,
            method: p.method,
            brain_tag: p.brain_tag,
            confidence: p.confidence,
            reasoning: p.reasoning,
            matched_count: p.matched_count,
            bonus_matched: p.bonus_matched,
            num1: nums[0],
            num2: nums[1],
            num3: nums[2],
            num4: nums[3],
            num5: nums[4],
            num6: nums[5],
          };
          if (actuals && actuals.length === 6) {
            base.actual_1 = actuals[0];
            base.actual_2 = actuals[1];
            base.actual_3 = actuals[2];
            base.actual_4 = actuals[3];
            base.actual_5 = actuals[4];
            base.actual_6 = actuals[5];
            base.actual_bonus = bonus;
          }
          return base;
        });

        // 캐시에도 해당 회차를 즉시 반영(다음 렌더/탭 전환 일관성)
        _testlottoPredRowsCache = (_testlottoPredRowsCache || []).filter((p) => parseInt(p.target_draw_no, 10) !== drawNo);
        _testlottoPredRowsCache = rows.concat(_testlottoPredRowsCache);
        _testlottoDetailDrawNo = drawNo;
        _testlottoDetailRows = rows;

        await renderPredictionsByBrain(drawNo, rows);

        // 무거운 전체 목록 리로드는 백그라운드로
        loadTestlottoDrawList().then(() => {
          sel.value = String(drawNo);
        }).catch(() => {});
      } else {
        // 기존 UI는 원래 흐름 유지
        await loadTestlottoDrawList();
        await testlottoLoadSavedPrediction(drawNo);
      }
    } catch (e2) {
      // 무시 (기존 렌더는 이미 완료)
    }
    loadBrainStatus();
  } catch (e) {
    lottoSetActionStatusText(status, '예측 실패: ' + e.message, '#f87171');
  }
}

/** 예측 세트 1개 카드 (Top5 / 최다 적중 공용) */
function renderLottoPredCard(pred, rankLabel, data, options) {
  const opts = options || {};
  const nums = pred.nums || [pred.num1, pred.num2, pred.num3, pred.num4, pred.num5, pred.num6];
  const matched = pred.matched_count >= 0 ? pred.matched_count : null;
  const tag = String(pred.brain_tag || '').toLowerCase();
  const dn = tag ? testlottoGetBrainDisplayName(tag) : '';
  const dd = tag ? testlottoGetBrainDescription(tag) : '';
  const method = pred.method || '알수없음';
  const brainText = dn ? (dn + (dd ? ' (' + dd + ')' : '')) : method;
  const confidence = pred.confidence || 0;
  const matchColor = matched === null ? '#666' :
    matched >= 5 ? '#ffd700' :
      matched >= 4 ? '#ff6b6b' :
        matched >= 3 ? '#4ade80' : '#666';
  const leftBar = opts.emphasize ? '#2ed573' : matchColor;
  let h = '';
  h += '<div style="background: #1e1e3a; border-left: 4px solid ' + leftBar + '; border-radius: 8px; padding: 14px; margin-bottom: 10px;">';
  h += '<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">';
  h += '<span style="color: #8b9cf7; font-weight: bold;">' + rankLabel + ' ' + brainText + '</span>';
  h += '<span style="color: #aaa; font-size: 12px;">신뢰도: ' + confidence + '%</span>';
  h += '</div>';
  h += '<div style="margin-bottom: 6px;">';
  nums.forEach((n) => {
    const isM = data.actual_numbers && data.actual_numbers.indexOf(n) >= 0;
    h += renderBall(n, isM, isM ? { role: 'hit' } : undefined);
  });
  h += '</div>';
  if (matched !== null && matched >= 0) {
    let rankText = '';
    if (matched === 6) { rankText = '🏆 1등!!! (6개 전체 적중)'; } else if (matched === 5 && pred.bonus_matched) { rankText = '🥈 2등! (5개 + 보너스)'; } else if (matched === 5) { rankText = '🥉 3등! (5개 적중)'; } else if (matched === 4) { rankText = '🎯 4등 (4개 적중)'; } else if (matched === 3) { rankText = '✅ 5등 (3개 적중)'; } else { rankText = matched + '개 적중 (등수 외)'; }
    h += '<div style="font-size: 13px; color: ' + matchColor + '; font-weight: bold;">' + rankText + '</div>';
  }
  if (pred.reasoning) {
    h += '<div style="font-size: 12px; color: #888; margin-top: 4px;">' + pred.reasoning + '</div>';
  }
  h += '</div>';
  return h;
}

function renderPredictions(data) {
  const container = document.getElementById('testlottoPredictionResults');
  let html = `<h3 style="color: #e0e0ff;">${data.target_draw_no}회차 예측 결과</h3>`;

  if (data.status && data.status.includes('기존')) {
    html += `<p style="color: #f0c040; font-size: 13px;">ℹ️ ${data.status}</p>`;
  }

  if (data.actual_numbers) {
    const sorted = [...data.actual_numbers].sort((a, b) => a - b);
    html += `<div style="background: #2d1b69; padding: 12px; border-radius: 8px; margin-bottom: 16px;">`;
    html += `<span style="color: #ffd700; font-weight: bold;">실제 당첨번호: </span>`;
    sorted.forEach((n) => {
      html += renderBall(n, true, { role: 'winning' });
    });
    if (data.actual_bonus != null && data.actual_bonus !== undefined) {
      html += `<span style="color: #888; margin: 0 6px;">+</span>`;
      html += '<span style="color: #ffd700; font-size: 12px; margin-right: 4px;">보너스</span>';
      html += renderBall(data.actual_bonus, true, { role: 'winning' });
    }
    html += `</div>`;
  }

  const totalN = data.total_sets || (data.predictions && data.predictions.length) || 0;
  // 당첨이 있을 때: Top5는 '신뢰도' 기준이라, 적중 개수가 가장 많은 세트(예: 5등)가 6~15위에 있으면 여기 안 나옴(명예의 전당과 달리 보이는 이유)
  if (data.actual_numbers && data.all_predictions && data.all_predictions.length) {
    const aps = data.all_predictions;
    const counts = aps.map((p) => (p.matched_count != null && p.matched_count >= 0 ? p.matched_count : 0));
    const maxM = Math.max(0, ...counts);
    if (maxM > 0) {
      const bestPreds = aps.filter((p) => p.matched_count != null && p.matched_count === maxM);
      if (bestPreds.length) {
        html += `<p style="color: #a8e6cf; font-size: 13px; margin: 0 0 8px 0;">🎯 이 회차 <b>최다 적중</b> (총 15세트 기준) — <span style="color: #9a9ab0; font-weight: normal;">적중 ${maxM}개(동률이면 여러 줄). <b>신뢰도 1~5위 밖</b>일 수 있음</span></p>`;
        bestPreds.forEach((pred, i) => {
          const rlab = bestPreds.length > 1 ? '최다' + (i + 1) : '최다';
          html += renderLottoPredCard(pred, rlab, data, { emphasize: true });
        });
        html += '<hr style="border: 0; border-top: 1px solid #333; margin: 12px 0;" />';
      }
    }
  }
  html += `<p style="color: #aaa; font-size: 13px;">🏅 <b>신뢰도</b> 상위 5세트 (총 ${totalN}세트 중) — 3개 이상 맞힌 세트는 <b>최다 적중</b> 블록에 있을 수 있고, 여기(#1~#5)엔 없을 수 있음</p>`;

  const top5 = data.top5 || (data.predictions && data.predictions.slice(0, 5)) || [];
  top5.forEach((pred, i) => {
    html += renderLottoPredCard(pred, '#' + (i + 1), data, {});
  });

  container.innerHTML = html;
}

/**
 * @param {number} num
 * @param {boolean} highlighted
 * @param {{ role?: 'hit' | 'winning' }} [opt] — hit: 예측↔당첨 일치(최강), winning: 당첨 요약 행
 */
function renderBall(num, highlighted, opt) {
  const role = (opt && opt.role) || null;
  const colors = {
    1: '#fbc400', 11: '#69c8f2', 21: '#ff7272',
    31: '#aaa', 41: '#b0d840',
  };
  let bg = '#555';
  const keys = Object.keys(colors).map((k) => parseInt(k, 10)).sort((a, b) => b - a);
  for (const start of keys) {
    if (num >= start) {
      bg = colors[start];
      break;
    }
  }
  const base =
    'display: inline-flex; align-items: center; justify-content: center; ' +
    'border-radius: 50%; color: #000; font-weight: bold; margin: 3px; ' +
    'vertical-align: middle; box-sizing: border-box;';

  // 예측 번호가 실제 당첨과 겹칠 때(가독성 최우선)
  if (role === 'hit' && highlighted) {
    var redHit = opt && opt.red_hit_border;
    var hitBorder = redHit
      ? 'border: 3px solid #e53935; box-shadow: 0 0 0 1px rgba(229,57,53,0.5), 0 0 12px rgba(229,57,53,0.45); '
      : 'border: 3px solid #fff; ' +
        'box-shadow: 0 0 0 2px #f5c400, 0 0 0 5px rgba(46,213,115,0.55), 0 0 22px 4px rgba(255,220,100,0.9); ';
    return (
      '<span style="' + base + ' ' +
      'width: 42px; height: 42px; font-size: 16px; background: ' + bg + '; ' +
      hitBorder +
      'transform: scale(1.1); z-index: 1; position: relative;' +
      '" title="당첨번호와 일치">' +
      num +
      '</span>'
    );
  }

  // «실제 당첨번호» 요약 행(전체 6+보너스) — 눈에 띄게, 적중 강조보다는 덜
  if (role === 'winning' || (highlighted && !role)) {
    return (
      '<span style="' + base + ' ' +
      'width: 38px; height: 38px; font-size: 15px; background: ' + bg + '; ' +
      'border: 2px solid rgba(255, 215, 0, 0.95); ' +
      'box-shadow: 0 0 14px rgba(255, 200, 80, 0.55), inset 0 0 8px rgba(255,255,255,0.15);' +
      '">' +
      num +
      '</span>'
    );
  }

  return (
    '<span style="' + base + ' ' +
    'width: 36px; height: 36px; font-size: 14px; background: ' + bg + '; ' +
    'border: 2px solid transparent;">' +
    num +
    '</span>'
  );
}

// ── 두뇌 상태 ──
async function loadBrainStatus() {
  try {
    var res = await fetch(_testlottoResolveApiUrl('/api/testlotto/brain/status'));
    var data = await res.json();

    document.getElementById('brainGrade').textContent = data.grade_emoji || '🧠';
    document.getElementById('brainGradeText').textContent = '두뇌 등급: ' + (data.grade || '일반');

    // 기본 통계
    var statsHtml = '총 예측: ' + (data.total_predictions || 0) + '건 | 최고 기록: ';
    if (data.best_record) {
      var mc = data.best_record.matched_count;
      var bm = data.best_record.bonus_matched;
      var bestRank = '';
      if (mc === 6) bestRank = '🏆 1등';
      else if (mc === 5 && bm) bestRank = '🥈 2등';
      else if (mc === 5) bestRank = '🥉 3등';
      else if (mc === 4) bestRank = '🎯 4등';
      else if (mc === 3) bestRank = '✅ 5등';
      else bestRank = mc + '개 적중';
      statsHtml += bestRank + ' (' + data.best_record.target_draw_no + '회차, ' + data.best_record.method + ')';
    } else {
      statsHtml += '없음';
    }
    document.getElementById('brainStats').innerHTML = statsHtml;

    // 3종 두뇌별 성적 비교 카드
    var profileDiv = document.getElementById('brainProfiles');
    if (profileDiv && data.brain_profiles && data.brain_profiles.length > 0) {
      var pHtml = '';
      data.brain_profiles.forEach(function(bp) {
        var icon = '🧠';
        if (bp.method === '통계두뇌') icon = '📊';
        else if (bp.method === 'LLM두뇌') icon = '🤖';
        else if (bp.method === '하이브리드두뇌') icon = '⚡';

        var barWidth = Math.min(Math.round((bp.avg_match || 0) / 3 * 100), 100);
        var barColor = bp.best_match >= 3 ? '#4ade80' : bp.best_match >= 2 ? '#f0c040' : '#666';

        pHtml += '<div style="background: #1e1e3a; border-radius: 8px; padding: 12px; flex: 1; min-width: 200px;">';
        pHtml += '<div style="font-size: 18px; margin-bottom: 6px;">' + icon + ' <span style="color: #e0e0ff; font-weight: bold;">' + bp.method + '</span></div>';
        pHtml += '<div style="color: #aaa; font-size: 13px;">예측: ' + (bp.total_predictions || 0) + '건</div>';
        pHtml += '<div style="color: #aaa; font-size: 13px;">평균 적중: ' + (bp.avg_match || 0).toFixed(2) + '개</div>';
        pHtml += '<div style="color: #aaa; font-size: 13px;">최고 적중: ' + (bp.best_match || 0) + '개</div>';
        pHtml += '<div style="background: #333; border-radius: 4px; height: 8px; margin-top: 6px;">';
        pHtml += '<div style="background: ' + barColor + '; width: ' + barWidth + '%; height: 100%; border-radius: 4px;"></div>';
        pHtml += '</div>';
        pHtml += '</div>';
      });
      profileDiv.innerHTML = pHtml;
    }

  } catch (e) {
    console.warn('두뇌 상태 로드 실패:', e);
  }
}

// ── 명예의 전당 ──
// === 명예의전당 전역 변수 ===
var _fameAllData = [];
var _fameCurrentRank = 'all';
var _fameShowCount = {};  // 두뇌별 표시 건수

async function loadHallOfFame() {
  try {
    const res = await fetch(_testlottoResolveApiUrl('/api/testlotto/brain/hall-of-fame'));
    const data = await res.json();
    _fameAllData = data.hall_of_fame || [];
    _fameCurrentRank = '1';
    _fameShowCount = {};
    renderHallOfFame();
  } catch (e) {
    console.warn('명예의 전당 로드 실패:', e);
  }
}

function getFameRank(mc, bm) {
  if (mc === 6) return '1';
  if (mc === 5 && bm) return '2';
  if (mc === 5) return '3';
  if (mc === 4) return '4';
  if (mc === 3) return '5';
  return '0';
}

function getFameRankText(rank) {
  var map = { '1': '🏆 1등!!!', '2': '🥈 2등!', '3': '🥉 3등!', '4': '🎯 4등', '5': '✅ 5등' };
  return map[rank] || '';
}

function getFameRankColor(rank) {
  var map = { '1': '#ffd700', '2': '#c0c0c0', '3': '#ff6b6b', '4': '#ff6b6b', '5': '#4ade80' };
  return map[rank] || '#888';
}

function renderHallOfFame() {
  var container = document.getElementById('hallOfFame');
  if (!_fameAllData.length) {
    container.innerHTML = '<p class="fame-empty">🏆 3개 이상 적중한 예측이 없습니다.</p>';
    return;
  }

  // 필터링
  var filtered = _fameAllData;
  if (_fameCurrentRank !== 'all') {
    filtered = _fameAllData.filter(function(r) {
      return getFameRank(r.matched_count, r.bonus_matched) === _fameCurrentRank;
    });
  }

  // 등수별 건수 계산 (필터바 표시용)
  var rankCounts = { '1': 0, '2': 0, '3': 0, '4': 0, '5': 0 };
  _fameAllData.forEach(function(r) {
    var rk = getFameRank(r.matched_count, r.bonus_matched);
    if (rankCounts[rk] !== undefined) rankCounts[rk]++;
  });
  var totalCount = _fameAllData.length;

  // 필터 바
  var html = '<div class="fame-filter-bar">';
  var ranks = [
    { key: 'all', label: '전체 (' + totalCount + ')' },
    { key: '1', label: '1등 (' + rankCounts['1'] + ')' },
    { key: '2', label: '2등 (' + rankCounts['2'] + ')' },
    { key: '3', label: '3등 (' + rankCounts['3'] + ')' },
    { key: '4', label: '4등 (' + rankCounts['4'] + ')' },
    { key: '5', label: '5등 (' + rankCounts['5'] + ')' }
  ];
  ranks.forEach(function(rk) {
    var active = _fameCurrentRank === rk.key ? ' active' : '';
    html += '<button class="fame-filter-btn' + active + '" onclick="fameFilterRank(\'' + rk.key + '\')">' + rk.label + '</button>';
  });
  html += '</div>';

  // 6컬럼 그리드
  var brains = ['stat', 'markov', 'llm', 'lstm', 'fusion', 'hyena'];
  html += '<div class="fame-grid">';

  brains.forEach(function(brain) {
    var brainData = filtered.filter(function(r) {
      return (r.brain_tag || '').toLowerCase() === brain;
    });
    // 최신순 정렬
    brainData.sort(function(a, b) { return (b.target_draw_no || 0) - (a.target_draw_no || 0); });

    var showKey = brain + '_' + _fameCurrentRank;
    if (!_fameShowCount[showKey]) _fameShowCount[showKey] = 20;
    var limit = _fameShowCount[showKey];
    var showing = brainData.slice(0, limit);

    html += '<div class="fame-column">';
    // 헤더
    html += '<div class="fame-col-header">';
    html += '<div class="brain-name">' + testlottoGetBrainDisplayName(brain) + '</div>';
    html += '<div class="brain-desc">' + testlottoGetBrainDescription(brain) + '</div>';
    html += '<div class="fame-count">' + brainData.length + '건</div>';
    html += '</div>';

    if (showing.length === 0) {
      html += '<div class="fame-empty">(없음)</div>';
    }

    showing.forEach(function(record) {
      var rank = getFameRank(record.matched_count, record.bonus_matched);
      var rankClass = 'fame-card rank-' + rank;
      var rankColor = getFameRankColor(rank);

      var predNums = [record.num1, record.num2, record.num3, record.num4, record.num5, record.num6];
      var actNums = [record.actual_1, record.actual_2, record.actual_3, record.actual_4, record.actual_5, record.actual_6].filter(function(n) { return n != null; });
      var actBonus = record.actual_bonus || null;
      var actSet = {};
      actNums.forEach(function(n) { actSet[n] = true; });
      var drawDate = record.draw_date ? ' (' + record.draw_date + ')' : '';

      html += '<div class="' + rankClass + '">';
      // 헤더
      html += '<div class="card-header">';
      html += '<span class="draw-info">' + record.target_draw_no + '회' + drawDate + '</span>';
      html += '<span class="rank-badge" style="color:' + rankColor + '">' + getFameRankText(rank) + '</span>';
      html += '</div>';
      // 예측 번호
      html += '<div class="nums-row"><span class="label">예측: </span>';
      predNums.forEach(function(n) {
        var isMatch = actSet[n] === true;
        html += renderBall(n, isMatch, isMatch ? { role: 'hit' } : undefined);
      });
      html += '</div>';
      // 당첨 번호
      if (actNums.length > 0) {
        html += '<div class="nums-row"><span class="label">당첨: </span>';
        actNums.forEach(function(n) {
          html += renderBall(n, true, { role: 'winning' });
        });
        if (actBonus) {
          html += '<span style="color:#aaa;margin:0 2px">+</span>';
          html += renderBall(actBonus, true, { role: 'winning' });
        }
        html += '</div>';
      }
      // 푸터
      html += '<div class="card-footer">';
      html += '<span>신뢰도 ' + (record.confidence || 0).toFixed(1) + '%</span>';
      html += '</div>';
      html += '</div>';
    });

    // 더보기 버튼
    if (brainData.length > limit) {
      var remaining = brainData.length - limit;
      html += '<button class="fame-more-btn" onclick="fameShowMore(\'' + brain + '\')">+ 더보기 (' + remaining + '건 남음)</button>';
    }

    html += '</div>';
  });

  html += '</div>';
  container.innerHTML = html;
}

function fameFilterRank(rank) {
  _fameCurrentRank = rank;
  _fameShowCount = {};
  renderHallOfFame();
}

function fameShowMore(brain) {
  var showKey = brain + '_' + _fameCurrentRank;
  _fameShowCount[showKey] = (_fameShowCount[showKey] || 20) + 20;
  renderHallOfFame();
}

// ── 통계 분석 ──
async function loadStats() {
  try {
    const res = await fetch(_testlottoResolveApiUrl('/api/testlotto/stats/comprehensive'));
    const data = await res.json();

    if (data.error) {
      document.getElementById('freqChart').innerHTML = `<p style="color: #f87171;">${data.error}</p>`;
      return;
    }

    renderFreqChart(data.frequency);
    renderOddEvenChart(data.odd_even);
    renderRangeChart(data.range_distribution);
    renderSumChart(data.sum_range);
    renderPairChart(data.pair_frequency);
  } catch (e) {
    console.warn('통계 로드 실패:', e);
  }
}

function renderFreqChart(freq) {
  const container = document.getElementById('freqChart');
  if (!freq) { container.innerHTML = '데이터 없음'; return; }

  const values = Object.values(freq).map((v) => v.count || 0);
  const maxCount = values.length > 0 ? Math.max.apply(null, values) : 1;

  let html = '<div style="display: flex; flex-wrap: wrap; gap: 4px;">';
  for (let n = 1; n <= 45; n += 1) {
    const info = freq[n] || freq[String(n)] || { count: 0 };
    const count = info.count || 0;
    const intensity = Math.round((count / Math.max(maxCount, 1)) * 255);
    const bg = `rgb(${intensity}, ${Math.round(intensity * 0.6)}, ${255 - intensity})`;
    html += `<div style="width: 48px; text-align: center; padding: 4px; border-radius: 6px; background: ${bg}; color: #fff; font-size: 11px;"
                  title="${n}번: ${count}회 출현">
              <div style="font-weight: bold;">${n}</div>
              <div>${count}</div>
            </div>`;
  }
  html += '</div>';
  container.innerHTML = html;
}

function renderOddEvenChart(data) {
  const container = document.getElementById('oddEvenChart');
  if (!data) { container.innerHTML = '데이터 없음'; return; }

  let html = '';
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const max = entries.length > 0 ? entries[0][1] : 1;
  entries.forEach(([pattern, count]) => {
    const width = Math.round((count / max) * 100);
    html += `<div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
              <span style="min-width: 70px; color: #aaa; font-size: 13px;">${pattern}</span>
              <div style="flex: 1; background: #333; border-radius: 4px; height: 20px;">
                <div style="width: ${width}%; background: #8b9cf7; border-radius: 4px; height: 100%;"></div>
              </div>
              <span style="color: #ccc; font-size: 12px; min-width: 40px;">${count}회</span>
            </div>`;
  });
  container.innerHTML = html;
}

function renderRangeChart(data) {
  const container = document.getElementById('rangeChart');
  if (!data) { container.innerHTML = '데이터 없음'; return; }

  let html = '';
  const vals = Object.values(data);
  const max = vals.length > 0 ? Math.max.apply(null, vals) : 1;
  Object.entries(data).forEach(([range, count]) => {
    const width = Math.round((count / max) * 100);
    html += `<div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
              <span style="min-width: 50px; color: #aaa; font-size: 13px;">${range}</span>
              <div style="flex: 1; background: #333; border-radius: 4px; height: 20px;">
                <div style="width: ${width}%; background: #4ade80; border-radius: 4px; height: 100%;"></div>
              </div>
              <span style="color: #ccc; font-size: 12px; min-width: 50px;">${count}회</span>
            </div>`;
  });
  container.innerHTML = html;
}

function renderSumChart(data) {
  const container = document.getElementById('sumChart');
  if (!data) { container.innerHTML = '데이터 없음'; return; }

  const html = `<p style="color: #ccc; font-size: 14px;">
    평균 합계: <b style="color: #ffd700;">${data.average}</b> |
    최소: ${data.min} | 최대: ${data.max}
  </p>`;
  container.innerHTML = html;
}

function renderPairChart(pairs) {
  const container = document.getElementById('pairChart');
  if (!pairs || pairs.length === 0) { container.innerHTML = '데이터 없음'; return; }

  let html = '<div style="display: flex; flex-wrap: wrap; gap: 6px;">';
  pairs.slice(0, 30).forEach((p) => {
    html += `<span style="background: #2a2a4e; padding: 4px 10px; border-radius: 12px; color: #ccc; font-size: 12px;">
              ${p.pair[0]}-${p.pair[1]} (${p.count}회)
            </span>`;
  });
  html += '</div>';
  container.innerHTML = html;
}

// ── 당첨 이력 ──
async function loadDraws() {
  try {
    const res = await fetch(_testlottoResolveApiUrl('/api/testlotto/draws?limit=50'));
    const data = await res.json();
    const container = document.getElementById('drawsList');

    if (!data.draws || data.draws.length === 0) {
      container.innerHTML = '<p style="color: #888;">데이터가 없습니다. "전체 데이터 수집"을 먼저 실행하세요.</p>';
      return;
    }

    let html = `<p style="color: #aaa; margin-bottom: 12px;">총 ${data.total}회차 저장됨 (최근 50개 표시)</p>`;
    html += '<div style="max-height: 500px; overflow-y: auto;">';

    data.draws.forEach((d) => {
      html += `<div style="display: flex; align-items: center; gap: 12px; padding: 8px; border-bottom: 1px solid #333;">`;
      html += `<span style="color: #8b9cf7; font-weight: bold; min-width: 70px;">${d.draw_no}회</span>`;
      html += `<span style="color: #888; min-width: 90px; font-size: 12px;">${d.draw_date}</span>`;
      [d.num1, d.num2, d.num3, d.num4, d.num5, d.num6].forEach((n) => {
        html += renderBall(n, false);
      });
      html += `<span style="color: #888; font-size: 11px;">+</span>`;
      html += renderBall(d.bonus, false);
      if (d.first_prize) {
        html += `<span style="color: #aaa; font-size: 11px; margin-left: 8px;">1등: ${(d.first_prize / 100000000).toFixed(1)}억</span>`;
      }
      html += `</div>`;
    });

    html += '</div>';
    container.innerHTML = html;
  } catch (e) {
    console.warn('당첨 이력 로드 실패:', e);
  }
}

// ── 초기화 ──
document.addEventListener('DOMContentLoaded', () => {
  const lottoTab = document.querySelector('[data-tab="lotto"]');
  if (lottoTab) {
    lottoTab.addEventListener('click', () => {
      setTimeout(() => {
        loadBrainStatus();
        loadHallOfFame();
        initTestlottoDrawSearch();
      }, 300);
    });
  }
});

// ============================================
// === 사이드바 + 대시보드 (1단계) ===
// ============================================

// === 사이드바 페이지 전환 ===
function switchLottoPage(pageName) {
  const root = document.getElementById('tab-lotto');
  if (!root) return;
  root.querySelectorAll('.lotto-page').forEach((p) => p.classList.remove('active'));
  root.querySelectorAll('.lotto-sidebar-item').forEach((b) => b.classList.remove('active'));

  const page = document.getElementById('lotto-page-' + pageName);
  if (page) page.classList.add('active');

  root.querySelectorAll('.lotto-sidebar-item').forEach((b) => {
    if (b.getAttribute('onclick') === "switchLottoPage('" + pageName + "')") {
      b.classList.add('active');
    }
  });

  // 페이지별 데이터 로드
  if (pageName === 'dashboard') loadDashboard();
  if (pageName === 'predict') initTestlottoDrawSearch();
  if (pageName === 'fame') loadHallOfFame();
  if (pageName === 'stats') loadStats();
  if (pageName === 'draws') loadDraws();
  if (pageName === 'brains') loadBrainStatus();
  if (pageName === 'special') loadSpecialForce();
}

// === 등수 드롭다운 토글 ===
function toggleRankDropdown(rankId) {
  const list = document.getElementById(rankId + 'List');
  if (list) {
    list.style.display = list.style.display === 'none' ? 'block' : 'none';
  }
}

// === 대시보드 데이터 로드 ===
async function loadDashboard() {
  try {
    const res = await fetch('/api/testlotto/dashboard-summary');
    const data = await res.json();
    setLottoBrainPowerCache(data.brain_power);
    renderCountdown(data.next_draw_no, data.next_draw_date, data.next_draw_weekday);
    renderRankings(data.rankings);
    renderPowerMeter(data.brain_power);
    renderProgress(data.learning_range, data.total_predictions);
    renderScores(data.scores);
  } catch (e) {
    console.error('Dashboard load failed:', e);
  }
}

// === 카운트다운 타이머 ===
let _testlottoCountdownInterval = null;

function renderCountdown(drawNo, dateStr, weekday) {
  const nextEl = document.getElementById('lottoNextDraw');
  if (nextEl) {
    nextEl.textContent = '🔔 다음 추첨: ' + drawNo + '회 (' + dateStr + ' ' + weekday + ')';
  }

  if (_testlottoCountdownInterval) clearInterval(_testlottoCountdownInterval);
  const target = new Date(dateStr + 'T20:45:00+09:00');

  function updateTimer() {
    const el = document.getElementById('lottoCountdownTimer');
    if (!el) return;
    const now = new Date();
    const diff = target - now;
    if (diff <= 0) {
      el.textContent = '🎉 추첨 완료!';
      clearInterval(_testlottoCountdownInterval);
      return;
    }
    const d = Math.floor(diff / 86400000);
    const h = Math.floor((diff % 86400000) / 3600000);
    const m = Math.floor((diff % 3600000) / 60000);
    const s = Math.floor((diff % 60000) / 1000);
    el.textContent =
      '⏰ 추첨까지 D-' + d + ' ' +
      String(h).padStart(2, '0') + ':' +
      String(m).padStart(2, '0') + ':' +
      String(s).padStart(2, '0');
  }

  updateTimer();
  _testlottoCountdownInterval = setInterval(updateTimer, 1000);
}

// === 등수별 랭킹 ===
function renderRankings(rankings) {
  if (!rankings) return;
  window._testlottoDashboardRankings = rankings;
  if (!window._testlottoRankState) {
    window._testlottoRankState = { rank1: { limit: 20 }, rank2: { limit: 20 }, rank3: { limit: 20 } };
  }
  ['rank1', 'rank2', 'rank3'].forEach((key) => {
    const list = rankings[key] || [];
    const countEl = document.getElementById(key + 'Count');
    const listEl = document.getElementById(key + 'List');
    if (countEl) countEl.textContent = String(list.length);
    if (listEl) {
      if (list.length === 0) {
        listEl.innerHTML = '<div style="padding:8px;color:#666">아직 없음</div>';
      } else {
        const state = window._testlottoRankState[key] || { limit: 20 };
        const limit = Math.max(20, Number(state.limit || 20));
        const shown = list.slice(0, limit);
        let html = '';
        html += shown.map((item) => {
          const t = String(item.brain || '').toLowerCase();
          const brain = testlottoGetBrainDisplayName(t);
          return '<div style="padding:4px 0;border-bottom:1px solid #0f3460">' +
            '<strong>' + item.draw_no + '회</strong> ' + brain + ' — ' +
            (item.numbers ? item.numbers.join(', ') : '') +
          '</div>';
        }).join('');
        if (list.length > limit) {
          html += '<div style="padding:10px 0;display:flex;justify-content:center">';
          html += '<button class="btn btn-primary" style="padding:8px 12px;font-size:12px" onclick="lottoRankShowMore(\'' + key + '\')">더보기 (+20)</button>';
          html += '</div>';
        } else {
          html += '<div style="padding:8px 0;color:#666;text-align:center;font-size:12px">끝</div>';
        }
        listEl.innerHTML = html;
      }
    }
  });
}

function lottoRankShowMore(key) {
  if (!window._testlottoRankState) window._testlottoRankState = {};
  const state = window._testlottoRankState[key] || { limit: 20 };
  state.limit = Number(state.limit || 20) + 20;
  window._testlottoRankState[key] = state;
  if (window._testlottoDashboardRankings) {
    renderRankings(window._testlottoDashboardRankings);
    const el = document.getElementById(key + 'List');
    if (el) el.style.display = 'block';
  }
}

function lottoRankShowAll(key) {
  if (!window._testlottoRankState) window._testlottoRankState = {};
  const state = window._testlottoRankState[key] || { limit: 20 };
  state.limit = 1000000;
  window._testlottoRankState[key] = state;
  if (window._testlottoDashboardRankings) {
    renderRankings(window._testlottoDashboardRankings);
    const el = document.getElementById(key + 'List');
    if (el) el.style.display = 'block';
  }
}

// === 두뇌 파워 미터 ===
function renderPowerMeter(brainPower) {
  const el = document.getElementById('powerMeterContent');
  if (!el || !brainPower) return;
  const maxScore = Math.max(...brainPower.map((b) => b.rank1 * 100 + b.rank2 * 50 + b.rank3 * 10), 1);
  el.innerHTML = brainPower.map((b) => {
    const t = String(b.brain || '').toLowerCase();
    const brain = testlottoGetBrainDisplayName(t);
    const desc = testlottoGetBrainDescription(t);
    const score = b.rank1 * 100 + b.rank2 * 50 + b.rank3 * 10;
    const pct = Math.round(score / maxScore * 100);
    const medal = pct >= 80 ? '🥇' : pct >= 50 ? '🥈' : pct >= 30 ? '🥉' : '  ';
    return '<div style="margin-bottom:12px">' +
      '<div style="display:flex;justify-content:space-between;margin-bottom:4px">' +
        '<span style="color:#fff">' + medal + ' ' + brain + (desc ? ' <span style="color:#9a9ab0;font-size:12px">(' + desc + ')</span>' : '') + '</span>' +
        '<span style="color:#ffd700">' + b.label + '</span>' +
      '</div>' +
      '<div style="color:#a0a0b0;font-size:13px;margin-bottom:4px">' +
        '1등 ' + b.rank1 + '회 · 2등 ' + b.rank2 + '회 · 3등 ' + b.rank3 + '회 · 4등 ' +
        Number(b.rank4 || 0) +
        '회 · 5등 ' +
        Number(b.rank5 || 0) +
        '회' +
      '</div>' +
      '<div style="background:#0a0a1a;border-radius:4px;height:8px;overflow:hidden">' +
        '<div style="background:linear-gradient(90deg,#e94560,#ffd700);width:' + pct + '%;height:100%;border-radius:4px"></div>' +
      '</div>' +
    '</div>';
  }).join('');
}

// === AI 학습 현황 ===
function renderProgress(range, totalPreds) {
  const el = document.getElementById('progressContent');
  if (!el || !range) return;
  const learned = (range.end - range.start + 1);
  const total = range.total_draws;
  const pct = Math.round(learned / Math.max(total, 1) * 100);
  el.innerHTML =
    '<div style="display:flex;justify-content:space-between;color:#fff;margin-bottom:8px">' +
      '<span>학습 범위: ' + range.start + ' ~ ' + range.end + '회차</span>' +
      '<span>' + pct + '% (' + learned + '/' + total + ')</span>' +
    '</div>' +
    '<div style="background:#0a0a1a;border-radius:4px;height:12px;overflow:hidden;margin-bottom:8px">' +
      '<div style="background:linear-gradient(90deg,#00b894,#0984e3);width:' + pct + '%;height:100%;border-radius:4px"></div>' +
    '</div>' +
    '<div style="color:#a0a0b0;font-size:13px">총 예측 세트: ' + Number(totalPreds || 0).toLocaleString() + '건</div>';
}

// === 등수별 적중 점수 ===
function renderScores(scores) {
  const el = document.getElementById('scoresContent');
  if (!el || !scores) return;
  const rows = [
    { label: '🥇 1등', pct: scores.rank1_pct, cnt: scores.rank1_cnt, color: '#ffd700' },
    { label: '🥈 2등', pct: scores.rank2_pct, cnt: scores.rank2_cnt, color: '#c0c0c0' },
    { label: '🥉 3등', pct: scores.rank3_pct, cnt: scores.rank3_cnt, color: '#cd7f32' },
    { label: '4등', pct: scores.rank4_pct, cnt: scores.rank4_cnt, color: '#74b9ff' },
    { label: '5등', pct: scores.rank5_pct, cnt: scores.rank5_cnt, color: '#a0a0b0' },
  ];
  el.innerHTML = rows.map((r) =>
    '<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #0f3460">' +
      '<span style="color:' + r.color + '">' + r.label + '</span>' +
      '<span style="color:#fff">' + Number(r.pct || 0).toFixed(3) + '% (' + Number(r.cnt || 0) + '건)</span>' +
    '</div>'
  ).join('') +
  '<div style="display:flex;justify-content:space-between;padding:8px 0;margin-top:4px">' +
    '<span style="color:#e94560;font-weight:bold">🎯 총 당첨 점수</span>' +
    '<span style="color:#e94560;font-weight:bold">' + Number(scores.total_hit_pct || 0).toFixed(2) + '%</span>' +
  '</div>';
}

// === 로또 탭 진입 시 대시보드 자동 로드 ===
(function() {
  const lottoTab = document.getElementById('tab-lotto');
  if (!lottoTab || typeof MutationObserver === 'undefined') return;
  const observer = new MutationObserver(function(mutations) {
    mutations.forEach(function(m) {
      if (m.target && m.target.id === 'tab-lotto' && m.target.classList.contains('active')) {
        loadDashboard();
      }
    });
  });
  observer.observe(lottoTab, { attributes: true, attributeFilter: ['class'] });
})();

function lottoGetActiveStatusEl() {
  const activePage = document.querySelector('.lotto-page.active');
  if (!activePage) return document.getElementById('testlottoActionStatus');
  if (activePage.id === 'lotto-page-collect') {
    return document.getElementById('lottoCollectStatus') || document.getElementById('testlottoActionStatus');
  }
  return document.getElementById('testlottoActionStatus');
}

// === 특수부대 페이지 ===
var _specialMissListLimit = 20;

/** 성적표: 5등 접기/더보기 상태 (loadSpecialForce 호출 시 초기화) */
var _specialFifthExpanded = false;
var _specialFifthLimit = 20;
/** @type {Array<Record<string, unknown>>|null} */
var _specialScorecardPredsCache = null;

async function loadSpecialForce() {
  try {
    _specialFifthExpanded = false;
    _specialFifthLimit = 20;
    _specialScorecardPredsCache = null;

    const predRes = await fetch(_testlottoResolveApiUrl('/api/testlotto/predictions?limit=50000'));
    const predData = await predRes.json();
    const preds = predData.predictions || predData || [];

    const drawBest = {};
    const baseTags = ['stat', 'markov', 'llm', 'lstm', 'fusion', 'hyena'];
    preds.forEach(function(p) {
      if (baseTags.indexOf(p.brain_tag) === -1) return;
      if (p.matched_count < 0) return;
      var dno = p.target_draw_no;
      if (!drawBest[dno] || p.matched_count > drawBest[dno]) {
        drawBest[dno] = p.matched_count;
      }
    });
    var missDrawNos = [];
    Object.keys(drawBest).forEach(function(dno) {
      if (drawBest[dno] <= 2) missDrawNos.push(parseInt(dno, 10));
    });
    missDrawNos.sort(function(a, b) { return b - a; });
    var totalDraws = Object.keys(drawBest).length;

    var summaryEl = document.getElementById('specialSummary');
    if (!summaryEl) return;
    var pctStr = totalDraws > 0 ? ((missDrawNos.length / totalDraws) * 100).toFixed(1) : '0.0';
    summaryEl.innerHTML =
      '총 미당첨 회차: <strong>' + missDrawNos.length + '회</strong> / ' + totalDraws +
      '회 (' + pctStr + '%) — 기존 6두뇌 30세트 전부 2개 이하 적중';

    var missPreds = preds.filter(function(p) { return p.brain_tag === 'miss_analysis'; });
    var snakePreds = preds.filter(function(p) { return p.brain_tag === 'snake'; });

    renderSpecialBrainStats('specialMissStats', missPreds);
    renderSpecialBrainStats('specialSnakeStats', snakePreds);

    renderSpecialBrainPreds('specialMissPreds', missPreds);
    renderSpecialBrainPreds('specialSnakePreds', snakePreds);

    renderSpecialMissList(missDrawNos, preds);

    renderSpecialScorecard(preds);
  } catch (e) {
    console.warn('특수부대 로드 실패:', e);
  }
}

/**
 * 특수부대 백테스트 성적표 (이미 fetch한 predictions만 사용)
 * @param {Array<Record<string, unknown>>} allPreds
 */
function renderSpecialScorecard(allPreds) {
  var page = document.getElementById('lotto-page-special');
  if (!page) return;

  var missPreds = allPreds.filter(function(p) { return p.brain_tag === 'miss_analysis'; });
  var snakePreds = allPreds.filter(function(p) { return p.brain_tag === 'snake'; });
  _specialScorecardPredsCache = allPreds;

  var wrap = document.getElementById('specialScorecard');
  if (!wrap) {
    wrap = document.createElement('div');
    wrap.id = 'specialScorecard';
    var summaryEl = document.getElementById('specialSummary');
    if (summaryEl && summaryEl.parentNode) {
      summaryEl.parentNode.insertBefore(wrap, summaryEl.nextSibling);
    } else {
      page.appendChild(wrap);
    }
  }

  function countScored(arr) {
    var n = 0;
    arr.forEach(function(p) {
      if (p.matched_count >= 0) n++;
    });
    return n;
  }

  function tagStats(arr) {
    var scored = arr.filter(function(p) { return p.matched_count >= 0; });
    var r4 = 0;
    var r5 = 0;
    var sum = 0;
    scored.forEach(function(p) {
      if (p.matched_count === 4) r4++;
      if (p.matched_count === 3) r5++;
      sum += Number(p.matched_count || 0);
    });
    var avg = scored.length ? (sum / scored.length).toFixed(2) : '0.00';
    return { r4: r4, r5: r5, avg: avg, scored: scored.length };
  }

  var drawRounds = new Set();
  missPreds.forEach(function(p) {
    drawRounds.add(p.target_draw_no);
  });

  var scoredTotal = countScored(missPreds) + countScored(snakePreds);
  var sm = tagStats(missPreds);
  var ss = tagStats(snakePreds);

  var boxStyle =
    'background: linear-gradient(135deg, #1a1a2e, #16213e); border: 1px solid #333; border-radius: 10px; ' +
    'padding: 16px; margin-bottom: 16px; color: #e0e0ff; font-size: 0.92em;';
  var hStyle = 'color: #ffd700; margin: 0 0 10px 0; font-size: 1.05em;';
  var grid2 =
    'display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 10px;';
  if (window.innerWidth && window.innerWidth < 520) {
    grid2 = 'display: grid; grid-template-columns: 1fr; gap: 12px; margin-top: 10px;';
  }

  var html = '';
  html += '<div style="' + boxStyle + '">';
  html += '<h4 style="' + hStyle + '">📊 백테스트 성적표</h4>';
  html += '<div style="color:#ccc;line-height:1.5;">';
  html += '총 <strong>' + drawRounds.size + '</strong>회차 테스트 | 채점완료 <strong>' + scoredTotal + '</strong>건';
  html += '</div>';
  html += '<div style="' + grid2 + '">';
  html += '<div style="border:1px solid #444;border-radius:8px;padding:10px;background:#0d1117;">';
  html += '<div style="font-weight:bold;color:#e0e0ff;margin-bottom:6px;">' + testlottoGetBrainDisplayName('miss_analysis') + '</div>';
  html += '<div style="color:#aaa;font-size:0.85em;">4등: ' + sm.r4 + '건</div>';
  html += '<div style="color:#aaa;font-size:0.85em;">5등: ' + sm.r5 + '건</div>';
  html += '<div style="color:#ffd700;margin-top:6px;">평균적중: ' + sm.avg + '</div>';
  html += '</div>';
  html += '<div style="border:1px solid #444;border-radius:8px;padding:10px;background:#0d1117;">';
  html += '<div style="font-weight:bold;color:#e0e0ff;margin-bottom:6px;">' + testlottoGetBrainDisplayName('snake') + '</div>';
  html += '<div style="color:#aaa;font-size:0.85em;">4등: ' + ss.r4 + '건</div>';
  html += '<div style="color:#aaa;font-size:0.85em;">5등: ' + ss.r5 + '건</div>';
  html += '<div style="color:#ffd700;margin-top:6px;">평균적중: ' + ss.avg + '</div>';
  html += '</div>';
  html += '</div>';
  html += '</div>';

  html += '<div style="' + boxStyle + '">';
  html += '<h4 style="' + hStyle + '">🏅 4등 이상 상세</h4>';
  var high = allPreds.filter(function(p) {
    var t = p.brain_tag;
    return (t === 'miss_analysis' || t === 'snake') && p.matched_count >= 4;
  }).sort(function(a, b) {
    var da = (b.target_draw_no || 0) - (a.target_draw_no || 0);
    if (da !== 0) return da;
    return (b.matched_count || 0) - (a.matched_count || 0);
  });
  if (!high.length) {
    html += '<div style="color:#666;font-size:0.85em;">4등 이상 적중 내역이 없습니다.</div>';
  } else {
    high.forEach(function(p) {
      html += _specialRenderHitDetailRow(p);
    });
  }
  html += '</div>';

  html += '<div style="' + boxStyle + '">';
  html += '<h4 style="' + hStyle + '">✅ 5등 내역</h4>';
  html += '<button type="button" class="special-more-btn" id="specialFifthToggleBtn" onclick="specialToggleFifth()">5등 보기 ▼</button>';
  html += '<div id="specialFifthBody" style="margin-top:10px;"></div>';
  html += '</div>';

  html += '<div style="' + boxStyle + '">';
  html += '<h4 style="' + hStyle + '">📈 구간별 성장 추이</h4>';
  html += _specialRenderRangeBars(missPreds, 'miss_analysis');
  html += '<div style="height:10px"></div>';
  html += _specialRenderRangeBars(snakePreds, 'snake');
  html += '</div>';

  wrap.innerHTML = html;
  renderSpecialFifthBody();
}

function _specialRangeGroup(dno) {
  var d = Number(dno) || 0;
  if (d < 100) return '001-099';
  if (d < 300) return '100-299';
  if (d < 500) return '300-499';
  if (d < 700) return '500-699';
  if (d < 900) return '700-899';
  return '900+';
}

function _specialRangeOrder() {
  return ['001-099', '100-299', '300-499', '500-699', '700-899', '900+'];
}

function _specialRenderRangeBars(arr, tag) {
  var scored = arr.filter(function(p) {
    return p.brain_tag === tag && p.matched_count >= 0;
  });
  var groups = {};
  _specialRangeOrder().forEach(function(g) { groups[g] = { sum: 0, cnt: 0 }; });
  scored.forEach(function(p) {
    var g = _specialRangeGroup(p.target_draw_no);
    groups[g].sum += Number(p.matched_count || 0);
    groups[g].cnt += 1;
  });
  var avgs = {};
  var maxAvg = 0.001;
  _specialRangeOrder().forEach(function(g) {
    var c = groups[g].cnt;
    var a = c ? groups[g].sum / c : 0;
    avgs[g] = a;
    if (a > maxAvg) maxAvg = a;
  });

  var title = testlottoGetBrainDisplayName(tag);
  var out = '<div style="color:#e0e0ff;font-weight:bold;margin-bottom:8px;">' + title + '</div>';
  _specialRangeOrder().forEach(function(g) {
    var a = avgs[g] || 0;
    var bars = Math.max(0, Math.min(10, Math.round((a / maxAvg) * 10)));
    var filled = '';
    var ei;
    for (ei = 0; ei < bars; ei++) filled += '█';
    var empty = '';
    for (ei = 0; ei < 10 - bars; ei++) empty += '░';
    out += '<div style="display:flex;align-items:center;gap:8px;margin:4px 0;font-family:monospace;font-size:0.85em;">';
    out += '<span style="min-width:72px;color:#888;">' + g + '</span>';
    out += '<span style="color:#8b9cf7;">' + filled + empty + '</span>';
    out += '<span style="color:#ccc;">' + a.toFixed(2) + '</span>';
    out += '</div>';
  });
  return out;
}

function _specialDrawDateLabel(p) {
  var d = p && p.draw_date;
  if (d) return String(d);
  return '—';
}

function _specialRankLabel(mc, bm) {
  if (mc === 6) return '1등';
  if (mc === 5 && bm) return '2등';
  if (mc === 5) return '3등';
  if (mc === 4) return '4등';
  if (mc === 3) return '5등';
  return (mc != null ? mc : '?') + '개 적중';
}

function _specialRenderHitDetailRow(p) {
  var tag = String(p.brain_tag || '');
  var dno = p.target_draw_no;
  var dateStr = _specialDrawDateLabel(p);
  var predNums = [p.num1, p.num2, p.num3, p.num4, p.num5, p.num6];
  var act = [p.actual_1, p.actual_2, p.actual_3, p.actual_4, p.actual_5, p.actual_6].filter(function(n) {
    return n != null;
  });
  var bonus = p.actual_bonus;
  var actSet = {};
  act.forEach(function(n) { actSet[n] = true; });

  var row =
    'border:1px solid #333;border-radius:8px;padding:10px;margin-bottom:10px;background:#0d1117;';
  var html = '<div style="' + row + '">';
  html += '<div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:6px;margin-bottom:6px;">';
  html += '<span style="color:#e0e0ff;font-weight:bold;">' + dno + '회 <span style="color:#888;font-weight:normal;">· ' + dateStr + '</span></span>';
  html += '<span style="color:#8b9cf7;">' + testlottoGetBrainDisplayName(tag) + '</span>';
  html += '</div>';
  html += '<div style="color:#888;font-size:0.78em;margin-bottom:4px;">' + _specialRankLabel(p.matched_count, p.bonus_matched) + ' · 신뢰도 ' + (Number(p.confidence || 0).toFixed(1)) + '%</div>';
  html += '<div style="margin-bottom:4px;"><span style="color:#888;font-size:0.8em;">예측</span> ';
  predNums.forEach(function(n) {
    var hit = actSet[n] === true;
    html += renderBall(Number(n), hit, hit ? { role: 'hit', red_hit_border: true } : undefined);
  });
  html += '</div>';
  html += '<div><span style="color:#888;font-size:0.8em;">당첨</span> ';
  if (act.length >= 6) {
    act.forEach(function(n) {
      html += renderBall(Number(n), true, { role: 'winning' });
    });
    if (bonus != null) {
      html += '<span style="color:#aaa;margin:0 4px">+</span>';
      html += renderBall(Number(bonus), true, { role: 'winning' });
    }
  } else {
    html += '<span style="color:#666;font-size:0.85em;">미정(당첨 미수집)</span>';
  }
  html += '</div>';
  html += '</div>';
  return html;
}

function renderSpecialFifthBody() {
  var body = document.getElementById('specialFifthBody');
  var btn = document.getElementById('specialFifthToggleBtn');
  if (!body) return;
  var preds = _specialScorecardPredsCache || [];
  var fifth = preds.filter(function(p) {
    var t = p.brain_tag;
    return (t === 'miss_analysis' || t === 'snake') && p.matched_count === 3;
  }).sort(function(a, b) {
    return (b.target_draw_no || 0) - (a.target_draw_no || 0);
  });
  if (btn) {
    btn.textContent = _specialFifthExpanded
      ? ('5등 ' + fifth.length + '건 접기 ▲')
      : ('5등 ' + fifth.length + '건 보기 ▼');
  }
  if (!_specialFifthExpanded) {
    body.innerHTML = '';
    return;
  }
  var slice = fifth.slice(0, _specialFifthLimit);
  var h = '';
  slice.forEach(function(p) {
    h += _specialRenderHitDetailRow(p);
  });
  if (fifth.length > _specialFifthLimit) {
    var rem = fifth.length - _specialFifthLimit;
    h += '<button type="button" class="special-more-btn" onclick="specialFifthMore()">+ 더보기 (' + rem + '건 남음)</button>';
  }
  body.innerHTML = h;
}

function specialToggleFifth() {
  _specialFifthExpanded = !_specialFifthExpanded;
  if (!_specialFifthExpanded) {
    _specialFifthLimit = 20;
  }
  renderSpecialFifthBody();
}

function specialFifthMore() {
  _specialFifthLimit += 20;
  renderSpecialFifthBody();
}

function renderSpecialBrainStats(elId, preds) {
  var el = document.getElementById(elId);
  if (!el) return;
  if (!preds.length) {
    el.innerHTML = '아직 예측 데이터가 없습니다. 두뇌예측 페이지에서 예측을 실행하세요.';
    return;
  }
  var r1 = 0; var r2 = 0; var r3 = 0; var r4 = 0; var r5 = 0; var total = 0;
  preds.forEach(function(p) {
    if (p.matched_count < 0) return;
    total++;
    if (p.matched_count === 6) r1++;
    else if (p.matched_count === 5 && p.bonus_matched) r2++;
    else if (p.matched_count === 5) r3++;
    else if (p.matched_count === 4) r4++;
    else if (p.matched_count === 3) r5++;
  });
  var html = '총 예측: ' + preds.length + '세트<br>';
  html += '🏆1등: ' + r1 + ' | 🥈2등: ' + r2 + ' | 🥉3등: ' + r3 + ' | 🎯4등: ' + r4 + ' | ✅5등: ' + r5;
  if (total > 0) {
    var hitRate = (((r1 + r2 + r3 + r4 + r5) / total) * 100).toFixed(1);
    html += '<br>5등 이상 적중률: ' + hitRate + '%';
  }
  el.innerHTML = html;
}

function renderSpecialBrainPreds(elId, preds) {
  var el = document.getElementById(elId);
  if (!el) return;
  if (!preds.length) {
    el.innerHTML = '<div style="color:#555;font-size:0.85em;">예측 없음</div>';
    return;
  }
  var sorted = preds.slice().sort(function(a, b) { return (b.target_draw_no || 0) - (a.target_draw_no || 0); });
  var latestDraw = sorted[0].target_draw_no;
  var latest = sorted.filter(function(p) { return p.target_draw_no === latestDraw; });

  var html = '<div style="color:#888;font-size:0.75em;margin-bottom:6px;">' + latestDraw + '회차 예측</div>';
  latest.forEach(function(p, i) {
    html += '<div class="special-pred-card">';
    html += '<div class="special-pred-header">';
    html += '<span>#' + (i + 1) + '</span>';
    html += '<span>신뢰도 ' + (p.confidence || 0).toFixed(1) + '%</span>';
    html += '</div>';
    html += '<div class="special-pred-nums">';
    var nums = [p.num1, p.num2, p.num3, p.num4, p.num5, p.num6];
    nums.forEach(function(n) {
      html += renderBall(n, false);
    });
    html += '</div>';
    html += '</div>';
  });
  el.innerHTML = html;
}

function renderSpecialMissList(missDrawNos, allPreds) {
  var el = document.getElementById('specialMissList');
  if (!el) return;
  if (!missDrawNos.length) {
    el.innerHTML = '<div style="color:#555;">미당첨 회차가 없습니다.</div>';
    return;
  }
  var showing = missDrawNos.slice(0, _specialMissListLimit);

  var html = '<table class="special-miss-table">';
  html += '<thead><tr><th>회차</th><th>최고 적중</th><th>미당첨분석</th><th>뱀</th></tr></thead>';
  html += '<tbody>';

  showing.forEach(function(dno) {
    var basePreds = allPreds.filter(function(p) {
      return p.target_draw_no === dno &&
        ['stat', 'markov', 'llm', 'lstm', 'fusion', 'hyena'].indexOf(p.brain_tag) >= 0 &&
        p.matched_count >= 0;
    });
    var bestMatch = 0;
    basePreds.forEach(function(p) { if (p.matched_count > bestMatch) bestMatch = p.matched_count; });

    var missBest = '-';
    var missP = allPreds.filter(function(p) {
      return p.target_draw_no === dno && p.brain_tag === 'miss_analysis' && p.matched_count >= 0;
    });
    if (missP.length) {
      var mb = 0;
      missP.forEach(function(p) { if (p.matched_count > mb) mb = p.matched_count; });
      missBest = mb + '개';
    }

    var snakeBest = '-';
    var snakeP = allPreds.filter(function(p) {
      return p.target_draw_no === dno && p.brain_tag === 'snake' && p.matched_count >= 0;
    });
    if (snakeP.length) {
      var sb = 0;
      snakeP.forEach(function(p) { if (p.matched_count > sb) sb = p.matched_count; });
      snakeBest = sb + '개';
    }

    html += '<tr>';
    html += '<td>' + dno + '회</td>';
    html += '<td>' + bestMatch + '개</td>';
    html += '<td>' + missBest + '</td>';
    html += '<td>' + snakeBest + '</td>';
    html += '</tr>';
  });

  html += '</tbody></table>';

  if (missDrawNos.length > _specialMissListLimit) {
    var remaining = missDrawNos.length - _specialMissListLimit;
    html += '<button class="special-more-btn" onclick="specialShowMoreMiss()">+ 더보기 (' + remaining + '건 남음)</button>';
  }

  el.innerHTML = html;
}

function specialShowMoreMiss() {
  _specialMissListLimit += 20;
  loadSpecialForce();
}
