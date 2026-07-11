/**
 * 테스트로또 회차 정밀 분석 상세페이지
 */

const BRAINS = [
  { tag: 'stat', name: '통계요정', color: '#3b82f6', short_desc: '최근 빈도·끝수·이월수로 자주 나온 흐름을 잡는다' },
  { tag: 'markov', name: '흐름술사', color: '#10b981', short_desc: '직전 회차와의 전이·궁합수 연결을 추적한다' },
  { tag: 'review', name: '복습왕', color: '#f59e0b', short_desc: '과거 오답을 복습해 놓쳤던 구간을 보정한다' },
];

const AUX_BRAINS_META = [
  { tag: 'miss_aux', name: '오답탐정', color: '#a855f7', short_desc: '자주 틀린 패턴을 찾아 경고한다' },
  { tag: 'pattern_aux', name: '패턴돋보기', color: '#ec4899', short_desc: '쌍수·연속수·AC값 신호를 읽는다' },
  { tag: 'balance_aux', name: '균형지킴이', color: '#06b6d4', short_desc: '홀짝·고저·합계 균형을 점검한다' },
  { tag: 'referee_aux', name: '심판관', color: '#64748b', short_desc: '세트 간 겹침·쏠림을 최종 판정한다' },
];

const PATTERN_LABELS = {
  carry_over: '이월수',
  ending_digit: '끝수',
  consecutive: '연속수',
  overdue: '미출(장기)',
  odd_even: '홀짝 균형',
  pair: '쌍수(동반출현)',
};

const ADJUSTMENT_LABELS = {
  carry_over_boost: '이월수 가중',
  ending_digit_boost: '끝수 가중',
  pair_boost: '쌍수 가중',
  consecutive_boost: '연속수 가중',
  overdue_boost: '미출 가중',
  odd_even_balance: '홀짝 균형',
};

const BRAIN_NAME = Object.fromEntries(BRAINS.map((b) => [b.tag, b.name]));

const MIN_TIER_MATCH = 3; // 5등 이상 (3개 적중) — 구버전 호환
const MIN_TIER_RANK = 1; // tier_rank 1~5 = 1~5등

let _drawList = [];
let _hitDrawList = [];
let _drawDates = {};
let _currentDraw = 2;
let _currentBrain = 'stat';
let _mode = 'single';
let _detailCache = {};

function _params() {
  return new URLSearchParams(window.location.search);
}

function _setUrl(params) {
  const q = new URLSearchParams(params);
  window.history.replaceState({}, '', `${window.location.pathname}?${q.toString()}`);
}

function _ballHtml(n, cls) {
  return `<span class="tld-ball ${cls}" aria-label="번호 ${n}">${n}</span>`;
}

function _matchBadge(n) {
  if (n >= 3) return 'tld-match-badge--good';
  if (n >= 1) return 'tld-match-badge--mid';
  return 'tld-match-badge--low';
}

function _tierLabel(mc, bonusMatched) {
  const bm = bonusMatched ? 1 : 0;
  if (mc >= 6) return '1등';
  if (mc === 5 && bm) return '2등';
  if (mc === 5) return '3등';
  if (mc === 4) return '4등';
  if (mc >= 3) return '5등';
  return '';
}

function _setTierRank(setItem, detail) {
  if (setItem.tier_rank != null && setItem.tier_label) {
    return {
      mc: Number(setItem.matched_count) || 0,
      bm: Number(setItem.bonus_matched) || 0,
      tier: setItem.tier_label,
      tierRank: Number(setItem.tier_rank) || 0,
    };
  }
  const actual = detail.actual_nums || [];
  const bonus = detail.bonus;
  const nums = setItem.nums || [];
  const actualSet = new Set(actual);
  const mc = nums.filter((n) => actualSet.has(n)).length;
  const bm = bonus && nums.includes(bonus);
  const tierRank = _tierRankFromMatch(mc, bm);
  return { mc, bm, tier: _tierLabel(mc, bm), tierRank };
}

function _tierRankFromMatch(mc, bonusMatched) {
  const bm = bonusMatched ? 1 : 0;
  if (mc >= 6) return 1;
  if (mc === 5 && bm) return 2;
  if (mc === 5) return 3;
  if (mc === 4) return 4;
  if (mc >= 3) return 5;
  return 0;
}

function _isHitTier(tierRank, mc) {
  return (Number(tierRank) || 0) > 0 || (Number(mc) || 0) >= MIN_TIER_MATCH;
}

function _sortNumsHitFirst(nums, actual) {
  const actualSet = new Set(actual || []);
  const hits = nums.filter((n) => actualSet.has(n)).sort((a, b) => a - b);
  const misses = nums.filter((n) => !actualSet.has(n)).sort((a, b) => a - b);
  return [...hits, ...misses];
}

function _ballsInline(nums, actual, bonus) {
  const actualSet = new Set(actual || []);
  const ordered = _sortNumsHitFirst(nums, actual);
  const balls = ordered
    .map((n) => {
      const hit = actualSet.has(n);
      return _ballHtml(n, hit ? 'tld-ball--hit' : 'tld-ball--miss');
    })
    .join('');
  const bonusHtml = bonus
    ? `<span class="tld-inline-bonus">${_ballHtml(bonus, 'tld-ball--bonus')}<span class="tld-bonus-tag">보너스</span></span>`
    : '';
  return `<span class="tld-inline-balls">${balls}${bonusHtml}</span>`;
}

function _asDrawNo(n) {
  const v = parseInt(n, 10);
  return Number.isFinite(v) && v > 0 ? v : null;
}

function _brainShortDesc(tag, detail) {
  const meta = detail?.brain_meta?.[tag];
  if (meta?.short_desc) return meta.short_desc;
  const b = BRAINS.find((x) => x.tag === tag);
  return b?.short_desc || '';
}

function _confBarHtml(confidence) {
  const pct = Math.min(100, Math.max(0, Number(confidence) || 0));
  return `<span class="tld-conf-bar" title="신뢰도 ${pct.toFixed(1)}%"><span class="tld-conf-bar__fill" style="width:${pct}%"></span><span class="tld-conf-bar__txt">${pct.toFixed(1)}%</span></span>`;
}

function _auxLevelClass(level) {
  if (level === 'ok') return 'tld-aux-signal--ok';
  if (level === 'warn') return 'tld-aux-signal--warn';
  return 'tld-aux-signal--alert';
}

function _matchLabel(n) {
  if (n >= 3) return '5등+';
  if (n >= 1) return '보통';
  return '미적중';
}

async function _loadHitDrawList(brainTag) {
  try {
    const data = await _fetchJson(
      `/api/testlotto/detail/draws-hit?brain_tag=${encodeURIComponent(brainTag)}&min_match=${MIN_TIER_MATCH}`
    );
    _hitDrawList = (data.draws || []).map(Number).sort((a, b) => b - a);
  } catch (e) {
    console.warn('5등+ 회차 목록', e);
    _hitDrawList = [];
  }
  _renderDrawSelect();
}

function _renderDrawSelect() {
  const sel = document.getElementById('tldDrawSelect');
  if (!sel) return;
  const list = _drawList.length ? _drawList : [];
  if (!list.length) {
    sel.innerHTML = '<option value="">회차 없음</option>';
    return;
  }
  const hitSet = new Set(_hitDrawList);
  sel.innerHTML = list
    .map((n) => {
      const dt = _drawDates[n] ? ` · ${_formatDrawDateShort(_drawDates[n])}` : '';
      const hitTag = hitSet.has(n) ? ' ★5등+' : '';
      return `<option value="${n}">제 ${n}회${dt}${hitTag}</option>`;
    })
    .join('');
  _syncDrawControls();
  _updateNavButtons();
}

function _navDrawStep(delta) {
  if (!_drawList.length) return null;
  const cur = _asDrawNo(_currentDraw);
  if (!cur) return null;
  let idx = _drawList.indexOf(cur);
  if (idx < 0) {
    if (delta > 0) {
      return _drawList.find((d) => d < cur) ?? null;
    }
    const newer = _drawList.filter((d) => d > cur);
    return newer.length ? Math.min(...newer) : null;
  }
  const newIdx = idx + delta;
  if (newIdx < 0 || newIdx >= _drawList.length) return null;
  return _drawList[newIdx];
}

function _updateNavButtons() {
  const prevBtn = document.getElementById('tldNavPrev');
  const nextBtn = document.getElementById('tldNavNext');
  if (!prevBtn || !nextBtn) return;
  const canPrev = _navDrawStep(1) != null;
  const canNext = _navDrawStep(-1) != null;
  prevBtn.disabled = !canPrev;
  nextBtn.disabled = !canNext;
  prevBtn.setAttribute('aria-disabled', canPrev ? 'false' : 'true');
  nextBtn.setAttribute('aria-disabled', canNext ? 'false' : 'true');
}

async function _goToDraw(drawNo) {
  const d = _asDrawNo(drawNo);
  if (!d) return;
  _currentDraw = d;
  _syncDrawControls();
  _updateNavButtons();
  _setUrl({ draw: _currentDraw, brain: _currentBrain, mode: _mode });
  await _refreshView();
}

async function _fetchJson(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`서버 응답 오류 (${r.status})`);
  return r.json();
}

async function _loadDrawList() {
  const data = await _fetchJson('/api/testlotto/draws?limit=10000');
  const rows = data.draws || [];
  _drawDates = {};
  rows.forEach((d) => {
    const n = parseInt(d.draw_no, 10);
    if (n > 0) {
      _drawDates[n] = d.draw_date || '';
    }
  });
  _drawList = Object.keys(_drawDates)
    .map(Number)
    .sort((a, b) => b - a);
  _renderDrawSelect();
}

function _formatDrawDateShort(dateStr) {
  if (!dateStr) return '';
  const p = dateStr.split('-');
  if (p.length === 3) return `${p[0]}.${p[1]}.${p[2]}`;
  return dateStr;
}

async function _loadProgressMeta() {
  try {
    const p = await _fetchJson('/api/testlotto/walkforward/progress');
    const el = document.getElementById('tldProgressMeta');
    if (el) {
      el.textContent = `누적 복습 ${p.review_draws || 0}회차 · 분석 기록 ${p.feature_rows || 0}건`;
    }
  } catch (e) {
    console.warn('진행 현황', e);
  }
}

function _selectBrain(tag) {
  if (_currentBrain === tag) return;
  _currentBrain = tag;
  _setUrl({ draw: _currentDraw, brain: tag, mode: _mode });
  const cached = _detailCache[_currentDraw];
  if (cached) {
    _renderBrainVerdicts(cached);
    _renderBrainScorecards(cached);
    _renderBrainDetail(cached, tag);
    _renderAuxBrains(cached);
    _loadLearnSummary(tag);
    const bname = BRAIN_NAME[tag] || tag;
    const status = document.getElementById('tldStatus');
    if (status) status.textContent = `제 ${_currentDraw}회 · ${bname} 분석 표시 중`;
  } else {
    _refreshView();
  }
  _loadHitDrawList(tag);
}

function _brainBestMatch(brain) {
  if (brain?.tier_rank > 0) {
    return Number(brain.matched_count) || 0;
  }
  const sets = brain?.predicted_sets || [];
  if (sets.length) {
    return Math.max(...sets.map((s) => Number(s.matched_count) || 0));
  }
  return Number(brain?.matched_count) || 0;
}

function _brainTierLabel(brain) {
  if (!brain) return '기록 없음';
  if (brain.tier_label && brain.tier_rank > 0) return brain.tier_label;
  if (brain.tier_label === '미적중') return '미적중';
  const mc = _brainBestMatch(brain);
  return _matchLabel(mc) === '5등+' ? '5등' : _matchLabel(mc) === '보통' ? '보통' : '미적중';
}

function _verdictClass(tierRank) {
  const tr = Number(tierRank) || 0;
  if (tr >= 1 && tr <= 2) return 'tld-verdict--gold';
  if (tr >= 3 && tr <= 4) return 'tld-verdict--good';
  if (tr === 5) return 'tld-verdict--mid';
  return 'tld-verdict--low';
}

function _renderBrainVerdicts(detail) {
  const wrap = document.getElementById('tldBrainVerdicts');
  if (!wrap) return;
  const verdictMap = Object.fromEntries((detail.brain_verdicts || []).map((v) => [v.brain_tag, v]));
  wrap.innerHTML = BRAINS.map((b) => {
    const v = verdictMap[b.tag];
    const active = _currentBrain === b.tag;
    const has = v?.has_review;
    const tier = has ? v.tier_label || '미적중' : '기록 없음';
    const mc = has ? `${v.matched_count || 0}/6` : '—';
    const setNo = has && v.best_set_no ? `best ${v.best_set_no}세트` : '';
    const tr = has ? Number(v.tier_rank) || 0 : -1;
    const desc = v?.short_desc || _brainShortDesc(b.tag, detail);
    return (
      `<button type="button" class="tld-verdict ${_verdictClass(tr)}${active ? ' tld-verdict--active' : ''}${!has ? ' tld-verdict--empty' : ''}" ` +
      `data-brain="${b.tag}" style="--brain-color:${b.color}" title="${desc}">` +
      `<span class="tld-verdict__name">${b.name}</span>` +
      `<span class="tld-verdict__desc">${desc}</span>` +
      `<span class="tld-verdict__tier">${tier}</span>` +
      `<span class="tld-verdict__meta">${mc}${setNo ? ' · ' + setNo : ''}</span>` +
      `</button>`
    );
  }).join('');
  wrap.querySelectorAll('.tld-verdict').forEach((btn) => {
    btn.addEventListener('click', () => _selectBrain(btn.dataset.brain));
  });
}

function _renderBrainScorecards(detail) {
  const wrap = document.getElementById('tldBrainScorecards');
  if (!wrap) return;
  const brainMap = Object.fromEntries((detail.brains || []).map((b) => [b.brain_tag, b]));
  wrap.innerHTML = BRAINS.map((b) => {
    const data = brainMap[b.tag];
    const mc = data ? _brainBestMatch(data) : null;
    const has = !!data;
    const active = _currentBrain === b.tag;
    const setCount = data?.predicted_sets?.length || (has ? 1 : 0);
    const scoreText = has ? `best ${mc}개 · ${setCount}세트` : '기록 없음';
    const grade = has ? _brainTierLabel(data) : '';
    const pct = has ? Math.round((mc / 6) * 100) : 0;
    const desc = data?.short_desc || _brainShortDesc(b.tag, detail);
    return (
      `<button type="button" role="tab" aria-selected="${active}" ` +
      `class="tld-scorecard${active ? ' tld-scorecard--active' : ''}${!has ? ' tld-scorecard--empty' : ''}" ` +
      `data-brain="${b.tag}" style="--brain-color:${b.color}" title="${desc}">` +
      `<span class="tld-scorecard__name">${b.name}</span>` +
      `<span class="tld-scorecard__desc">${desc}</span>` +
      `<span class="tld-scorecard__ring" style="--pct:${pct}"><span class="tld-scorecard__mc">${has ? mc + '/6' : '—'}</span></span>` +
      `<span class="tld-scorecard__label">${scoreText}${grade ? ' · ' + grade : ''}</span>` +
      `</button>`
    );
  }).join('');
  wrap.querySelectorAll('.tld-scorecard').forEach((btn) => {
    btn.addEventListener('click', () => _selectBrain(btn.dataset.brain));
  });
}

function _renderAuxBrains(detail) {
  const wrap = document.getElementById('tldAuxBrains');
  if (!wrap) return;
  const auxList = detail.aux_brains || [];
  if (!auxList.length) {
    wrap.innerHTML = '<p class="tld-empty-inline">보조뇌 신호 데이터가 없습니다.</p>';
    return;
  }
  wrap.innerHTML = auxList
    .map((aux) => {
      const meta = AUX_BRAINS_META.find((a) => a.tag === aux.brain_tag) || {};
      const color = meta.color || '#64748b';
      const desc = aux.short_desc || meta.short_desc || '';
      const actual = aux.on_actual || {};
      const onPred = (aux.on_predict_brains || [])
        .map(
          (p) =>
            `<li class="tld-aux-pred ${_auxLevelClass(p.level)}">` +
            `<span class="tld-aux-pred__name">${p.predict_name || p.predict_tag}</span>` +
            `<span class="tld-aux-pred__signal">${p.signal || ''}</span>` +
            `</li>`
        )
        .join('');
      return `<article class="tld-aux-card" style="--aux-color:${color}">
        <header class="tld-aux-card__head">
          <span class="tld-aux-card__badge">신호/경고</span>
          <h5 class="tld-aux-card__name">${aux.brain_name || meta.name}</h5>
          <p class="tld-aux-card__desc">${desc}</p>
        </header>
        <div class="tld-aux-card__actual ${_auxLevelClass(actual.level)}">
          <span class="tld-aux-card__label">실제 당첨</span>
          <span class="tld-aux-card__signal">${actual.signal || '—'}</span>
        </div>
        <ul class="tld-aux-pred-list">${onPred || '<li class="tld-aux-pred tld-muted">예측뇌 평가 없음</li>'}</ul>
      </article>`;
    })
    .join('');
}

function _renderWrongNote(detail, brain) {
  const wn = brain.wrong_note;
  if (!wn) return '';
  const actual = detail.actual_nums || [];
  const pred = wn.best_nums || [];
  const actualSet = new Set(actual);
  const predSet = new Set(pred);
  const explainMap = Object.fromEntries((wn.num_explains || []).map((e) => [e.num, e.tags || []]));

  const predCells = pred
    .map((n) => {
      const hit = actualSet.has(n);
      const cls = hit ? 'tld-wn-cell--hit' : 'tld-wn-cell--miss';
      const tags = (explainMap[n] || [])
        .map((t) => `<span class="tld-wn-tag">${t}</span>`)
        .join('');
      return `<div class="tld-wn-cell ${cls}">
        ${_ballHtml(n, hit ? 'tld-ball--hit' : 'tld-ball--miss')}
        <div class="tld-wn-tags">${tags || '<span class="tld-wn-tag tld-wn-tag--muted">근거산출</span>'}</div>
      </div>`;
    })
    .join('');

  const actualCells = actual
    .map((n) => {
      const caught = predSet.has(n);
      const cls = caught ? 'tld-wn-cell--hit' : 'tld-wn-cell--ghost';
      return `<div class="tld-wn-cell ${cls}">
        ${_ballHtml(n, caught ? 'tld-ball--hit' : 'tld-ball--actual-miss')}
        ${caught ? '' : '<span class="tld-wn-ghost-lbl">놓침</span>'}
      </div>`;
    })
    .join('');

  return `<div class="tld-wrong-note">
    <p class="tld-wn-narrative">${wn.narrative || ''}</p>
    <div class="tld-wn-compare">
      <div class="tld-wn-row">
        <span class="tld-wn-label">예측 <strong>${wn.best_set_no || brain.best_set_no || '?'}세트</strong></span>
        <div class="tld-wn-balls">${predCells}</div>
      </div>
      <div class="tld-wn-row tld-wn-row--actual">
        <span class="tld-wn-label">실제 당첨</span>
        <div class="tld-wn-balls">${actualCells}</div>
      </div>
    </div>
    <p class="tld-wn-legend">
      <span class="tld-wn-legend__hit">● 맞음</span>
      <span class="tld-wn-legend__miss">● 틀린 예측</span>
      <span class="tld-wn-legend__ghost">● 놓침(실제만)</span>
    </p>
  </div>`;
}

function _renderAlignedCompare(detail, predNums) {
  const actual = detail.actual_nums || [];
  const pred = predNums || [];
  const hitSet = new Set(pred.filter((n) => actual.includes(n)));
  const actualSet = new Set(actual);
  const missedActual = actual.filter((n) => !pred.includes(n));

  const predCells = pred
    .map((n) => {
      const isHit = hitSet.has(n);
      return `<div class="tld-slot${isHit ? ' tld-slot--hit' : ' tld-slot--miss'}">` +
        `${_ballHtml(n, isHit ? 'tld-ball--hit' : 'tld-ball--miss')}` +
        `<span class="tld-slot__mark" aria-label="${isHit ? '적중' : '미적중'}">${isHit ? '✓' : '✗'}</span>` +
        `</div>`;
    })
    .join('');

  const actualCells = actual
    .map((n) => {
      const wasMissed = !pred.includes(n);
      return `<div class="tld-slot${wasMissed ? ' tld-slot--actual-miss' : ' tld-slot--actual-hit'}">` +
        `${_ballHtml(n, 'tld-ball--actual')}` +
        `</div>`;
    })
    .join('');

  const missedRow = missedActual.length
    ? `<div class="tld-aligned-row tld-aligned-row--missed">` +
      `<span class="tld-aligned-label">놓친 번호</span>` +
      `<div class="tld-aligned-slots">${missedActual.map((n) => `<div class="tld-slot tld-slot--missed-only">${_ballHtml(n, 'tld-ball--actual-miss')}</div>`).join('')}</div>` +
      `</div>`
    : '';

  return (
    `<div class="tld-aligned-compare">` +
    `<div class="tld-aligned-row"><span class="tld-aligned-label">실제 당첨</span><div class="tld-aligned-slots">${actualCells}</div></div>` +
    `<div class="tld-aligned-row tld-aligned-row--pred"><span class="tld-aligned-label">이 뇌 예측</span><div class="tld-aligned-slots">${predCells}</div></div>` +
    missedRow +
    `</div>`
  );
}

function _renderSetRow(detail, setItem, isBest) {
  const nums = setItem.nums || [];
  const { mc, tier } = _setTierRank(setItem, detail);
  const tierTag = tier && tier !== '미적중' ? ` <em class="tld-tier-tag">${tier}</em>` : '';
  const conf = setItem.confidence != null ? _confBarHtml(setItem.confidence) : '';
  const isTopConf =
    detail.brains &&
    (() => {
      const brain = (detail.brains || []).find((b) => b.brain_tag === _currentBrain);
      return brain && Number(brain.most_confident_set_no) === Number(setItem.set_no);
    })();
  return `<div class="tld-set-row${isBest ? ' tld-set-row--best' : ''}${isTopConf ? ' tld-set-row--topconf' : ''}">
    <div class="tld-set-row__head">
      <span class="tld-set-row__label">${setItem.set_no || '?'}세트${isBest ? ' <em class="tld-best-tag">BEST</em>' : ''}${isTopConf ? ' <em class="tld-conf-tag">최고신뢰</em>' : ''}</span>
      <span class="tld-set-row__conf">${conf}</span>
      <span class="tld-match-badge ${_matchBadge(mc)}">${mc}개 적중${tierTag}</span>
    </div>
    ${_renderAlignedCompare(detail, nums)}
  </div>`;
}

function _renderSetRowCompact(detail, setItem) {
  const { mc, tier } = _setTierRank(setItem, detail);
  const tierTag = tier ? `<span class="tld-tier-tag">${tier}</span>` : '';
  const conf = setItem.confidence != null ? _confBarHtml(setItem.confidence) : '';
  return `<div class="tld-set-compact">
    <span class="tld-set-compact__label">${setItem.set_no || '?'}세트</span>
    ${conf}
    <span class="tld-match-badge ${_matchBadge(mc)}">${mc}개${tierTag}</span>
    ${_ballsInline(setItem.nums || [], detail.actual_nums, detail.bonus)}
  </div>`;
}

function _renderBrainSets(detail, brain) {
  const sets = brain.predicted_sets || [];
  if (!sets.length) {
    const single = brain.predicted_nums || [];
    if (!single.length) return '';
    const item = { set_no: 1, nums: single, matched_count: brain.matched_count };
    const { mc, tier, tierRank } = _setTierRank(item, detail);
    if (_isHitTier(tierRank, mc)) {
      return _renderSetRow(detail, item, true);
    }
    return `<details class="tld-miss-dropdown" open>
      <summary class="tld-miss-dropdown__summary">미적중 세트 <span class="tld-muted">(1건)</span></summary>
      <div class="tld-miss-dropdown__body">${_renderSetRowCompact(detail, item)}</div>
    </details>`;
  }
  const bestNo = brain.best_set_no || 1;
  const enriched = sets.map((s) => {
    const { mc, tier, tierRank } = _setTierRank(s, detail);
    return { ...s, matched_count: mc, tier, tier_rank: tierRank };
  });
  const hitSets = enriched
    .filter((s) => _isHitTier(s.tier_rank, s.matched_count))
    .sort((a, b) => (a.tier_rank || 99) - (b.tier_rank || 99) || b.matched_count - a.matched_count);
  const missSets = enriched
    .filter((s) => !_isHitTier(s.tier_rank, s.matched_count))
    .sort((a, b) => b.matched_count - a.matched_count || a.set_no - b.set_no);

  const hitHtml = hitSets
    .map((s) => _renderSetRow(detail, s, s.set_no === bestNo))
    .join('');

  const missHtml = missSets.length
    ? `<details class="tld-miss-dropdown">
        <summary class="tld-miss-dropdown__summary">미적중 세트 <span class="tld-muted">(${missSets.length}건 · 적중 순)</span></summary>
        <div class="tld-miss-dropdown__body">${missSets.map((s) => _renderSetRowCompact(detail, s)).join('')}</div>
      </details>`
    : '';

  if (!hitHtml && !missHtml) return '';

  return `<div class="tld-sets-panel">
    <h4 class="tld-sets-title">5세트 예측 · best ${bestNo}세트로 학습 · <span class="tld-sets-filter">5등+ ${hitSets.length}건 표시</span></h4>
    ${hitHtml || '<p class="tld-empty-inline">5등 이상 적중 세트 없음</p>'}
    ${missHtml}
  </div>`;
}

function _feedbackSentences(labels, adjEntries) {
  const lines = [];
  labels.forEach((l) => {
    const key = Object.entries(PATTERN_LABELS).find(([, v]) => v === l)?.[0];
    const adjKey = key === 'ending_digit' ? 'ending_digit_boost' : key === 'carry_over' ? 'carry_over_boost' : key === 'consecutive' ? 'consecutive_boost' : key === 'odd_even' ? 'odd_even_balance' : key === 'pair' ? 'pair_boost' : key === 'overdue' ? 'overdue_boost' : null;
    const boost = adjKey ? adjEntries.find(([k]) => k === adjKey) : null;
    if (boost) {
      lines.push(`${l} 패턴을 놓쳤습니다 → ${ADJUSTMENT_LABELS[boost[0]] || boost[0]} <strong>+${Number(boost[1]).toFixed(2)}</strong>`);
    } else if (l) {
      lines.push(`${l} 패턴을 놓쳤습니다`);
    }
  });
  adjEntries.forEach(([k, v]) => {
    if (!lines.some((ln) => ln.includes(ADJUSTMENT_LABELS[k] || k))) {
      lines.push(`${ADJUSTMENT_LABELS[k] || k} 조정 <strong>+${Number(v).toFixed(2)}</strong>`);
    }
  });
  return lines;
}

function _formatWon(n) {
  const v = Number(n) || 0;
  if (v <= 0) return '—';
  if (v >= 100000000) return `${(v / 100000000).toFixed(1).replace(/\.0$/, '')}억원`;
  if (v >= 10000) return `${Math.round(v / 10000).toLocaleString('ko-KR')}만원`;
  return `${v.toLocaleString('ko-KR')}원`;
}

function _formatWonFull(n) {
  const v = Number(n) || 0;
  if (v <= 0) return '—';
  return `${v.toLocaleString('ko-KR')}원`;
}

function _formatDrawDate(dateStr) {
  if (!dateStr) return '미확인';
  try {
    const d = new Date(dateStr + 'T12:00:00');
    const dows = ['일', '월', '화', '수', '목', '금', '토'];
    return `${_formatDrawDateShort(dateStr)} (${dows[d.getDay()]}요일)`;
  } catch (e) {
    return dateStr;
  }
}

function _renderDrawHeader(detail) {
  const title = document.getElementById('tldDrawTitle');
  const sub = document.getElementById('tldDrawSub');
  if (title) title.textContent = `제 ${detail.draw_no}회 로또 6/45`;
  if (sub) {
    const sales = detail.total_sales
      ? `총 판매액 ${_formatWon(detail.total_sales)}`
      : '총 판매액 미확인';
    sub.textContent = `추첨일 ${_formatDrawDate(detail.draw_date)} · ${sales}`;
  }
  _renderKpiStrip(detail);
}

function _renderKpiStrip(detail) {
  const el = document.getElementById('tldKpiStrip');
  const f = detail.features || {};
  if (!el) return;
  const items = [];
  if (detail.total_sales > 0) items.push({ label: '총 판매액', value: _formatWon(detail.total_sales) });
  if (detail.total_winners > 0) {
    items.push({ label: '전체 당첨자', value: `${Number(detail.total_winners).toLocaleString('ko-KR')}명` });
  }
  if (f.sum_total != null) items.push({ label: '번호 합계', value: String(f.sum_total) });
  if (f.odd_count != null) items.push({ label: '홀·짝', value: `${f.odd_count} : ${f.even_count}` });
  if (f.ac_value != null) items.push({ label: 'AC값', value: String(f.ac_value) });
  if (f.combo_rank_814 != null) {
    items.push({ label: '814만 순위', value: `${Number(f.combo_rank_814).toLocaleString('ko-KR')}위` });
  }
  if (!items.length) {
    el.innerHTML = '';
    return;
  }
  el.innerHTML = items
    .map((it) => `<div class="tld-kpi"><span class="tld-kpi__label">${it.label}</span><span class="tld-kpi__value">${it.value}</span></div>`)
    .join('');
}

function _renderPrizeSummary(detail) {
  const el = document.getElementById('tldPrizeSummary');
  const tiers = detail.prize_tiers || [];
  if (!el) return;
  if (!tiers.length) {
    el.innerHTML = '';
    return;
  }
  const t1 = tiers.find((t) => t.tier_rank === 1);
  el.innerHTML = `
    <div class="tld-prize-hero">
      <div class="tld-prize-hero__item">
        <span class="tld-prize-hero__label">1등 1게임당</span>
        <span class="tld-prize-hero__value tld-prize-hero__value--gold">${_formatWonFull(t1?.prize_per_game)}</span>
        <span class="tld-prize-hero__sub">${t1?.winner_count ? `${t1.winner_count.toLocaleString('ko-KR')}명 당첨` : ''}</span>
      </div>
      <div class="tld-prize-hero__item">
        <span class="tld-prize-hero__label">회차 총 판매액</span>
        <span class="tld-prize-hero__value">${detail.total_sales ? _formatWon(detail.total_sales) : '—'}</span>
      </div>
    </div>
    <div class="tld-prize-cards">
      ${tiers
        .map((t) => {
          const cls = t.tier_rank === 1 ? ' tld-prize-card--tier1' : '';
          return `<div class="tld-prize-card${cls}">
            <span class="tld-prize-card__rank">${t.tier_label || t.tier_rank + '등'}</span>
            <span class="tld-prize-card__money">${_formatWonFull(t.prize_per_game)}</span>
            <span class="tld-prize-card__winners">${t.winner_count > 0 ? t.winner_count.toLocaleString('ko-KR') + '명' : '—'}</span>
            <span class="tld-prize-card__hint">${t.match_hint || ''}</span>
          </div>`;
        })
        .join('')}
    </div>`;
}

function _renderPrizeTiers(detail) {
  const body = document.getElementById('tldPrizeBody');
  const note = document.getElementById('tldPrizeNote');
  const tiers = detail.prize_tiers || [];
  _renderPrizeSummary(detail);
  if (!body) return;
  if (!tiers.length) {
    body.innerHTML =
      '<tr><td colspan="5" class="tld-empty">등수별 당첨 정보가 없습니다. 「archive/sync」 또는 동행복권 동기화가 필요합니다.</td></tr>';
    if (note) note.textContent = '';
    return;
  }
  body.innerHTML = tiers
    .map((t) => {
      const cls = t.tier_rank === 1 ? ' class="tld-tier-1"' : '';
      const wc = t.winner_count > 0 ? `${t.winner_count.toLocaleString('ko-KR')}명` : '—';
      const total = t.total_prize > 0 ? _formatWonFull(t.total_prize) : (t.winner_count && t.prize_per_game ? _formatWonFull(t.winner_count * t.prize_per_game) : '—');
      return `<tr>
        <td${cls}>${t.tier_label || `${t.tier_rank}등`}</td>
        <td>${t.match_hint || '—'}</td>
        <td>${wc}</td>
        <td class="tld-money">${_formatWonFull(t.prize_per_game)}</td>
        <td class="tld-money">${total}</td>
      </tr>`;
    })
    .join('');
  if (note) {
    const src = detail.archive_synced_at ? `동기화 ${detail.archive_synced_at}` : '';
    note.textContent = detail.prize_tiers_complete
      ? `출처: 동행복권 lt645 (1~5등 전체)${src ? ' · ' + src : ''}`
      : '1등 정보만 표시 중입니다. archive/sync 실행 후 자동으로 채워집니다.';
  }
}

function _renderAnalysisGrid(detail) {
  const grid = document.getElementById('tldAnalysisGrid');
  const f = detail.features || {};
  if (!grid) return;

  const groups = [
    {
      title: '이월·연속',
      items: [
        ['이월수 개수', f.carry_over_count != null ? `${f.carry_over_count}개` : '—'],
        ['이월 번호', (f.carry_over_nums || []).join(', ') || '없음'],
        ['연속수 쌍', f.consecutive_count != null ? `${f.consecutive_count}쌍` : '—'],
      ],
    },
    {
      title: '끝수·구간',
      items: [
        ['끝수 분포', (f.ending_digits || []).join(', ') || '—'],
        [
          '구간(저·중·고)',
          Array.isArray(f.zone_low_mid_high) && f.zone_low_mid_high.length === 3
            ? `저 ${f.zone_low_mid_high[0]} · 중 ${f.zone_low_mid_high[1]} · 고 ${f.zone_low_mid_high[2]}`
            : '—',
        ],
      ],
    },
    {
      title: '미출·순위',
      items: [
        ['장기 미출', (f.gap_overdue_nums || []).join(', ') || '없음'],
        [
          '814만 조합 순위',
          f.combo_rank_814 != null ? `${Number(f.combo_rank_814).toLocaleString('ko-KR')}위` : '—',
        ],
      ],
    },
  ];

  grid.innerHTML = groups
    .map(
      (g) => `
    <div class="tld-analysis-card">
      <h4 class="tld-analysis-card__title">${g.title}</h4>
      <dl class="tld-analysis-dl">
        ${g.items.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')}
      </dl>
    </div>`
    )
    .join('');
}

function _renderActual(detail) {
  const balls = document.getElementById('tldActualBalls');
  if (!balls) return;
  const nums = detail.actual_nums || [];
  const main = nums.map((n) => _ballHtml(n, 'tld-ball--actual tld-ball--lg')).join('');
  const bonus = detail.bonus
    ? `<span class="tld-bonus-wrap">${_ballHtml(detail.bonus, 'tld-ball--bonus tld-ball--lg')}<span class="tld-bonus-tag">보너스</span></span>`
    : '';
  balls.innerHTML = main + bonus;
}

function _renderBrainDetail(detail, brainTag) {
  const brain = (detail.brains || []).find((b) => b.brain_tag === brainTag);
  const title = document.getElementById('tldBrainTitle');
  const compare = document.getElementById('tldBrainCompare');
  const missed = document.getElementById('tldMissedBlock');
  const feedback = document.getElementById('tldFeedbackBlock');
  const bmeta = BRAINS.find((b) => b.tag === brainTag);

  if (title) {
    const desc = brain?.short_desc || _brainShortDesc(brainTag, detail);
    title.innerHTML = `${bmeta?.name || '예측 뇌'} · 제 ${detail.draw_no}회 오답노트` +
      (desc ? `<span class="tld-brain-short-desc">${desc}</span>` : '');
  }

  if (!brain) {
    if (compare) {
      compare.innerHTML = `<div class="tld-empty-box">
        <p>이 회차에 <strong>${bmeta?.name || ''}</strong>의 복습 기록이 없습니다.</p>
        <p class="tld-empty-hint">메인 화면에서 「복습 루프」를 실행하면 예측·채점·오답 분석이 이곳에 기록됩니다.</p>
      </div>`;
    }
    if (missed) missed.innerHTML = '';
    if (feedback) feedback.innerHTML = '';
    return;
  }

  const mc = _brainBestMatch(brain);
  const tierText = _brainTierLabel(brain);
  const labels =
    brain.missed_pattern_labels ||
    (brain.missed_patterns || []).map((p) => PATTERN_LABELS[p] || p);
  const hitNums = (brain.hit_nums || []).join(', ') || '없음';
  const bestNo = brain.best_set_no || 1;
  const confLine = brain.confidence_summary || '';

  if (compare) {
    compare.innerHTML = `
      ${confLine ? `<p class="tld-conf-summary">${confLine}</p>` : ''}
      ${_renderWrongNote(detail, brain)}
      <details class="tld-sets-expand">
        <summary class="tld-sets-expand__summary">전체 5세트 펼치기 <span class="tld-muted">(best ${bestNo}세트 · ${tierText})</span></summary>
        <div class="tld-sets-expand__body">${_renderBrainSets(detail, brain)}</div>
      </details>`;
  }

  if (missed) {
    missed.innerHTML = `
      <h4 class="tld-sub-title">놓친 패턴 상세</h4>
      ${
        labels.length
          ? labels.map((l) => `<span class="tld-tag">${l}</span>`).join('')
          : '<span class="tld-empty-inline">특이 패턴 없음</span>'
      }`;
  }

  const fb = brain.feedback || {};
  const adj = fb.adjustments || {};
  const adjEntries = Object.entries(adj).filter(([, v]) => Number(v) > 0);
  const fbLines = _feedbackSentences(labels, adjEntries);
  if (feedback) {
    feedback.innerHTML = `
      <h4 class="tld-sub-title">이번 회차 학습</h4>
      <p class="tld-feedback-line">최근 평균 적중 <strong>${fb.recent_avg_match ?? '—'}</strong>개</p>
      ${
        fbLines.length
          ? `<ul class="tld-adj-list">${fbLines.map((ln) => `<li>${ln}</li>`).join('')}</ul>`
          : '<p class="tld-empty-inline">아직 누적된 조정값이 없습니다.</p>'
      }`;
  }
}

async function _loadLearnSummary(brainTag) {
  const el = document.getElementById('tldLearnSummary');
  if (!el) return;
  const bname = BRAIN_NAME[brainTag] || brainTag;
  try {
    const s = await _fetchJson(`/api/testlotto/detail/brain/${brainTag}/summary`);
    const adj = s.adjustments || {};
    const miss = s.miss_counts || {};
    const adjHtml = Object.entries(adj)
      .filter(([, v]) => Number(v) > 0)
      .map(([k, v]) => `<dd>${ADJUSTMENT_LABELS[k] || k} <strong>+${Number(v).toFixed(2)}</strong></dd>`)
      .join('');
    const missHtml = Object.entries(miss)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 6)
      .map(([k, v]) => `<dd>${PATTERN_LABELS[k] || k} <strong>${v}회</strong></dd>`)
      .join('');
    el.innerHTML = `
      <p class="tld-learn-brain">${bname}</p>
      <dl class="tld-learn">
        <dt>누적 복습</dt><dd>${s.review_count || 0}회 <span class="tld-muted">(최근 ${s.last_draw_no || '—'}회)</span></dd>
        <dt>평균 적중</dt><dd>${s.recent_avg_match ?? 0}개</dd>
        <dt>현재 가중치</dt><dd>${Number(s.current_weight ?? 1).toFixed(2)}</dd>
        <dt>기록 구간</dt><dd>${s.page_stats?.min_draw || '—'}회 ~ ${s.page_stats?.max_draw || '—'}회 <span class="tld-muted">(${s.page_stats?.records || 0}건)</span></dd>
        ${adjHtml ? '<dt>누적 조정</dt>' + adjHtml : ''}
        ${missHtml ? '<dt>자주 놓친 패턴</dt>' + missHtml : ''}
      </dl>`;
  } catch (e) {
    el.innerHTML = '<p class="tld-empty">학습 요약을 불러오지 못했습니다.</p>';
  }
}

async function _loadSingleDraw(drawNo) {
  const d = _asDrawNo(drawNo);
  if (!d) return;
  _currentDraw = d;
  const status = document.getElementById('tldStatus');
  if (status) status.textContent = `제 ${d}회 분석 데이터를 불러오는 중…`;
  try {
    let detail = _detailCache[d];
    if (!detail) {
      detail = await _fetchJson(`/api/testlotto/detail/draw/${d}`);
      if (detail.error) throw new Error(detail.error);
      _detailCache[d] = detail;
    }
    document.title = `테스트로또 · 제 ${d}회 정밀 분석`;
    _renderDrawHeader(detail);
    _renderActual(detail);
    _renderBrainVerdicts(detail);
    _renderBrainScorecards(detail);
    _renderBrainDetail(detail, _currentBrain);
    _renderAuxBrains(detail);
    _renderPrizeTiers(detail);
    _renderAnalysisGrid(detail);
    await _loadLearnSummary(_currentBrain);
    _syncDrawControls();
    _updateNavButtons();
    const bname = BRAIN_NAME[_currentBrain] || _currentBrain;
    if (status) {
      const inHit = _hitDrawList.includes(d);
      status.textContent = inHit
        ? `제 ${d}회 · ${bname} · 5등+ ${_hitDrawList.length}건 중`
        : `제 ${d}회 · ${bname} 분석 표시 중`;
    }
  } catch (e) {
    if (status) status.textContent = e.message || '불러오기 실패';
  }
}

async function _loadRangeTimeline() {
  const start = parseInt(document.getElementById('tldRangeStart')?.value, 10) || 2;
  const end = parseInt(document.getElementById('tldRangeEnd')?.value, 10) || 20;
  const title = document.getElementById('tldTimelineTitle');
  const body = document.getElementById('tldTimelineBody');
  const status = document.getElementById('tldStatus');
  const bmeta = BRAINS.find((b) => b.tag === _currentBrain);

  if (title) title.textContent = `${bmeta?.name || ''} · ${start}~${end}회 복습 흐름`;
  if (status) status.textContent = '구간 데이터를 불러오는 중…';

  try {
    const data = await _fetchJson(
      `/api/testlotto/detail/reviews?start=${start}&end=${end}&brain_tag=${_currentBrain}&limit=500`
    );
    if (!body) return;
    if (!data.items?.length) {
      body.innerHTML = `<tr><td colspan="5" class="tld-empty">${start}~${end}회 구간에 복습 기록이 없습니다.</td></tr>`;
      if (status) status.textContent = '복습 기록 없음';
      return;
    }
    body.innerHTML = data.items
      .map((it) => {
        const labels = (it.missed_patterns || []).map((p) => PATTERN_LABELS[p] || p);
        const pred = (it.predicted_nums || []).join(' · ');
        return `<tr data-draw="${it.draw_no}" class="tld-timeline-row" tabindex="0">
          <td><b>제 ${it.draw_no}회</b></td>
          <td class="tld-nums-cell">${pred}</td>
          <td><span class="tld-match-badge ${_matchBadge(it.matched_count)}">${it.matched_count}개</span></td>
          <td>${labels.map((l) => `<span class="tld-tag">${l}</span>`).join('') || '—'}</td>
          <td class="tld-narrative-cell">${it.narrative || '—'}</td>
        </tr>`;
      })
      .join('');
    body.querySelectorAll('.tld-timeline-row').forEach((tr) => {
      const go = () => {
        const d = _asDrawNo(tr.dataset.draw);
        if (!d) return;
        _mode = 'single';
        _applyModeUi();
        _goToDraw(d);
      };
      tr.addEventListener('click', go);
      tr.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') go();
      });
    });
    if (status) status.textContent = `총 ${data.total}건 중 ${data.items.length}건 표시`;
  } catch (e) {
    if (body) body.innerHTML = `<tr><td colspan="5">${e.message}</td></tr>`;
    if (status) status.textContent = '구간 불러오기 실패';
  }
}

function _applyModeUi() {
  const single = document.getElementById('tldSingleView');
  const range = document.getElementById('tldRangeView');
  const rangeRow = document.getElementById('tldRangeRow');
  document.querySelectorAll('.tld-mode-btn').forEach((btn) => {
    btn.classList.toggle('tld-mode-btn--active', btn.dataset.mode === _mode);
  });
  if (single) single.hidden = _mode !== 'single';
  if (range) range.hidden = _mode !== 'range';
  if (rangeRow) rangeRow.hidden = _mode !== 'range';
}

function _syncDrawControls() {
  const d = _asDrawNo(_currentDraw);
  if (d) _currentDraw = d;
  const sel = document.getElementById('tldDrawSelect');
  const inp = document.getElementById('tldDrawInput');
  if (sel && d) {
    const hasOpt = Array.from(sel.options).some((o) => parseInt(o.value, 10) === d);
    if (hasOpt) sel.value = String(d);
  }
  if (inp && d) inp.value = String(d);
}

async function _refreshView() {
  if (_mode === 'range') {
    await _loadRangeTimeline();
  } else {
    await _loadSingleDraw(_currentDraw);
  }
}

function _parseInitialFromUrl() {
  const p = _params();
  _currentDraw = _asDrawNo(p.get('draw')) || 1231;
  _currentBrain = p.get('brain') || 'stat';
  _mode = p.get('mode') === 'range' ? 'range' : 'single';
  const rs = parseInt(p.get('start'), 10);
  const re = parseInt(p.get('end'), 10);
  if (rs) document.getElementById('tldRangeStart').value = rs;
  if (re) document.getElementById('tldRangeEnd').value = re;
}

function _bindEvents() {
  document.getElementById('tldNavPrev')?.addEventListener('click', () => {
    const target = _navDrawStep(1);
    if (target != null) _goToDraw(target);
  });
  document.getElementById('tldNavNext')?.addEventListener('click', () => {
    const target = _navDrawStep(-1);
    if (target != null) _goToDraw(target);
  });
  document.getElementById('tldDrawSelect')?.addEventListener('change', (e) => {
    const d = _asDrawNo(e.target.value);
    if (d) _goToDraw(d);
  });
  document.getElementById('tldDrawInput')?.addEventListener('change', (e) => {
    const d = _asDrawNo(e.target.value);
    if (d) _goToDraw(d);
  });
  document.querySelectorAll('.tld-mode-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      _mode = btn.dataset.mode;
      _applyModeUi();
      _setUrl({
        draw: _currentDraw,
        brain: _currentBrain,
        mode: _mode,
        start: document.getElementById('tldRangeStart')?.value,
        end: document.getElementById('tldRangeEnd')?.value,
      });
      _refreshView();
    });
  });
  document.getElementById('tldRangeApply')?.addEventListener('click', () => {
    _setUrl({
      draw: _currentDraw,
      brain: _currentBrain,
      mode: 'range',
      start: document.getElementById('tldRangeStart')?.value,
      end: document.getElementById('tldRangeEnd')?.value,
    });
    _refreshView();
  });
}

async function initTestlottoDetailPage() {
  _parseInitialFromUrl();
  _applyModeUi();
  _bindEvents();
  await Promise.all([_loadDrawList(), _loadProgressMeta(), _loadHitDrawList(_currentBrain)]);
  _syncDrawControls();
  _updateNavButtons();
  await _refreshView();
}

document.addEventListener('DOMContentLoaded', initTestlottoDetailPage);
window.testlottoDetailRefresh = _refreshView;
