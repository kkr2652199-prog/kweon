/**
 * 4군 독립 페이지 — 부가 페이지 완성 · API /api/lotto4/v13/
 * 전역: window.lotto4SwitchBrainTab(tag), window.lotto4CopyKakaoText
 */
(function () {
  'use strict';

  const API = '/api/lotto4/v13';

  /** 구버전 DB brain_tag → 현행 v13 (표시·탭·필터 통일, DB 비변경) */
  const LEGACY_TO_CANONICAL = {
    v13_bayesian: 'v13_cdm',
    v13_graph: 'v13_cond_prob',
    v13_contrarian_v2: 'v13_gap',
    v13_gen: 'v13_diversity',
    v13_transformer: 'v13_seq',
    v13_trend: 'v13_struct',
    v13_rl: 'v13_evolution',
    v13_anti_popular: 'v13_ev',
  };

  /** Commander/엔진에서 숨김 처리하는 뇌 (구·신 태그 동의어는 canonical 로 판별) */
  const UI_HIDDEN_CANONICAL = new Set(['v13_cdm', 'v13_cond_prob']);

  /** walk-forward 위반 등으로 실예측 중단 — placeholder만 DB·UI에 남김 */
  const QUARANTINED_BRAINS = new Set(['v13_seq']);

  function canonicalBrainTag(tag) {
    const t = String(tag || '').toLowerCase();
    return LEGACY_TO_CANONICAL[t] || t;
  }

  function isUiHiddenBrain(rawTag) {
    return UI_HIDDEN_CANONICAL.has(canonicalBrainTag(rawTag));
  }

  function brainLabelForTag(rawTag) {
    const c = canonicalBrainTag(rawTag);
    return BRAIN_LABEL_TAB[c] || rawTag;
  }

  /** 탭: HIDDEN 제외. 주뇌는 구조·시퀀스만 노출 */
  const BRAIN_PRIMARY = ['v13_struct', 'v13_seq'];
  const BRAIN_SECONDARY = ['v13_diversity', 'v13_evolution', 'v13_gap', 'v13_ev', 'v13_ensemble'];
  const BRAIN_ORDER = BRAIN_PRIMARY.concat(BRAIN_SECONDARY);

  const BRAIN_LABEL_TAB = {
    v13_struct: '📐 구조예측',
    v13_cdm: '🎯 CDM',
    v13_seq: '🧬 시퀀스',
    v13_cond_prob: '🔗 조건부확률',
    v13_diversity: '🌈 다양성',
    v13_evolution: '🧬 진화',
    v13_ensemble: '🧠 앙상블',
    v13_gap: '📉 갭분석',
    v13_ev: '💎 기대값',
  };

  let _currentBrain = 'v13_struct';
  let _lastRows = [];
  let _lastDraw = null;
  let _nextDrawNo = 1;
  let _drawMin = 1;
  let _eliteTags = new Set();
  let _rankByTag = {};
  let _nanoByTag = {};
  let _countdownTimer = null;
  /** 적중 모달 내부 회차 (◀▶·점프용) */
  let _tierModalDraw = null;
  let _tierModalMode = 'predict';

  function setStatus(el, text, ok) {
    if (!el) return;
    el.textContent = text || '';
    el.classList.toggle('error', ok === false);
  }

  /** fetch 후 JSON 파싱·HTTP 오류 메시지 통일 (500 시 HTML/Plain Internal Server Error 대응) */
  async function fetchJsonHandled(url, options) {
    const res = await fetch(url, options || {});
    const text = await res.text();
    let data = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch (parseErr) {
        var snippet = text.replace(/\s+/g, ' ').trim().slice(0, 220);
        throw new Error(
          'HTTP ' +
            res.status +
            ' — 응답이 JSON이 아닙니다. ' +
            '(서버 오류 페이지·프록시·URL 불일치 가능) ' +
            snippet,
        );
      }
    } else {
      data = {};
    }
    if (!res.ok) {
      var detail = null;
      if (data) {
        if (typeof data.detail === 'string') detail = data.detail;
        else if (Array.isArray(data.detail))
          detail = data.detail
            .map(function (x) {
              return x.msg || JSON.stringify(x);
            })
            .join('; ');
        else if (data.message) detail = String(data.message);
        else if (typeof data.error === 'string') detail = data.error;
      }
      throw new Error(detail || 'HTTP ' + res.status);
    }
    return data;
  }

  function ballZoneClass(n) {
    const x = Number(n);
    if (x >= 1 && x <= 10) return 'ball z1';
    if (x <= 20) return 'ball z2';
    if (x <= 30) return 'ball z3';
    if (x <= 40) return 'ball z4';
    if (x <= 45) return 'ball z5';
    return 'ball z1';
  }

  function actualSetFromRow(row) {
    if (!row) return null;
    const keys = ['actual_1', 'actual_2', 'actual_3', 'actual_4', 'actual_5', 'actual_6'];
    const s = new Set();
    for (const k of keys) {
      if (row[k] == null || row[k] === '') return null;
      s.add(Number(row[k]));
    }
    return s;
  }

  function fmtNums(r) {
    return [r.num1, r.num2, r.num3, r.num4, r.num5, r.num6].map((x) => Number(x));
  }

  function renderBallsHtml(nums, hitSet, bonusNum) {
    const arr = nums
      .map((n) => Number(n))
      .filter((n) => !Number.isNaN(n))
      .sort((a, b) => a - b);
    let html = '<div class="balls">';
    arr.forEach((nn) => {
      let cls = ballZoneClass(nn);
      if (hitSet && hitSet.has(nn)) cls += ' hit';
      if (bonusNum != null && nn === Number(bonusNum)) cls += ' bonus-hit';
      html += '<span class="' + cls + '">' + nn + '</span>';
    });
    html += '</div>';
    return html;
  }

  function renderBonusBall(n) {
    const nn = Number(n);
    return '<span class="ball ball-bonus-only ' + ballZoneClass(nn).replace('ball ', '') + '">' + nn + '</span>';
  }

  function tierBadgeClass(tr) {
    if (tr === 1) return 'tier-badge t1';
    if (tr === 2) return 'tier-badge t2';
    if (tr === 3) return 'tier-badge t3';
    if (tr === 4) return 'tier-badge t4';
    return 'tier-badge t5';
  }

  function getDrawNoFromUi() {
    const sel = document.getElementById('drawSelect');
    const v = parseInt(sel && sel.value, 10);
    return v || null;
  }

  function setDrawNoUi(d) {
    const sel = document.getElementById('drawSelect');
    if (!sel) return;
    const o = Array.from(sel.options).find((x) => parseInt(x.value, 10) === d);
    if (o) sel.value = String(d);
    else {
      const opt = document.createElement('option');
      opt.value = String(d);
      opt.textContent = String(d) + '회';
      sel.appendChild(opt);
      sel.value = String(d);
    }
    const di = document.getElementById('drawDirectInput');
    if (di) di.value = String(d);
  }

  function rebuildDrawOptions(maxInclusive, minInclusive) {
    const sel = document.getElementById('drawSelect');
    if (!sel) return;
    const min = Math.max(1, Number(minInclusive != null ? minInclusive : _drawMin) || 1);
    const max = Math.max(min, Number(maxInclusive) || 1);
    _drawMin = min;
    const cur = getDrawNoFromUi();
    sel.innerHTML = '';
    for (let i = min; i <= max; i++) {
      const opt = document.createElement('option');
      opt.value = String(i);
      opt.textContent = i + '회';
      sel.appendChild(opt);
    }
    const use = cur && cur >= min && cur <= max ? cur : max;
    sel.value = String(use);
    const di = document.getElementById('drawDirectInput');
    if (di) di.value = String(use);
  }

  function switchView(name) {
    document.querySelectorAll('.view-panel').forEach((p) => {
      p.classList.toggle('active', p.getAttribute('data-view-panel') === name);
    });
    document.querySelectorAll('.nav-btn').forEach((b) => {
      b.classList.toggle('active', b.getAttribute('data-view') === name);
    });
  }

  /** 엔진3: 로또의 진실 — 막대 최대값 (카드3 LSTM 누수 스케일) */
  function truthBarMax(bars) {
    let max = 0.7894;
    (bars || []).forEach((b) => {
      const v = Number(b.value);
      if (Number.isFinite(v) && v > max) max = v;
    });
    return max * 1.08;
  }

  function renderTruthBarRow(label, value, maxVal, role) {
    const v = Number(value);
    const pct = maxVal > 0 ? Math.min(100, (v / maxVal) * 100) : 0;
    const roleClass = role ? ' truth-bar--' + role : '';
    return (
      '<div class="truth-bar-row">' +
      '<span class="truth-bar-label">' +
      escapeHtml(label) +
      '</span>' +
      '<div class="truth-bar-track">' +
      '<div class="truth-bar-fill' +
      roleClass +
      '" style="width:' +
      pct.toFixed(1) +
      '%"></div>' +
      '</div>' +
      '<span class="truth-bar-value">' +
      (Number.isFinite(v) ? v.toFixed(4) : '-') +
      '</span>' +
      '</div>'
    );
  }

  function renderTruthCards(data) {
    const host = document.getElementById('truthCardsHost');
    if (!host || !data) return;
    const cards = data.cards || [];
    let html = '';
    cards.forEach((card, idx) => {
      const maxVal = truthBarMax(card.bars);
      let barsHtml = '';
      (card.bars || []).forEach((b) => {
        barsHtml += renderTruthBarRow(b.label, b.value, maxVal, b.role);
      });
      html +=
        '<article class="card truth-card" data-truth-id="' +
        escapeHtml(card.id || '') +
        '">' +
        '<div class="truth-card-num">' +
        String(idx + 1) +
        '</div>' +
        '<h3 class="truth-card-title">' +
        escapeHtml(card.title || '') +
        '</h3>' +
        (card.subtitle
          ? '<p class="truth-card-sub">' + escapeHtml(card.subtitle) + '</p>'
          : '') +
        '<div class="truth-bars">' +
        barsHtml +
        '</div>' +
        '<p class="truth-card-desc">' +
        escapeHtml(card.description || '') +
        '</p>' +
        (card.source_note
          ? '<p class="truth-card-source"><code>' +
            escapeHtml(card.source_note) +
            '</code></p>'
          : '') +
        '</article>';
    });
    host.innerHTML = html;
    const banner = document.getElementById('truthBanner');
    if (banner && data.banner) banner.textContent = data.banner;
    const srcEl = document.getElementById('truthSources');
    if (srcEl && data.sources && data.sources.length) {
      srcEl.textContent = '데이터 출처: ' + data.sources.join(' · ');
    }
  }

  async function loadTruth() {
    const st = document.getElementById('truthStatus');
    setStatus(st, '불러오는 중…', true);
    try {
      const data = await fetchJsonHandled(API + '/truth');
      renderTruthCards(data);
      setStatus(st, '검증 수치 ' + (data.cards || []).length + '카드 표시', true);
    } catch (e) {
      setStatus(st, '오류: ' + (e.message || e), false);
    }
  }

  const STRATEGY_X_BRAIN_ORDER = [
    'strategy_x_popularity_freq',
    'strategy_x_popularity_pair',
    'strategy_x_shape',
    'strategy_x_cooccur',
    'strategy_x_hyena',
  ];
  const STRATEGY_X_PRIMARY = [
    'strategy_x_popularity_freq',
    'strategy_x_popularity_pair',
    'strategy_x_shape',
    'strategy_x_cooccur',
  ];
  const STRATEGY_X_SECONDARY = ['strategy_x_hyena'];
  const STRATEGY_X_DRAW_MIN = 262;

  let _sxRows = [];
  let _sxMeta = {};
  let _sxByTag = {};
  let _sxCurrentBrain = 'strategy_x_hyena';

  function rebuildSxDrawOptions() {
    const sx = document.getElementById('sxDrawSelect');
    if (!sx) return;
    const min = STRATEGY_X_DRAW_MIN;
    const max = Math.max(_nextDrawNo || 1229, 1228);
    const cur = parseInt(sx.value, 10) || null;
    sx.innerHTML = '';
    for (let i = min; i <= max; i++) {
      const opt = document.createElement('option');
      opt.value = String(i);
      opt.textContent = i + '회';
      sx.appendChild(opt);
    }
    const use =
      cur && cur >= min && cur <= max ? cur : Math.min(1228, max);
    sx.value = String(use);
    const di = document.getElementById('sxDrawDirectInput');
    if (di) di.value = String(use);
  }

  function syncSxDrawOptions() {
    rebuildSxDrawOptions();
  }

  function getSxDrawNo() {
    const sx = document.getElementById('sxDrawSelect');
    const v = parseInt(sx && sx.value, 10);
    if (v) return v;
    const di = document.getElementById('sxDrawDirectInput');
    const dv = parseInt(di && di.value, 10);
    return dv || null;
  }

  function setSxDrawNo(d) {
    const sx = document.getElementById('sxDrawSelect');
    const dn = parseInt(d, 10);
    if (!dn) return;
    if (sx) {
      let o = Array.from(sx.options).find((x) => parseInt(x.value, 10) === dn);
      if (!o) {
        o = document.createElement('option');
        o.value = String(dn);
        o.textContent = dn + '회';
        sx.appendChild(o);
      }
      sx.value = String(dn);
    }
    const di = document.getElementById('sxDrawDirectInput');
    if (di) di.value = String(dn);
  }

  function parseReasoningObj(row) {
    try {
      return JSON.parse(row.reasoning || '{}');
    } catch (_e) {
      return {};
    }
  }

  function strategyXScoreLabel(row) {
    const meta = parseReasoningObj(row);
    if (meta.cooccur_score != null) return 'cooccur ' + meta.cooccur_score;
    if (meta.popularity_score != null) return '인기 ' + meta.popularity_score;
    if (meta.combined_score != null) return '종합 ' + meta.combined_score;
    if (row.confidence != null && row.confidence !== '') {
      return '점수 ' + Number(row.confidence).toFixed(3);
    }
    return '';
  }

  function renderStrategyXSetRow(row, idx) {
    const nums = fmtNums(row)
      .slice()
      .sort((a, b) => a - b);
    const hit = actualSetFromRow(row);
    const bonus = row.actual_bonus != null ? row.actual_bonus : null;
    const matched = row.matched_count != null ? Number(row.matched_count) : null;
    const tLab = tierLabel(row.matched_count, row.bonus_matched);
    const scoreLab = strategyXScoreLabel(row);
    let border = '';
    if (matched != null && matched >= 3) border = ' set-hit-border';
    let html = '<div class="set-row' + border + '">';
    html += '<div class="set-row-head">';
    html += '<span class="set-label">#' + (idx + 1) + '</span>';
    if (scoreLab) html += '<span class="conf-badge">' + escapeHtml(scoreLab) + '</span>';
    if (tLab) html += '<span class="set-tier-label">' + tLab + '</span>';
    html += '</div><div class="set-row-meta">';
    if (matched != null && matched >= 0) {
      html += '<span class="conf-badge conf-matched">적중 ' + matched + '개</span>';
    } else if (matched != null && matched < 0) {
      html += '<span class="conf-badge conf-pending">채점 전</span>';
    }
    html += '</div>';
    html += renderBallsHtml(nums, hit, bonus);
    html += '</div>';
    return html;
  }

  function strategyXTierRank(row) {
    const m = row.matched_count != null ? Number(row.matched_count) : NaN;
    const bonus =
      row.bonus_matched === 1 ||
      row.bonus_matched === true ||
      (row.bonus_matched != null && Number(row.bonus_matched) === 1);
    if (!Number.isFinite(m) || m < 0) return 0;
    if (m === 6) return 1;
    if (m === 5 && bonus) return 2;
    if (m === 5) return 3;
    if (m === 4) return 4;
    if (m === 3) return 5;
    return 0;
  }

  function strategyXHitSummaryLine(rows) {
    const c = { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0 };
    (rows || []).forEach((r) => {
      const tr = strategyXTierRank(r);
      if (tr) c[tr] += 1;
    });
    return (
      ' · 전적 1등 ' +
      c[1] +
      ' | 2등 ' +
      c[2] +
      ' | 3등 ' +
      c[3] +
      ' | 4등 ' +
      c[4] +
      ' | 5등 ' +
      c[5]
    );
  }

  function makeSxTabBtn(tag) {
    const bm = _sxMeta[tag] || {};
    const b = document.createElement('button');
    b.type = 'button';
    b.className =
      'tab-btn' +
      (tag === 'strategy_x_hyena' ? ' tab-btn--hyena' : '') +
      (_sxCurrentBrain === tag ? ' active' : '');
    b.setAttribute('data-sx-brain', tag);
    let label = escapeHtml(bm.label || tag);
    if (tag === 'strategy_x_hyena') {
      label += ' <span class="rank-badge">최종</span>';
    }
    b.innerHTML = label;
    b.addEventListener('click', () => lotto4SwitchStrategyXBrain(tag));
    return b;
  }

  function buildStrategyXTabs(order) {
    const tp = document.getElementById('sxTabsPrimary');
    const ts = document.getElementById('sxTabsSecondary');
    if (!tp || !ts) return;
    tp.innerHTML = '';
    ts.innerHTML = '';
    const ord = order || STRATEGY_X_BRAIN_ORDER;
    const primary = STRATEGY_X_PRIMARY.filter((t) => ord.includes(t));
    const secondary = STRATEGY_X_SECONDARY.filter((t) => ord.includes(t));
    primary.forEach((tag) => tp.appendChild(makeSxTabBtn(tag)));
    secondary.forEach((tag) => ts.appendChild(makeSxTabBtn(tag)));
    highlightStrategyXTab();
  }

  function highlightStrategyXTab() {
    document.querySelectorAll('.tab-btn[data-sx-brain]').forEach((btn) => {
      const tag = btn.getAttribute('data-sx-brain');
      btn.classList.toggle('active', tag === _sxCurrentBrain);
    });
  }

  function lotto4SwitchStrategyXBrain(tag) {
    if (!STRATEGY_X_BRAIN_ORDER.includes(tag)) return;
    _sxCurrentBrain = tag;
    highlightStrategyXTab();
    renderStrategyXSetsForBrain();
  }

  function renderStrategyXSetsForBrain() {
    const host = document.getElementById('strategyXSetsHost');
    const title = document.getElementById('strategyXActiveTitle');
    const discHost = document.getElementById('strategyXDisclaimer');
    if (!host) return;

    const list = _sxByTag[_sxCurrentBrain] || [];
    const bm = _sxMeta[_sxCurrentBrain] || {};

    if (title) {
      title.textContent =
        (bm.label || _sxCurrentBrain) + ' · 예측 세트' + strategyXHitSummaryLine(list);
    }

    if (discHost) {
      const disc =
        bm.disclaimer ||
        '인기영역 조합기입니다. 미래를 예측하지 않으며 당첨 확률은 모든 조합이 동일합니다.';
      discHost.textContent = disc ? '안내: ' + disc : '';
    }

    if (!_sxRows.length) {
      host.innerHTML =
        '<div class="empty-notice">이 회차 저장 기록이 없습니다. 「전략 X 생성」을 누르거나 era_C 백테스트 적재 회차를 선택하세요.</div>';
      if (title) title.textContent = '';
      if (discHost) discHost.innerHTML = '';
      return;
    }

    const drawnSample =
      list.find((r) => actualSetFromRow(r)) || _sxRows.find((r) => actualSetFromRow(r));
    let html = drawnSample ? renderActualDrawBanner(drawnSample) : renderUndrawnBanner();
    if (!list.length) {
      html += '<div class="status-line">이 뇌 세트 없음</div>';
    } else {
      list.forEach((r, i) => {
        html += renderStrategyXSetRow(r, i);
      });
    }
    host.innerHTML = html;
  }

  function renderStrategyXSets(data) {
    const order = data.brain_order || STRATEGY_X_BRAIN_ORDER;
    _sxRows = data.predictions || [];
    _sxMeta = data.brain_meta || {};
    _sxByTag = {};
    _sxRows.forEach((r) => {
      const tag = r.brain_tag || '';
      if (!_sxByTag[tag]) _sxByTag[tag] = [];
      _sxByTag[tag].push(r);
    });

    if (!order.includes(_sxCurrentBrain)) {
      _sxCurrentBrain = 'strategy_x_hyena';
    }

    if (!_sxRows.length) {
      const tp = document.getElementById('sxTabsPrimary');
      const ts = document.getElementById('sxTabsSecondary');
      if (tp) tp.innerHTML = '';
      if (ts) ts.innerHTML = '';
      renderStrategyXSetsForBrain();
      return;
    }

    buildStrategyXTabs(order);
    lotto4SwitchStrategyXBrain(_sxCurrentBrain);
  }

  async function generateStrategyX(drawNo) {
    const d = drawNo || getSxDrawNo();
    await fetchJsonHandled(API + '/strategy_x/recommend/' + d, { method: 'POST' });
    await fetchJsonHandled(API + '/strategy_x/cooccur/' + d, { method: 'POST' });
    await fetchJsonHandled(API + '/strategy_x/hyena/' + d, { method: 'POST' });
  }

  async function loadStrategyX(drawNo, options) {
    const st = document.getElementById('strategyXStatus');
    const d = drawNo || getSxDrawNo();
    if (!d) {
      setStatus(st, '회차를 선택하세요.', false);
      return;
    }
    setSxDrawNo(d);
    setStatus(st, d + '회 불러오는 중…', true);
    try {
      if (options && options.generate) {
        setStatus(st, d + '회 생성 중… (recommend·cooccur·hyena)', true);
        await generateStrategyX(d);
      }
      const data = await fetchJsonHandled(API + '/strategy_x/predictions/draw/' + d);
      renderStrategyXSets(data);
      const n = (data.predictions || []).length;
      setStatus(st, d + '회 · strategy_x ' + n + '행 표시', true);
    } catch (e) {
      const host = document.getElementById('strategyXSetsHost');
      const tp = document.getElementById('sxTabsPrimary');
      const ts = document.getElementById('sxTabsSecondary');
      if (host) host.innerHTML = '';
      if (tp) tp.innerHTML = '';
      if (ts) ts.innerHTML = '';
      setStatus(st, '오류: ' + (e.message || e), false);
    }
  }

  function sxBrainLabel(tag) {
    const bm = _sxMeta[tag] || {};
    return bm.label || tag;
  }

  function renderSxTierModalFromRows(d, rows) {
    const tierNoEl = document.getElementById('tierDrawNo');
    const jump = document.getElementById('tierJumpInput');
    const actualEl = document.getElementById('tierActualNumbers');
    const sectionsEl = document.getElementById('tierSections');
    if (!sectionsEl) return;
    _tierModalDraw = d;
    if (tierNoEl) tierNoEl.textContent = String(d);
    if (jump) jump.value = String(d);

    const sample = rows.find((r) => actualSetFromRow(r));
    let nums = [];
    let bonusNum = null;
    if (sample) {
      for (let k = 1; k <= 6; k++) {
        const key = 'actual_' + k;
        if (sample[key] != null && sample[key] !== '') nums.push(Number(sample[key]));
      }
      nums.sort((a, b) => a - b);
      bonusNum = sample.actual_bonus != null ? Number(sample.actual_bonus) : null;
    }
    const winSet = nums.length === 6 ? new Set(nums) : null;

    if (actualEl) {
      if (nums.length === 6) {
        let h = '<div class="tier-actual-inner">';
        h += '<span class="tier-actual-label">실제 당첨번호</span>';
        h += renderBallsHtml(nums, null, null);
        if (bonusNum != null && !Number.isNaN(bonusNum)) {
          h +=
            '<span class="tier-bonus-line"><span class="strip-bonus-label">보너스</span>' +
            renderBonusBall(bonusNum) +
            '</span>';
        }
        h += '</div>';
        actualEl.innerHTML = h;
      } else {
        actualEl.innerHTML =
          '<p class="tier-no-draw">이 회차는 아직 당첨번호가 없거나 미수집입니다.</p>';
      }
    }

    const byRank = { 1: [], 2: [], 3: [], 4: [], 5: [] };
    (rows || []).forEach((r) => {
      const rk = strategyXTierRank(r);
      if (rk) byRank[rk].push(r);
    });

    let html = '';
    const titles = { 1: '1등', 2: '2등', 3: '3등', 4: '4등', 5: '5등' };
    for (let r = 1; r <= 5; r++) {
      const list = byRank[r];
      html += '<section class="tier-section"><h4 class="tier-section-title t' + r + '">' + titles[r] + '</h4>';
      if (!list.length) {
        html += '<p class="tier-empty-rank">해당 등수 적중 없음</p>';
      } else {
        list.forEach((it) => {
          const brainSets = _sxByTag[it.brain_tag] || [];
          const setIdx = Math.max(1, brainSets.indexOf(it) + 1);
          const label = sxBrainLabel(it.brain_tag) + ' #' + setIdx;
          const setNums = fmtNums(it)
            .slice()
            .sort((a, b) => a - b);
          html += '<div class="tier-set">';
          html += '<div class="tier-set-meta">' + escapeHtml(label) + '</div>';
          html += renderBallsHtml(setNums, winSet, bonusNum);
          html += '</div>';
        });
      }
      html += '</section>';
    }
    if (!rows.some((r) => strategyXTierRank(r))) {
      html =
        '<p class="tier-global-empty">이 회차에 1~5등 적중 세트가 없습니다. 미추첨·미채점이거나 해당 회차 기록이 없을 수 있습니다.</p>' +
        html;
    }
    sectionsEl.innerHTML = html;
  }

  async function openSxTierModal() {
    const d = getSxDrawNo();
    const modal = document.getElementById('modalTier');
    const sectionsEl = document.getElementById('tierSections');
    const st = document.getElementById('strategyXStatus');
    if (!d || !modal) return;
    _tierModalMode = 'strategy-x';
    modal.classList.remove('hidden');
    if (sectionsEl) sectionsEl.innerHTML = '<p class="tier-loading">불러오는 중…</p>';
    try {
      if (!_sxRows.length) await loadStrategyX(d, { generate: false });
      renderSxTierModalFromRows(d, _sxRows);
    } catch (e) {
      if (sectionsEl) sectionsEl.innerHTML = '<p class="error">오류: ' + (e.message || e) + '</p>';
      setStatus(st, '적중 모달 오류: ' + (e.message || e), false);
    }
  }

  function buildSxKakaoText(drawDateLine, d) {
    const lines = [];
    lines.push('🎰 [4군 전략 X] 제' + d + '회');
    lines.push('📅 ' + drawDateLine);
    lines.push('━━━━━━━━━━━━━━');
    const circled = ['①', '②', '③', '④', '⑤'];
    STRATEGY_X_BRAIN_ORDER.forEach((tag) => {
      const list = _sxByTag[tag] || [];
      if (!list.length) return;
      const label = sxBrainLabel(tag);
      const hits = strategyXHitSummaryLine(list).replace(' · 전적 ', '');
      lines.push('');
      lines.push('🧠 ' + label + ' (' + hits + ')');
      list.forEach((r, i) => {
        const nums = fmtNums(r)
          .map((x) => String(x).padStart(2, '0'))
          .join(' ');
        const score = strategyXScoreLabel(r);
        const suff = score ? ' (' + score + ')' : '';
        const emoji = circled[i] || String(i + 1) + ')';
        lines.push('  ' + emoji + ' ' + nums + suff);
      });
    });
    lines.push('');
    lines.push('━━━━━━━━━━━━━━');
    lines.push('🦴 전략 X — 인기영역 조합 (예측 아님)');
    return lines.join('\n');
  }

  async function copySxKakao() {
    const st = document.getElementById('strategyXStatus');
    const d = getSxDrawNo();
    if (!d) {
      setStatus(st, '회차를 선택하세요.', false);
      return;
    }
    if (!_sxRows.length) {
      setStatus(st, '먼저 전략 X 기록을 불러오세요.', false);
      return;
    }
    let dateLine = '미수집/미추첨';
    try {
      const dj = await fetchJsonHandled(API + '/draws?draw_no=' + d);
      const dr = dj.draws && dj.draws[0];
      if (dr && dr.draw_date) dateLine = dr.draw_date + ' 추첨';
      else dateLine = '미추첨 또는 당첨 DB 미수집';
    } catch (_e) {
      dateLine = '추첨일 조회 실패';
    }
    const text = buildSxKakaoText(dateLine, d);
    if (!text.trim()) {
      setStatus(st, '복사할 예측이 없습니다.', false);
      return;
    }
    navigator.clipboard.writeText(text).then(
      () => setStatus(st, '카톡용 텍스트 복사됨', true),
      () => setStatus(st, '복사 실패(브라우저 권한)', false),
    );
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  /** 로또 조회 탭 — 814만 순위 · 당첨 이력 */
  let _comboPage = 1;
  let _comboLoaded = false;

  function fmtComboPrize(v) {
    const n = Number(v);
    if (!Number.isFinite(n) || n <= 0) return '—';
    return n.toLocaleString('ko-KR') + '원';
  }

  function initComboLookupInputs() {
    const host = document.getElementById('comboLookupInputs');
    if (!host || host.childElementCount >= 6) return;
    host.innerHTML = '';
    for (let i = 1; i <= 6; i++) {
      const inp = document.createElement('input');
      inp.type = 'number';
      inp.min = '1';
      inp.max = '45';
      inp.className = 'combo-num-inp';
      inp.id = 'comboLookupN' + i;
      inp.placeholder = String(i);
      inp.setAttribute('aria-label', '번호 ' + i);
      host.appendChild(inp);
    }
  }

  function readComboLookupNums() {
    const nums = [];
    for (let i = 1; i <= 6; i++) {
      const el = document.getElementById('comboLookupN' + i);
      const raw = el && el.value ? el.value.trim() : '';
      if (raw === '') return { error: '6개 번호를 모두 입력하세요.' };
      const n = Number(raw);
      if (!Number.isInteger(n) || n < 1 || n > 45) {
        return { error: '번호는 1~45 정수여야 합니다.' };
      }
      nums.push(n);
    }
    if (new Set(nums).size !== 6) return { error: '중복 번호는 허용되지 않습니다.' };
    return { nums };
  }

  function renderComboLookupResult(data, errMsg) {
    const el = document.getElementById('comboLookupResult');
    if (!el) return;
    if (errMsg) {
      el.innerHTML = '<p class="combo-lookup-err">' + escapeHtml(errMsg) + '</p>';
      return;
    }
    if (!data) {
      el.innerHTML = '';
      return;
    }
    let appearHtml = '';
    if (data.appeared && data.appearances && data.appearances.length) {
      const lines = data.appearances.map(
        (a) => escapeHtml(String(a.draw_no)) + '회 (' + escapeHtml(String(a.draw_date || '')) + ')',
      );
      appearHtml =
        '<p class="combo-appear-yes">역대 당첨 출현: ' +
        lines.join(', ') +
        '</p>';
    } else {
      appearHtml = '<p class="combo-appear-no">역대 1등 당첨 이력 없음 (현재 DB 기준)</p>';
    }
    el.innerHTML =
      '<div class="combo-lookup-card">' +
      renderBallsHtml(data.numbers) +
      '<p><strong>814만 중 순위:</strong> No.' +
      escapeHtml(String(data.combo_no).replace(/\B(?=(\d{3})+(?!\d))/g, ',')) +
      ' / ' +
      escapeHtml(String(data.combo_total).replace(/\B(?=(\d{3})+(?!\d))/g, ',')) +
      '</p>' +
      appearHtml +
      '</div>';
  }

  async function runComboNumberLookup() {
    const parsed = readComboLookupNums();
    if (parsed.error) {
      renderComboLookupResult(null, parsed.error);
      return;
    }
    const url =
      API +
      '/combo/lookup?' +
      parsed.nums.map((n, i) => 'n' + (i + 1) + '=' + encodeURIComponent(n)).join('&');
    try {
      const res = await fetch(url);
      const data = await res.json();
      if (!res.ok) {
        renderComboLookupResult(null, data.detail || '조회 실패');
        return;
      }
      renderComboLookupResult(data, null);
    } catch (e) {
      renderComboLookupResult(null, String(e));
    }
  }

  function renderComboTableRows(items) {
    const tbody = document.getElementById('comboDrawTbody');
    if (!tbody) return;
    if (!items || !items.length) {
      tbody.innerHTML = '<tr><td colspan="6">데이터 없음</td></tr>';
      return;
    }
    tbody.innerHTML = items
      .map((row) => {
        const rank = Number(row.combo_no);
        const rankStr = Number.isFinite(rank)
          ? rank.toLocaleString('ko-KR')
          : '—';
        const winners =
          row.first_winners != null && row.first_winners !== '' ? String(row.first_winners) + '명' : '—';
        return (
          '<tr>' +
          '<td>' +
          escapeHtml(String(row.draw_no)) +
          '회</td>' +
          '<td>' +
          escapeHtml(String(row.draw_date || '—')) +
          '</td>' +
          '<td>' +
          renderBallsHtml(row.numbers) +
          '</td>' +
          '<td class="combo-rank-cell">No.' +
          escapeHtml(rankStr) +
          '</td>' +
          '<td>' +
          escapeHtml(fmtComboPrize(row.first_prize)) +
          '</td>' +
          '<td>' +
          escapeHtml(String(winners)) +
          '</td>' +
          '</tr>'
        );
      })
      .join('');
  }

  function renderComboPagination(meta) {
    const host = document.getElementById('comboPagination');
    if (!host) return;
    const totalPages = Number(meta.total_pages) || 0;
    const page = Number(meta.page) || 1;
    if (totalPages <= 1) {
      host.innerHTML =
        totalPages === 0
          ? ''
          : '<span class="combo-page-info">전체 ' + escapeHtml(String(meta.total)) + '건</span>';
      return;
    }
    let html = '<span class="combo-page-info">' + page + ' / ' + totalPages + ' (총 ' + meta.total + '건)</span>';
    html += '<div class="combo-page-btns">';
    if (page > 1) {
      html +=
        '<button type="button" class="btn btn-secondary combo-page-btn" data-combo-page="' +
        (page - 1) +
        '">이전</button>';
    }
    if (page < totalPages) {
      html +=
        '<button type="button" class="btn btn-secondary combo-page-btn" data-combo-page="' +
        (page + 1) +
        '">다음</button>';
    }
    html += '</div>';
    host.innerHTML = html;
    host.querySelectorAll('.combo-page-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        const p = Number(btn.getAttribute('data-combo-page'));
        if (Number.isFinite(p)) loadComboDrawTable(p);
      });
    });
  }

  async function loadComboDrawTable(page) {
    const st = document.getElementById('comboTableStatus');
    const orderEl = document.getElementById('comboOrderSelect');
    const perEl = document.getElementById('comboPerPageSelect');
    const qEl = document.getElementById('comboSearchQ');
    const order = orderEl ? orderEl.value : 'draw_no_desc';
    const perPage = perEl ? perEl.value : '50';
    const q = qEl && qEl.value ? qEl.value.trim() : '';
    const p = page || _comboPage || 1;
    _comboPage = p;
    if (st) st.textContent = '불러오는 중…';
    const params = new URLSearchParams({
      page: String(p),
      per_page: String(perPage),
      order,
    });
    if (q) params.set('q', q);
    try {
      const res = await fetch(API + '/combo/all?' + params.toString());
      const data = await res.json();
      if (!res.ok) {
        if (st) st.textContent = '로드 실패';
        return;
      }
      renderComboTableRows(data.items);
      renderComboPagination(data);
      if (st) {
        st.textContent =
          '최신 회차 ' +
          (data.items && data.items[0] ? data.items[0].draw_no + '회' : '—') +
          ' · DB 전체 ' +
          data.total +
          '건';
      }
      _comboLoaded = true;
    } catch (e) {
      if (st) st.textContent = '오류: ' + e;
    }
  }

  function loadComboLookupView() {
    initComboLookupInputs();
    loadComboDrawTable(_comboPage || 1);
  }

  /** 전체 조합 탭 — 20분할 DB · 페이지네이션 */
  const AC_TOTAL = 8145060;
  let _acMeta = { ready: false, combo_total: AC_TOTAL, winners: 0 };
  let _acPage = 1;
  let _acWinnersOnly = false;
  let _acHighlightNo = null;
  let _acLastItems = [];

  function acGetPerPage() {
    const el = document.getElementById('acPerPageSelect');
    return el ? Number(el.value) || 120 : 120;
  }

  function initAcSearchInputs() {
    const host = document.getElementById('acSearchInputs');
    if (!host || host.childElementCount >= 6) return;
    host.innerHTML = '';
    for (let i = 1; i <= 6; i++) {
      const inp = document.createElement('input');
      inp.type = 'number';
      inp.min = '1';
      inp.max = '45';
      inp.className = 'combo-num-inp';
      inp.id = 'acSearchN' + i;
      inp.placeholder = String(i);
      host.appendChild(inp);
    }
  }

  function acFmtRank(n) {
    const v = Number(n);
    return Number.isFinite(v) ? v.toLocaleString('ko-KR') : '—';
  }

  function acParseComboNoInput(raw) {
    const s = String(raw || '').trim().replace(/,/g, '');
    if (!/^\d+$/.test(s)) return NaN;
    const n = parseInt(s, 10);
    return Number.isFinite(n) ? n : NaN;
  }

  function acUpdateSummary() {
    const el = document.getElementById('acSummary');
    if (!el) return;
    const total = Number(_acMeta.combo_total) || AC_TOTAL;
    const winners = Number(_acMeta.winners) || 0;
    el.innerHTML =
      '<strong>전체 ' +
      acFmtRank(total) +
      '개 조합</strong> (순위 No.1 ~ No.' +
      acFmtRank(total) +
      ')' +
      (winners ? ' · 역대 당첨 <strong>' + acFmtRank(winners) + '건</strong>' : '') +
      '<span class="allcombos-summary-hint">순위 번호(예: 3826391) 또는 6번호로 바로 찾을 수 있습니다.</span>';
  }

  async function acGoToComboResult(data, st) {
    if (!data || data.error) {
      if (st) st.textContent = data?.detail || data?.error || '찾을 수 없습니다';
      return;
    }
    const jmp = document.getElementById('acJumpInput');
    const quick = document.getElementById('acQuickSearch');
    if (jmp) jmp.value = acFmtRank(data.combo_no).replace(/,/g, '');
    if (quick && data.combo_no) quick.value = String(data.combo_no);
    _acHighlightNo = data.combo_no;
    if (_acWinnersOnly) {
      if (data.item && !data.item.is_winner) {
        if (st) {
          st.textContent =
            'No.' +
            acFmtRank(data.combo_no) +
            ' — 당첨 조합이 아닙니다 (당첨만 보기 해제 후 전체 목록에서 확인)';
        }
        return;
      }
      if (data.winner_page) {
        await loadAcPage(data.winner_page);
        return;
      }
    }
    const page = data.page || acComboNoToPage(data.combo_no);
    await loadAcPage(page);
  }

  function acRenderRows(items) {
    const tbody = document.getElementById('acTbody');
    if (!tbody) return;
    _acLastItems = items || [];
    if (!items || !items.length) {
      tbody.innerHTML = '<tr><td colspan="4">데이터 없음</td></tr>';
      return;
    }
    tbody.innerHTML = items
      .map((row) => {
        const win = row.is_winner;
        const trCls = win ? 'allcombos-row-winner' : '';
        const hi =
          _acHighlightNo && Number(_acHighlightNo) === Number(row.combo_no)
            ? ' allcombos-row-highlight'
            : '';
        let winCell = '—';
        if (win && row.win_draw_no) {
          winCell =
            '<span class="allcombos-win-badge">' +
            escapeHtml(String(row.win_draw_no)) +
            '회 (' +
            escapeHtml(String(row.win_date || '')) +
            ')</span>';
        }
        return (
          '<tr class="' +
          trCls +
          hi +
          '" data-combo-no="' +
          escapeHtml(String(row.combo_no)) +
          '">' +
          '<td class="ac-col-rank">No.' +
          escapeHtml(acFmtRank(row.combo_no)) +
          '</td>' +
          '<td class="ac-col-nums">' +
          renderBallsHtml(row.numbers) +
          '</td>' +
          '<td class="ac-col-sum">' +
          escapeHtml(String(row.total)) +
          '</td>' +
          '<td class="ac-col-win">' +
          winCell +
          '</td>' +
          '</tr>'
        );
      })
      .join('');
  }

  function acRenderPagination(meta) {
    const host = document.getElementById('acPagination');
    if (!host) return;
    const totalPages = Number(meta.total_pages) || 0;
    const page = Number(meta.page) || 1;
    if (totalPages <= 1) {
      host.innerHTML =
        totalPages === 0
          ? ''
          : '<span class="combo-page-info">1 / 1 (총 ' + escapeHtml(String(meta.total)) + '건)</span>';
      return;
    }
    let html =
      '<span class="combo-page-info">' +
      page +
      ' / ' +
      totalPages +
      ' (총 ' +
      acFmtRank(meta.total) +
      '건)</span>';
    html += '<div class="combo-page-btns">';
    if (page > 1) {
      html +=
        '<button type="button" class="btn btn-secondary combo-page-btn" data-ac-page="' +
        (page - 1) +
        '">이전</button>';
    }
    if (page < totalPages) {
      html +=
        '<button type="button" class="btn btn-secondary combo-page-btn" data-ac-page="' +
        (page + 1) +
        '">다음</button>';
    }
    html += '</div>';
    host.innerHTML = html;
    host.querySelectorAll('.combo-page-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        const p = Number(btn.getAttribute('data-ac-page'));
        if (Number.isFinite(p)) loadAcPage(p);
      });
    });
  }

  async function loadAcPage(page) {
    const st = document.getElementById('acStatus');
    const perPage = acGetPerPage();
    const p = page || _acPage || 1;
    _acPage = p;
    if (st) st.textContent = '불러오는 중…';
    const params = new URLSearchParams({
      page: String(p),
      per_page: String(perPage),
    });
    if (_acWinnersOnly) params.set('winners_only', 'true');
    try {
      const res = await fetch(API + '/allcombos?' + params.toString());
      const data = await res.json();
      if (!res.ok || data.error) {
        if (st) st.textContent = data.message || data.error || '로드 실패';
        return;
      }
      acRenderRows(data.items);
      acRenderPagination(data);
      if (st) {
        const first = data.items && data.items[0] ? data.items[0].combo_no : '—';
        const last = data.items && data.items.length ? data.items[data.items.length - 1].combo_no : '—';
        const totalAll = Number(data.combo_total) || AC_TOTAL;
        if (_acWinnersOnly) {
          const dr = data.items && data.items[0] ? data.items[0].win_draw_no : '—';
          st.textContent =
            '당첨만 · 회차 최신순 · 페이지 ' +
            data.page +
            '/' +
            data.total_pages +
            ' (당첨 ' +
            acFmtRank(data.total) +
            '건 / 전체 ' +
            acFmtRank(totalAll) +
            '개) · 최신 ' +
            dr +
            '회 ~ No.' +
            acFmtRank(first);
        } else {
          st.textContent =
            '전체 ' +
            acFmtRank(totalAll) +
            '개 · 페이지 ' +
            data.page +
            '/' +
            data.total_pages +
            ' · No.' +
            acFmtRank(first) +
            '~' +
            acFmtRank(last);
        }
      }
    } catch (e) {
      if (st) st.textContent = '오류: ' + e;
    }
  }

  function acComboNoToPage(comboNo) {
    const per = acGetPerPage();
    return Math.max(1, Math.floor((Number(comboNo) - 1) / per) + 1);
  }

  async function acDoJump() {
    const inp = document.getElementById('acJumpInput');
    const n = acParseComboNoInput(inp && inp.value);
    const st = document.getElementById('acStatus');
    const perPage = acGetPerPage();
    if (!n || n < 1 || n > AC_TOTAL) {
      if (st) st.textContent = '1 ~ 8,145,060 순위를 입력하세요 (쉼표 없이 또는 3,826,391 형식)';
      return;
    }
    try {
      const res = await fetch(
        API + '/allcombos/jump?combo_no=' + encodeURIComponent(n) + '&per_page=' + perPage,
      );
      const data = await res.json();
      if (!res.ok || data.error) {
        if (st) st.textContent = data.detail || data.error || '해당 순위를 찾을 수 없습니다';
        return;
      }
      await acGoToComboResult(
        { combo_no: n, page: data.page, winner_page: data.winner_page, item: data.item },
        st,
      );
    } catch (e) {
      if (st) st.textContent = String(e);
    }
  }

  async function acDoQuickSearch() {
    const inp = document.getElementById('acQuickSearch');
    const raw = inp && inp.value ? inp.value.trim() : '';
    const st = document.getElementById('acStatus');
    const perPage = acGetPerPage();
    if (!raw) {
      if (st) st.textContent = '순위 번호 또는 6개 번호를 입력하세요';
      return;
    }
    const params = new URLSearchParams({ per_page: String(perPage), nums: raw });
    try {
      const res = await fetch(API + '/allcombos/search?' + params.toString());
      const data = await res.json();
      if (!res.ok) {
        if (st) st.textContent = data.detail || '검색 실패';
        return;
      }
      await acGoToComboResult(data, st);
    } catch (e) {
      if (st) st.textContent = String(e);
    }
  }

  async function acDoSearch() {
    const nums = [];
    for (let i = 1; i <= 6; i++) {
      const el = document.getElementById('acSearchN' + i);
      const raw = el && el.value ? el.value.trim() : '';
      if (!raw) {
        const st = document.getElementById('acStatus');
        if (st) st.textContent = '6개 번호를 모두 입력하세요';
        return;
      }
      nums.push(Number(raw));
    }
    const url =
      API +
      '/allcombos/search?' +
      nums.map((n, i) => 'n' + (i + 1) + '=' + encodeURIComponent(n)).join('&') +
      '&per_page=' +
      acGetPerPage();
    const st = document.getElementById('acStatus');
    try {
      const res = await fetch(url);
      const data = await res.json();
      if (!res.ok || data.error) {
        if (st) st.textContent = data.detail || data.error || '검색 실패';
        return;
      }
      await acGoToComboResult(data, st);
    } catch (e) {
      if (st) st.textContent = String(e);
    }
  }

  function acExportCsv() {
    const st = document.getElementById('acStatus');
    const items = _acLastItems;
    if (!items || !items.length) {
      if (st) st.textContent = '보낼 데이터 없음';
      return;
    }
    const lines = ['combo_no,num1,num2,num3,num4,num5,num6,total,is_winner,win_draw_no,win_date'];
    items.forEach((row) => {
      const ns = row.numbers || [];
      lines.push(
        [
          row.combo_no,
          ns[0],
          ns[1],
          ns[2],
          ns[3],
          ns[4],
          ns[5],
          row.total,
          row.is_winner ? 1 : 0,
          row.win_draw_no || '',
          row.win_date || '',
        ].join(','),
      );
    });
    const blob = new Blob(['\ufeff' + lines.join('\n')], { type: 'text/csv;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'allcombos_page' + _acPage + '.csv';
    a.click();
    URL.revokeObjectURL(a.href);
    if (st) st.textContent = 'CSV 저장 (' + items.length + '행)';
  }

  function acToggleWinnersOnly() {
    const cb = document.getElementById('acWinnersOnly');
    _acWinnersOnly = !!(cb && cb.checked);
    _acHighlightNo = null;
    _acPage = 1;
    loadAcPage(1);
  }

  async function loadAllCombosView() {
    initAcSearchInputs();
    const st = document.getElementById('acStatus');
    if (st) st.textContent = '메타 불러오는 중…';
    try {
      const res = await fetch(API + '/allcombos/meta');
      _acMeta = await res.json();
      if (!_acMeta.ready) {
        if (st) {
          st.textContent =
            '20분할 DB 미적재 — python tools/build_lotto_all_combos.py (현재 ' +
            (_acMeta.count || 0).toLocaleString('ko-KR') +
            '행)';
        }
        return;
      }
      _acPage = 1;
      _acHighlightNo = null;
      acUpdateSummary();
      await loadAcPage(1);
    } catch (e) {
      if (st) st.textContent = '오류: ' + e;
    }
  }

  /** DB 0~1 또는 이미 % 값 → 표시용 % 문자열 (3군 lotto3.js 동일 규칙) */
  function confidenceDisplayPct(row) {
    if (!row || row.confidence == null || row.confidence === '') return null;
    const v = Number(row.confidence);
    if (!Number.isFinite(v)) return null;
    let pct = v;
    if (v <= 1) pct = v * 100;
    return (Math.round(pct * 100) / 100).toFixed(1);
  }

  function tierLabel(matched, bonusRaw) {
    const m = matched != null ? Number(matched) : NaN;
    const bonus =
      bonusRaw === 1 ||
      bonusRaw === true ||
      (bonusRaw != null && Number(bonusRaw) === 1);
    if (!Number.isFinite(m)) return '';
    if (m < 0) return '채점 전';
    if (m === 6) return '🏆 1등';
    if (m === 5 && bonus) return '🥈 2등';
    if (m === 5) return '🥉 3등';
    if (m === 4) return '4등';
    if (m === 3) return '5등';
    return '미당첨';
  }

  function dzBadgeHtml(row) {
    if (!row) return '';
    if (row.dz_filter_passed === false) {
      return '<span class="dz-badge" title="Dead Zone 보정">DZ</span>';
    }
    if (Array.isArray(row.dz_flags) && row.dz_flags.length) {
      return '<span class="dz-badge" title="Dead Zone">DZ ' + row.dz_flags.join(',') + '</span>';
    }
    return '';
  }

  function updateEliteTabVisibility() {
    const eliteOnly = document.getElementById('chkEliteOnly');
    const on = !!(eliteOnly && eliteOnly.checked);
    if (on && _eliteTags.size === 0) {
      document.querySelectorAll('.tab-btn[data-brain]').forEach((btn) => {
        btn.classList.add('hidden-elite');
      });
      const title = document.getElementById('brainActiveTitle');
      if (title) title.textContent = '';
      const host = document.getElementById('setsHost');
      if (host) {
        host.innerHTML =
          '<div class="empty-notice elite-empty">📢 현재 고적중 기준을 충족하는 뇌가 없습니다. 체크를 해제하면 전체 뇌를 볼 수 있습니다.</div>';
      }
      return;
    }
    document.querySelectorAll('.tab-btn[data-brain]').forEach((btn) => {
      const tag = btn.getAttribute('data-brain');
      let show = true;
      if (on) {
        show = _eliteTags.has(tag);
      }
      btn.classList.toggle('hidden-elite', !show);
    });
    if (on && _eliteTags.size > 0) {
      const allowed = BRAIN_ORDER.filter((t) => _eliteTags.has(t));
      if (allowed.length && !allowed.includes(_currentBrain)) {
        _currentBrain = allowed[0];
      }
    }
  }

  async function refreshEliteTags() {
    try {
      const res = await fetch(API + '/brain/elite-tags');
      const data = await res.json();
      _eliteTags = new Set();
      (data.tags || []).forEach((t) => {
        const l = String(t).toLowerCase();
        _eliteTags.add(l);
        _eliteTags.add(canonicalBrainTag(l));
      });
    } catch {
      _eliteTags = new Set();
    }
    updateEliteTabVisibility();
    lotto4SwitchBrainTab(_currentBrain);
  }

  async function loadBrainMeta() {
    try {
      const [r1, r2] = await Promise.all([
        fetch(API + '/brain/ranks').then((r) => r.json()),
        fetch(API + '/brain/nano-summary').then((r) => r.json()),
      ]);
      _rankByTag = {};
      (r1.ranked || []).forEach((x) => {
        const raw = String(x.brain_tag).toLowerCase();
        const canon = canonicalBrainTag(raw);
        const rk = x.rank;
        _rankByTag[raw] = rk;
        if (_rankByTag[canon] == null) _rankByTag[canon] = rk;
      });
      _nanoByTag = {};
      (r2.brains || []).forEach((x) => {
        const raw = String(x.brain_tag).toLowerCase();
        const canon = canonicalBrainTag(raw);
        _nanoByTag[raw] = x;
        if (!_nanoByTag[canon]) _nanoByTag[canon] = x;
      });
    } catch {
      _rankByTag = {};
      _nanoByTag = {};
    }
    renderTabs();
    updateEliteTabVisibility();
    lotto4SwitchBrainTab(_currentBrain);
  }

  function renderTabs() {
    const tp = document.getElementById('tabsPrimary');
    const ts = document.getElementById('tabsSecondary');
    if (!tp || !ts) return;
    tp.innerHTML = '';
    ts.innerHTML = '';
    BRAIN_PRIMARY.forEach((tag) => {
      tp.appendChild(makeTabBtn(tag));
    });
    BRAIN_SECONDARY.forEach((tag) => {
      ts.appendChild(makeTabBtn(tag));
    });
    highlightActiveTab();
  }

  function makeTabBtn(tag) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'tab-btn' + (_currentBrain === tag ? ' active' : '');
    b.setAttribute('data-brain', tag);
    const label = BRAIN_LABEL_TAB[tag] || brainLabelForTag(tag);
    const rk = _rankByTag[tag];
    const qBadge = isQuarantineBrain(tag) ? ' <span class="rank-badge quarantine-badge">격리</span>' : '';
    b.innerHTML =
      label + qBadge + (rk ? ' <span class="rank-badge">#' + rk + '</span>' : '');
    if (rk) b.title = '대시보드 뇌 순위 #' + rk + ' (당첨 번호와 무관)';
    b.addEventListener('click', () => lotto4SwitchBrainTab(tag));
    return b;
  }

  function highlightActiveTab() {
    document.querySelectorAll('.tab-btn[data-brain]').forEach((btn) => {
      const tag = btn.getAttribute('data-brain');
      btn.classList.toggle('active', tag === _currentBrain);
    });
  }

  function nanoLine(tag) {
    const n = _nanoByTag[tag];
    if (!n) return '';
    return (
      ' · 전적 1등 ' +
      (n.r1 || 0) +
      ' | 2등 ' +
      (n.r2 || 0) +
      ' | 3등 ' +
      (n.r3 || 0) +
      ' | 4등 ' +
      (n.r4 || 0) +
      ' | 5등 ' +
      (n.r5 || 0)
    );
  }

  function lotto4SwitchBrainTab(tag) {
    const t = String(tag || '').toLowerCase();
    if (!BRAIN_ORDER.includes(t)) return;
    _currentBrain = t;
    highlightActiveTab();
    const title = document.getElementById('brainActiveTitle');
    if (title) {
      title.textContent = brainLabelForTag(_currentBrain) + ' · 예측 세트' + nanoLine(_currentBrain);
    }
    renderSetsForBrain();
  }
  window.lotto4SwitchBrainTab = lotto4SwitchBrainTab;

  function rowsForCurrentBrain() {
    return _lastRows.filter((r) => canonicalBrainTag(r.brain_tag) === _currentBrain);
  }

  function firstRowWithActual(rows) {
    for (let j = 0; j < rows.length; j++) {
      if (actualSetFromRow(rows[j])) return rows[j];
    }
    return null;
  }

  function renderActualDrawBanner(sample) {
    const nums = [];
    for (let k = 1; k <= 6; k++) {
      const key = 'actual_' + k;
      if (sample[key] == null || sample[key] === '') return '';
      nums.push(Number(sample[key]));
    }
    nums.sort((a, b) => a - b);
    const bonus = sample.actual_bonus != null && sample.actual_bonus !== '' ? Number(sample.actual_bonus) : null;
    let html = '<div class="predict-context-strip" role="region" aria-label="당첨번호">';
    html += '<div class="predict-context-strip-inner">';
    html += '<span class="strip-title">이 회차 당첨번호 (확정)</span>';
    html += renderBallsHtml(nums, null, null);
    if (bonus != null) {
      html +=
        '<span class="strip-bonus-wrap"><span class="strip-bonus-label">보너스</span>' +
        renderBonusBall(bonus) +
        '</span>';
    }
    html += '</div>';
    html +=
      '<div class="strip-note">아래 숫자는 이 뇌가 제시한 예측입니다. 금색 테두리는 적중 3개 이상 세트입니다.</div>';
    html += '</div>';
    return html;
  }

  function renderUndrawnBanner() {
    return (
      '<div class="predict-context-strip predict-context-undrawn" role="status">' +
      '<div class="predict-context-strip-inner">' +
      '<span class="strip-title">미추첨 회차</span>' +
      '<span class="strip-note strip-note-inline">아래는 예측 번호입니다. 추첨 후 당첨 번호가 상단에 표시됩니다.</span>' +
      '</div></div>'
    );
  }

  function isQuarantineBrain(tag) {
    return QUARANTINED_BRAINS.has(canonicalBrainTag(tag));
  }

  function rowsAreQuarantinePlaceholder(rows) {
    if (!rows.length) return false;
    return rows.every((r) => String(r.reasoning || '').includes('격리'));
  }

  function allRowsSameNums(rows) {
    if (rows.length < 2) return true;
    const key = (r) =>
      fmtNums(r)
        .slice()
        .sort((a, b) => a - b)
        .join(',');
    const k0 = key(rows[0]);
    return rows.every((r) => key(r) === k0);
  }

  function renderQuarantineNotice(rows) {
    const same = allRowsSameNums(rows);
    let html =
      '<div class="predict-context-strip predict-context-quarantine" role="status">' +
      '<div class="predict-context-strip-inner">' +
      '<span class="strip-title">시퀀스 뇌 격리 중 (실예측 없음)</span>' +
      '<span class="strip-note strip-note-inline">' +
      'walk-forward 위반 의심으로 LSTM 시퀀스 예측이 중단되었습니다. ' +
      '표시 번호는 모두 무효 placeholder이며 앙상블·합의·가중치에 포함되지 않습니다.' +
      (same
        ? ' (구버전 DB: 7의 배수 등 동일 더미 — 「두뇌 예측 실행」 시 회차별 5세트 더미로 갱신됩니다.)'
        : '') +
      '</span></div></div>';
    rows.forEach((r, i) => {
      const nums = fmtNums(r)
        .slice()
        .sort((a, b) => a - b);
      html +=
        '<div class="quarantine-placeholder-row">' +
        '<span class="quarantine-ph-label">무효 placeholder #' +
        (i + 1) +
        '</span>' +
        renderBallsHtml(nums, null, null) +
        '</div>';
    });
    return html;
  }

  function renderSetsForBrain() {
    const host = document.getElementById('setsHost');
    if (!host) return;
    const eliteOnly = document.getElementById('chkEliteOnly');
    if (eliteOnly && eliteOnly.checked && _eliteTags.size === 0) {
      host.innerHTML =
        '<div class="empty-notice elite-empty">📢 현재 고적중 기준을 충족하는 뇌가 없습니다. 체크를 해제하면 전체 뇌를 볼 수 있습니다.</div>';
      return;
    }
    const list = rowsForCurrentBrain();
    if (!_lastRows.length) {
      host.innerHTML = '<div class="status-line">예측을 실행하거나 저장분을 불러오세요.</div>';
      return;
    }
    if (!list.length) {
      host.innerHTML = '<div class="status-line">이 뇌에 대한 데이터가 없습니다.</div>';
      return;
    }
    const drawnSample = firstRowWithActual(list);
    let banner = '';
    if (drawnSample) banner = renderActualDrawBanner(drawnSample);
    else banner = renderUndrawnBanner();

    if (isQuarantineBrain(_currentBrain) && rowsAreQuarantinePlaceholder(list)) {
      host.innerHTML = banner + renderQuarantineNotice(list);
      return;
    }

    let html = banner;
    list.forEach((r, i) => {
      const nums = fmtNums(r)
        .slice()
        .sort((a, b) => a - b);
      const hit = actualSetFromRow(r);
      const bonus = r.actual_bonus != null ? r.actual_bonus : null;
      const confStr = confidenceDisplayPct(r);
      const matched = r.matched_count != null ? Number(r.matched_count) : null;
      const tLab = tierLabel(r.matched_count, r.bonus_matched);
      let border = '';
      if (matched != null && matched >= 3) border = ' set-hit-border';
      html += '<div class="set-row' + border + '">';
      html += '<div class="set-row-head">';
      html += '<span class="set-label">#' + (i + 1) + '</span>';
      html += '<span class="set-row-predict-label">예측</span>';
      if (tLab) html += '<span class="set-tier-label">' + tLab + '</span>';
      html += dzBadgeHtml(r);
      html += '</div><div class="set-row-meta">';
      if (confStr != null) html += '<span class="conf-badge">신뢰 ' + confStr + '%</span>';
      if (matched != null && matched >= 0) {
        html += '<span class="conf-badge conf-matched">적중 ' + matched + '개</span>';
      } else if (matched != null && matched < 0) {
        html += '<span class="conf-badge conf-pending">채점 전</span>';
      }
      html += '</div>';
      html += renderBallsHtml(nums, hit, bonus);
      html += '</div>';
    });
    host.innerHTML = html;
  }

  function stopCountdown() {
    if (_countdownTimer) {
      clearInterval(_countdownTimer);
      _countdownTimer = null;
    }
  }

  /** KST 기준 wall components */
  function _kstCalendar(ms) {
    const d = new Date(ms);
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: 'Asia/Seoul',
      year: 'numeric',
      month: 'numeric',
      day: 'numeric',
      weekday: 'short',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    }).formatToParts(d);
    const m = {};
    parts.forEach(function (p) {
      if (p.type !== 'literal') m[p.type] = p.value;
    });
    return {
      y: parseInt(m.year, 10),
      mo: parseInt(m.month, 10),
      da: parseInt(m.day, 10),
      wd: m.weekday,
    };
  }

  function _kstYmdToUtcMs(y, mo, da, h, mi, se) {
    return Date.UTC(y, mo - 1, da, h - 9, mi, se);
  }

  /** 다음 토요일 20:45 KST 시각의 UTC ms */
  function nextSat2045KstUtcMs(nowMs) {
    const k = _kstCalendar(nowMs);
    for (let add = 0; add < 28; add++) {
      const utcDraw = _kstYmdToUtcMs(k.y, k.mo, k.da + add, 20, 45, 0);
      const wd = new Intl.DateTimeFormat('en-US', {
        timeZone: 'Asia/Seoul',
        weekday: 'short',
      }).format(new Date(utcDraw));
      if (wd === 'Sat' && utcDraw > nowMs) return utcDraw;
    }
    return nowMs + 7 * 86400000;
  }

  function renderCountdown(nextDrawNo) {
    const noEl = document.getElementById('countdownNextDraw');
    const timerEl = document.getElementById('countdownTimer');
    if (noEl) noEl.textContent = nextDrawNo != null ? String(nextDrawNo) + '회' : '-';
    if (!timerEl) return;
    const tick = function () {
      const t = nextSat2045KstUtcMs(Date.now());
      let diff = Math.max(0, t - Date.now());
      const sec = Math.floor(diff / 1000);
      const DD = Math.floor(sec / 86400);
      const HH = Math.floor((sec % 86400) / 3600);
      const MM = Math.floor((sec % 3600) / 60);
      const SS = sec % 60;
      timerEl.textContent =
        DD + '일 ' + String(HH).padStart(2, '0') + '시간 ' + String(MM).padStart(2, '0') + '분 ' + String(SS).padStart(2, '0') + '초';
    };
    stopCountdown();
    tick();
    _countdownTimer = setInterval(tick, 1000);
  }

  function renderOddEvenChart(oddEven) {
    const host = document.getElementById('chartOddEven');
    if (!host) return;
    if (!oddEven || typeof oddEven !== 'object') {
      host.innerHTML = '<div class="status-line">데이터 없음</div>';
      return;
    }
    const rows = Object.keys(oddEven).map(function (k) {
      return { label: k, c: oddEven[k] };
    });
    rows.sort(function (a, b) {
      return b.c - a.c;
    });
    const maxC = Math.max(1, ...rows.map(function (x) {
      return x.c;
    }));
    let html = '<div class="chart-block-title">홀짝 비율 (6개당첨 전체)</div>';
    rows.forEach(function (x) {
      const pct = Math.round((x.c / maxC) * 100);
      html +=
        '<div class="freq-row chart-bar-row"><span class="n chart-bar-label">' +
        x.label +
        '</span><div class="bar"><i style="width:' +
        pct +
        '%"></i></div><span class="freq-count">' +
        x.c +
        '</span></div>';
    });
    host.innerHTML = html;
  }

  function renderRangeChart(ranges) {
    const host = document.getElementById('chartRange');
    if (!host) return;
    if (!ranges || typeof ranges !== 'object') {
      host.innerHTML = '<div class="status-line">데이터 없음</div>';
      return;
    }
    const order = ['1-10', '11-20', '21-30', '31-40', '41-45'];
    const rows = order.map(function (k) {
      return { label: k, c: ranges[k] != null ? ranges[k] : 0 };
    });
    const maxC = Math.max(1, ...rows.map(function (x) {
      return x.c;
    }));
    let html = '<div class="chart-block-title">번호대별 분포 (볼 45개 누적)</div>';
    rows.forEach(function (x) {
      const pct = Math.round((x.c / maxC) * 100);
      html +=
        '<div class="freq-row chart-bar-row"><span class="n chart-bar-label">' +
        x.label +
        '</span><div class="bar"><i style="width:' +
        pct +
        '%"></i></div><span class="freq-count">' +
        x.c +
        '</span></div>';
    });
    host.innerHTML = html;
  }

  function renderSumChart(sumRange) {
    const host = document.getElementById('chartSum');
    if (!host) return;
    const dataArr = sumRange && Array.isArray(sumRange.data) ? sumRange.data : [];
    if (!dataArr.length) {
      host.innerHTML = '<div class="status-line">데이터 없음</div>';
      return;
    }
    const sums = dataArr.map(function (x) {
      return x.sum;
    });
    const lo = Math.min.apply(null, sums);
    const hi = Math.max.apply(null, sums);
    const binW = 10;
    const bins = {};
    for (let s = Math.floor(lo / binW) * binW; s <= hi + binW; s += binW) {
      bins[s + '–' + (s + binW - 1)] = 0;
    }
    sums.forEach(function (s) {
      const b = Math.floor(s / binW) * binW;
      const key = b + '–' + (b + binW - 1);
      if (bins[key] != null) bins[key]++;
      else bins[key] = 1;
    });
    const rowKeys = Object.keys(bins).sort(function (a, b) {
 return parseInt(a, 10) - parseInt(b, 10); 
});
    const maxC = Math.max(1, ...rowKeys.map(function (k) {
      return bins[k];
    }));
    let html =
      '<div class="chart-block-title">6개 번호 합계 분포 (구간 ' +
      binW +
      ', ' +
      (sumRange.average != null ? '평균 ' + sumRange.average : '') +
      ')</div>';
    rowKeys.forEach(function (k) {
      const c = bins[k];
      const pct = Math.round((c / maxC) * 100);
      html +=
        '<div class="freq-row chart-bar-row"><span class="n chart-bar-label">' +
        k +
        '</span><div class="bar"><i style="width:' +
        pct +
        '%"></i></div><span class="freq-count">' +
        c +
        '</span></div>';
    });
    host.innerHTML = html;
  }

  function renderPairChart(items) {
    const host = document.getElementById('chartPair');
    if (!host) return;
    if (!items || !items.length) {
      host.innerHTML =
        '<div class="status-line">데이터 없음 — python tools/collect_cooccur.py 실행</div>';
      return;
    }
    const maxC = Math.max(1, ...items.map(function (x) {
      return x.count;
    }));
    let html = '<div class="chart-block-title">동반출현 상위 (3-조합, cooccur-3)</div>';
    items.slice(0, 20).forEach(function (row, idx) {
      const nums = [row.num1, row.num2, row.num3];
      const balls = renderBallsHtml(nums, null, null);
      const pct = Math.round((row.count / maxC) * 100);
      html +=
        '<div class="pair-chart-row"><span class="pair-chart-rank">' +
        (idx + 1) +
        '</span><div class="pair-chart-balls">' +
        balls +
        '</div><div class="bar pair-chart-bar"><i style="width:' +
        pct +
        '%"></i></div><span class="freq-count">' +
        row.count +
        '</span></div>';
    });
    host.innerHTML = html;
  }

  function toggleDashRankDropdown() {
    const body = document.getElementById('dashRankWeightsBody');
    const btn = document.getElementById('btnDashRankToggle');
    if (!body) return;
    const open = body.classList.toggle('rank-dropdown-open');
    if (btn) btn.setAttribute('aria-expanded', open ? 'true' : 'false');
  }

  async function loadDashRankWeights() {
    const body = document.getElementById('dashRankWeightsBody');
    if (!body) return;
    body.innerHTML = '<div class="status-line">불러오는 중…</div>';
    try {
      const res = await fetch(API + '/brain/ranks');
      const data = await res.json();
      const items = data.ranked || [];
      if (!items.length) {
        body.innerHTML = '<div class="status-line">가중치 데이터 없음</div>';
        return;
      }
      let html = '<ol class="rank-weight-list">';
      items.forEach(function (it) {
        const dispTag = canonicalBrainTag(it.brain_tag);
        const lab = brainLabelForTag(it.brain_tag);
        html +=
          '<li><span class="rw-rank">#' +
          it.rank +
          '</span> <code title="' +
          dispTag +
          '">' +
          dispTag +
          '</code> <span class="rw-w-label">' +
          lab +
          '</span> <span class="rw-w">' +
          (it.current_weight != null ? it.current_weight : '-') +
          '</span></li>';
      });
      html += '</ol>';
      body.innerHTML = html;
    } catch (e) {
      body.innerHTML = '<div class="status-line error">' + (e.message || e) + '</div>';
    }
  }

  async function loadDashboard() {
    const body = document.getElementById('dashboardBody');
    const scoresEl = document.getElementById('dashboardScores');
    const tbody = document.querySelector('#brainPowerTable tbody');
    try {
      const res = await fetch(API + '/dashboard-summary');
      const data = await res.json();
      _nextDrawNo = Number(data.next_draw_no) || 1;
      const lr = data.learning_range || {};
      const predMin = Math.max(1, Number(lr.start) || 1);
      rebuildDrawOptions(_nextDrawNo, predMin);
      syncSxDrawOptions();
      renderCountdown(_nextDrawNo);
      loadDashRankWeights();

      if (body) {
        const lr = data.learning_range || {};
        const rk = data.rankings || {};
        body.innerHTML =
          '<div class="dash-tile"><div class="k">다음 회차</div><div class="v">' +
          (data.next_draw_no || '-') +
          '</div><div style="font-size:0.78rem;color:var(--muted);margin-top:6px">' +
          (data.next_draw_date || '') +
          ' (' +
          (data.next_draw_weekday || '') +
          ')</div></div>' +
          '<div class="dash-tile"><div class="k">학습 구간</div><div class="v">' +
          (lr.start || '-') +
          '–' +
          (lr.end || '-') +
          '</div><div style="font-size:0.78rem;color:var(--muted);margin-top:6px">총 ' +
          (lr.total_draws || 0) +
          '회차 데이터</div></div>' +
          '<div class="dash-tile"><div class="k">예측 총 건수</div><div class="v">' +
          (data.total_predictions || 0) +
          '</div></div>' +
          '<div class="dash-tile"><div class="k">1·2·3등 (건)</div><div class="v">' +
          (rk.rank1_total || 0) +
          ' / ' +
          (rk.rank2_total || 0) +
          ' / ' +
          (rk.rank3_total || 0) +
          '</div></div>';
      }
      if (scoresEl && data.scores) {
        const s = data.scores;
        scoresEl.innerHTML =
          '<strong>전체 적중 비율</strong> · 1등 ' +
          s.rank1_pct +
          '% · 2등 ' +
          s.rank2_pct +
          '% · 3등 ' +
          s.rank3_pct +
          '% · 4등 ' +
          s.rank4_pct +
          '% · 5등 ' +
          s.rank5_pct +
          '% · 합계 ' +
          s.total_hit_pct +
          '%';
      }
      if (tbody && Array.isArray(data.brain_power)) {
        tbody.innerHTML = '';
        data.brain_power.forEach((b) => {
          if (isUiHiddenBrain(b.brain || '')) return;
          const tr = document.createElement('tr');
          tr.innerHTML =
            '<td>' +
            (b.label || brainLabelForTag(b.brain)) +
            '</td><td>' +
            b.rank1 +
            '</td><td>' +
            b.rank2 +
            '</td><td>' +
            b.rank3 +
            '</td><td>' +
            b.rank4 +
            '</td><td>' +
            b.rank5 +
            '</td>';
          tbody.appendChild(tr);
        });
      }

      const sxMeta = document.getElementById('strategyXDashMeta');
      const sxTb = document.querySelector('#strategyXBrainPowerTable tbody');
      if (sxMeta) {
        const sxLr = data.strategy_x_learning_range || {};
        const sxTotal = data.strategy_x_total_predictions || 0;
        if (sxTotal > 0) {
          sxMeta.innerHTML =
            '<strong>전략 X 백테스트</strong> · 구간 ' +
            (sxLr.start || '-') +
            '–' +
            (sxLr.end || '-') +
            ' · 예측 ' +
            sxTotal +
            '건 (5뇌×5세트, R2 무작위 수준 참고)';
        } else {
          sxMeta.innerHTML =
            '<span class="status-line">전략 X 백테스트 기록 없음 — tools/run_strategy_x_fullbackfill.py 실행</span>';
        }
      }
      if (sxTb && Array.isArray(data.strategy_x_brain_power)) {
        sxTb.innerHTML = '';
        data.strategy_x_brain_power.forEach((b) => {
          const tr = document.createElement('tr');
          tr.innerHTML =
            '<td>' +
            (b.label || b.brain) +
            ' <code class="tag-code">' +
            (b.brain || '') +
            '</code></td><td>' +
            (b.rank1 || 0) +
            '</td><td>' +
            (b.rank2 || 0) +
            '</td><td>' +
            (b.rank3 || 0) +
            '</td><td>' +
            (b.rank4 || 0) +
            '</td><td>' +
            (b.rank5 || 0) +
            '</td><td>' +
            (b.avg_matched != null ? b.avg_matched : '-') +
            '</td>';
          sxTb.appendChild(tr);
        });
      }
    } catch (e) {
      if (body) {
        body.innerHTML =
          '<div class="status-line error">대시보드 실패: ' + (e.message || e) + '</div>';
      }
    }
  }

  function renderFreqChart(elId, freqObj, title) {
    const host = document.getElementById(elId);
    if (!host) return;
    if (!freqObj || typeof freqObj !== 'object') {
      host.innerHTML = '<div class="status-line">데이터 없음</div>';
      return;
    }
    const arr = [];
    for (let n = 1; n <= 45; n++) {
      const o = freqObj[n];
      arr.push({ n: n, c: o ? o.count : 0 });
    }
    const maxC = Math.max(1, ...arr.map((x) => x.c));
    let html = title ? '<div style="font-weight:700;margin-bottom:8px">' + title + '</div>' : '';
    arr.forEach((x) => {
      const pct = Math.round((x.c / maxC) * 100);
      html +=
        '<div class="freq-row"><span class="n">' +
        x.n +
        '</span><div class="bar"><i style="width:' +
        pct +
        '%"></i></div><span class="freq-count">' +
        Math.min(x.c, 9999) +
        '</span></div>';
    });
    host.innerHTML = html;
  }

  function renderBonusFreqChart(elId, items) {
    const host = document.getElementById(elId);
    const hint = document.getElementById('statsBonusHint');
    if (!host) return;
    if (!items || !items.length) {
      host.innerHTML =
        '<div class="status-line">데이터 없음 — python tools/collect_bonus_stats.py 실행</div>';
      if (hint) hint.textContent = '';
      return;
    }
    if (hint) hint.textContent = 'lotto_bonus_stats (보너스 당첨 번호별 누적)';
    const freqObj = {};
    items.forEach((it) => {
      const k = it.bonus_no;
      freqObj[k] = { count: it.total_count != null ? it.total_count : 0 };
    });
    for (let n = 1; n <= 45; n++) {
      if (!freqObj[n]) freqObj[n] = { count: 0 };
    }
    renderFreqChart(elId, freqObj, '');
  }

  function renderFreqWithRanks(elId, items) {
    const host = document.getElementById(elId);
    const hint = document.getElementById('statsNumberRankHint');
    if (!host) return;
    if (!items || !items.length) {
      host.innerHTML =
        '<div class="status-line">데이터 없음 — python tools/collect_number_freq.py 실행</div>';
      if (hint) hint.textContent = '';
      return;
    }
    if (hint) hint.textContent = 'lotto_number_freq — 최다·최소 순위 뱃지(각 상위 3위)';
    const byN = {};
    items.forEach((it) => {
      byN[it.number] = it;
    });
    const maxC = Math.max(
      1,
      ...items.map(function (it) {
        return it.total_count != null ? it.total_count : 0;
      }),
    );
    let html = '';
    for (let n = 1; n <= 45; n++) {
      const it = byN[n];
      const c = it && it.total_count != null ? it.total_count : 0;
      const pct = Math.round((c / maxC) * 100);
      let pills = '';
      if (it && it.rank_most != null && it.rank_most <= 3) {
        pills +=
          '<span class="rank-pill rank-pill--hot">최다 ' + it.rank_most + '위</span>';
      }
      if (it && it.rank_least != null && it.rank_least <= 3) {
        pills +=
          '<span class="rank-pill rank-pill--cold">최소 ' + it.rank_least + '위</span>';
      }
      html +=
        '<div class="freq-row"><span class="n">' +
        n +
        '</span><div class="bar"><i style="width:' +
        pct +
        '%"></i></div><span class="freq-count">' +
        c +
        '</span><span class="rank-pills">' +
        pills +
        '</span></div>';
    }
    host.innerHTML = html;
  }

  function renderCooccur3Rows(items) {
    const tb = document.querySelector('#statsCooccur3Table tbody');
    const hint = document.getElementById('statsCooccur3Hint');
    if (!tb) return;
    if (!items || !items.length) {
      tb.innerHTML =
        '<tr><td colspan="5">데이터 없음 — python tools/collect_cooccur.py 실행</td></tr>';
      if (hint) hint.textContent = '';
      return;
    }
    if (hint) hint.textContent = 'lotto_cooccur_3 · 회차당 C(6,3) 조합 전수 (당첨 6개 기준)';
    tb.innerHTML = '';
    items.forEach(function (row, idx) {
      const tr = document.createElement('tr');
      const nums = [row.num1, row.num2, row.num3];
      const balls = renderBallsHtml(nums, null, null);
      tr.innerHTML =
        '<td>' +
        (idx + 1) +
        '</td><td>' +
        balls +
        '</td><td>' +
        row.count +
        '</td><td>' +
        (row.last_draw_no != null ? row.last_draw_no : '') +
        '</td><td>' +
        (row.last_draw_date != null ? row.last_draw_date : '') +
        '</td>';
      tb.appendChild(tr);
    });
  }

  function renderCooccur4Rows(items) {
    const tb = document.querySelector('#statsCooccur4Table tbody');
    const hint = document.getElementById('statsCooccur4Hint');
    if (!tb) return;
    if (!items || !items.length) {
      tb.innerHTML =
        '<tr><td colspan="5">데이터 없음 — python tools/collect_cooccur.py 실행</td></tr>';
      if (hint) hint.textContent = '';
      return;
    }
    if (hint) hint.textContent = 'lotto_cooccur_4 · 회차당 C(6,4) 조합 전수';
    tb.innerHTML = '';
    items.forEach(function (row, idx) {
      const tr = document.createElement('tr');
      const nums = [row.num1, row.num2, row.num3, row.num4];
      const balls = renderBallsHtml(nums, null, null);
      tr.innerHTML =
        '<td>' +
        (idx + 1) +
        '</td><td>' +
        balls +
        '</td><td>' +
        row.count +
        '</td><td>' +
        (row.last_draw_no != null ? row.last_draw_no : '') +
        '</td><td>' +
        (row.last_draw_date != null ? row.last_draw_date : '') +
        '</td>';
      tb.appendChild(tr);
    });
  }

  function mergeHallBrainSummary(summ) {
    const acc = new Map();
    summ.forEach((s) => {
      const raw = String(s.brain_tag || '');
      if (isUiHiddenBrain(raw)) return;
      const c = canonicalBrainTag(raw);
      if (!acc.has(c)) {
        acc.set(c, { brain_tag: c, r1: 0, r2: 0, r3: 0, r4: 0, r5: 0, total_hits: 0 });
      }
      const o = acc.get(c);
      o.r1 += Number(s.r1 || 0);
      o.r2 += Number(s.r2 || 0);
      o.r3 += Number(s.r3 || 0);
      o.r4 += Number(s.r4 || 0);
      o.r5 += Number(s.r5 || 0);
      o.total_hits += Number(s.total_hits || 0);
    });
    return Array.from(acc.values()).sort((a, b) =>
      String(a.brain_tag).localeCompare(String(b.brain_tag)),
    );
  }

  let _hallAutoRefreshTimer = null;

  function ensureHallAutoRefresh() {
    if (_hallAutoRefreshTimer != null) return;
    _hallAutoRefreshTimer = setInterval(() => {
      const hall = document.getElementById('view-hall');
      const navBtns = document.querySelectorAll('.nav-btn[data-view="hall"]');
      const hallActive =
        hall &&
        hall.classList.contains('active') &&
        Array.from(navBtns).some((b) => b.classList.contains('active'));
      if (hallActive) loadHall();
    }, 30000);
  }

  async function loadHall() {
    const rankEl = document.getElementById('hallRankFilter');
    const brainEl = document.getElementById('hallBrainFilter');
    const rank = rankEl ? parseInt(rankEl.value, 10) || 0 : 0;
    const brain = brainEl && brainEl.value ? brainEl.value : '';
    const qs =
      '?rank=' +
      rank +
      (brain ? '&brain=' + encodeURIComponent(brain) : '') +
      '&limit=2500';
    const sumTb = document.querySelector('#hallBrainSummary tbody');
    const detTb = document.querySelector('#hallTable tbody');
    if (!sumTb || !detTb) return;
    sumTb.innerHTML = '<tr><td colspan="7">불러오는 중…</td></tr>';
    detTb.innerHTML = '<tr><td colspan="7">불러오는 중…</td></tr>';
    try {
      const res = await fetch(API + '/hall-of-fame' + qs);
      const data = await res.json();
      const summ = mergeHallBrainSummary(data.brain_summary || []);
      sumTb.innerHTML = '';
      summ.forEach((s) => {
        const tr = document.createElement('tr');
        const tot =
          (s.r1 || 0) + (s.r2 || 0) + (s.r3 || 0) + (s.r4 || 0) + (s.r5 || 0);
        const lab = brainLabelForTag(s.brain_tag);
        tr.innerHTML =
          '<td>' +
          lab +
          ' <code class="tag-code">' +
          s.brain_tag +
          '</code></td><td>' +
          s.r1 +
          '</td><td>' +
          s.r2 +
          '</td><td>' +
          s.r3 +
          '</td><td>' +
          s.r4 +
          '</td><td>' +
          s.r5 +
          '</td><td>' +
          tot +
          '</td>';
        sumTb.appendChild(tr);
      });
      const recs = data.records || [];
      detTb.innerHTML = '';
      recs.slice(0, 800).forEach((r) => {
        if (isUiHiddenBrain(r.brain_tag)) return;
        const tr = document.createElement('tr');
        const winNums = r.winning_numbers || [];
        const winSet = new Set(winNums.map(Number));
        const predBalls =
          '<div class="hall-pred-balls">' +
          renderBallsHtml(r.numbers || [], winSet, null) +
          '</div>';
        const winBalls = renderBallsHtml(winNums, null, null);
        const hitStr = (r.matched_numbers || []).join(', ');
        const tb =
          '<span class="' +
          tierBadgeClass(r.tier_rank) +
          '">' +
          (r.tier_label || '') +
          '</span>';
        const canon = canonicalBrainTag(r.brain_tag);
        const lab = brainLabelForTag(r.brain_tag);
        const rawTag = String(r.brain_tag || '');
        const tagCell =
          lab +
          ' <code class="tag-code" title="' +
          (rawTag !== canon ? 'DB: ' + rawTag : '') +
          '">' +
          canon +
          '</code>';
        tr.innerHTML =
          '<td>' +
          r.draw_no +
          '</td><td>' +
          tagCell +
          '</td><td>' +
          tb +
          '</td><td>' +
          r.matched_count +
          '</td><td>' +
          hitStr +
          '</td><td>' +
          predBalls +
          '</td><td>' +
          winBalls +
          '</td>';
        detTb.appendChild(tr);
      });
      ensureHallAutoRefresh();
    } catch (e) {
      sumTb.innerHTML = '<tr><td colspan="7">오류</td></tr>';
      detTb.innerHTML = '<tr><td colspan="7">오류: ' + (e.message || e) + '</td></tr>';
    }
  }

  async function loadStats() {
    const note = document.getElementById('statsDbNote');
    const sumEl = document.getElementById('statsSummary');
    const pre = document.getElementById('statsPre');
    const trendHost = document.getElementById('statsTrendPanels');
    if (pre) pre.textContent = '불러오는 중…';
    try {
      const res = await fetch(API + '/stats/comprehensive-full');
      const data = await res.json();
      if (data.error) {
        if (note) note.textContent = data.error;
        if (pre) pre.textContent = JSON.stringify(data, null, 2);
        return;
      }
      if (note) note.textContent = data.db_note || '';
      if (sumEl) {
        const odd = data.odd_even || {};
        const rng = data.range_distribution || {};
        const cons = data.consecutive || {};
        const sr = data.sum_range || {};
        sumEl.innerHTML =
          '<div class="dash-tile"><div class="k">총 회차</div><div class="v">' +
          data.total_draws +
          '</div></div>' +
          '<div class="dash-tile"><div class="k">최신</div><div class="v">' +
          data.latest_draw +
          '</div><div style="font-size:0.78rem;color:var(--muted)">' +
          (data.latest_date || '') +
          '</div></div>' +
          '<div class="dash-tile"><div class="k">합계 평균</div><div class="v">' +
          (sr.average != null ? sr.average : '-') +
          '</div><div style="font-size:0.75rem;color:var(--muted)">최소 ' +
          (sr.min ?? '-') +
          ' · 최대 ' +
          (sr.max ?? '-') +
          '</div></div>' +
          '<div class="dash-tile"><div class="k">연속번호 출현</div><div class="v">' +
          (cons.percentage != null ? cons.percentage + '%' : '-') +
          '</div></div>';
        let oddHtml = '<div class="trend-panel"><strong>홀짝 패턴 (전체)</strong><br/>';
        Object.keys(odd).forEach((k) => {
          oddHtml += k + ': ' + odd[k] + '회 · ';
        });
        oddHtml += '</div>';
        let rngHtml = '<div class="trend-panel"><strong>번호대 분포 (전체)</strong><br/>';
        Object.keys(rng).forEach((k) => {
          rngHtml += k + ': ' + rng[k] + ' · ';
        });
        rngHtml += '</div>';
        sumEl.innerHTML += oddHtml + rngHtml;
      }
      renderFreqChart('statsFreqAll', data.frequency, '');
      renderOddEvenChart(data.odd_even || {});
      renderRangeChart(data.range_distribution || {});
      renderSumChart(data.sum_range || {});
      try {
        const [d3, d4, db, dn] = await Promise.all([
          fetch(API + '/stats/cooccur-3?top=20').then(function (r) {
            return r.json();
          }),
          fetch(API + '/stats/cooccur-4?top=20').then(function (r) {
            return r.json();
          }),
          fetch(API + '/stats/bonus').then(function (r) {
            return r.json();
          }),
          fetch(API + '/stats/number-freq').then(function (r) {
            return r.json();
          }),
        ]);
        renderPairChart(d3.items || []);
        renderFreqWithRanks('statsNumberRanked', dn.items || []);
        renderCooccur3Rows(d3.items || []);
        renderCooccur4Rows(d4.items || []);
        renderBonusFreqChart('statsBonusFreq', db.items || []);
      } catch (eExt) {
        renderPairChart([]);
        renderCooccur3Rows([]);
        renderCooccur4Rows([]);
        const bh = document.getElementById('statsBonusHint');
        const nh = document.getElementById('statsNumberRankHint');
        if (bh) bh.textContent = '확장 통계 API 오류: ' + (eExt.message || eExt);
        if (nh) nh.textContent = '';
        document.getElementById('statsBonusFreq').innerHTML =
          '<div class="status-line error">로드 실패</div>';
        document.getElementById('statsNumberRanked').innerHTML =
          '<div class="status-line error">로드 실패</div>';
      }
      if (trendHost) {
        trendHost.innerHTML = '';
        ['trend_last_10', 'trend_last_30', 'trend_last_50'].forEach((key, idx) => {
          const sizes = [10, 30, 50];
          const t = data[key];
          if (!t || !t.frequency) return;
          const div = document.createElement('div');
          div.className = 'trend-panel';
          div.innerHTML = '<strong>최근 ' + sizes[idx] + '회</strong> · 회차수 ' + (t.draw_count || 0);
          const fid = 'freqTrend' + idx;
          const inner = document.createElement('div');
          inner.id = fid;
          div.appendChild(inner);
          trendHost.appendChild(div);
          renderFreqChart(fid, t.frequency, '');
        });
      }
      const dump = Object.assign({}, data);
      delete dump.frequency;
      delete dump.trend_last_10;
      delete dump.trend_last_30;
      delete dump.trend_last_50;
      if (pre) pre.textContent = JSON.stringify(dump, null, 2);
    } catch (e) {
      if (pre) pre.textContent = '오류: ' + (e.message || e);
    }
  }

  async function loadCollectStatus() {
    const box = document.getElementById('collectStatusBox');
    if (!box) return;
    try {
      const res = await fetch(API + '/collect-status');
      const h = await res.json();
      box.innerHTML =
        '최대 회차: <strong>' +
        (h.max_draw_no || 0) +
        '</strong> · DB 행 수: ' +
        (h.row_count || 0) +
        ' · 다음 수집 후보: <strong>' +
        (h.next_draw_no || '-') +
        '</strong> (' +
        (h.next_draw_date || '') +
        ')';
    } catch (e) {
      box.textContent = '상태 로드 실패: ' + (e.message || e);
    }
  }

  async function runCollectDraws(mode, drawNoOpt) {
    const logEl = document.getElementById('collectLog');
    const busy = document.getElementById('collectBusy');
    const summ = document.getElementById('collectResultSummary');
    const body = { mode: mode || 'single' };
    if (drawNoOpt != null && String(drawNoOpt).trim() !== '') body.draw_no = Number(drawNoOpt);
    if (busy) busy.classList.remove('hidden');
    if (summ) summ.textContent = '';
    if (logEl) logEl.textContent = '요청 중…';
    try {
      const data = await fetchJsonHandled(API + '/collect-draws', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (logEl) {
        logEl.textContent = JSON.stringify(data, null, 2);
      }
      if (summ) {
        summ.innerHTML =
          '<strong>요약</strong> · ok: ' +
          data.ok +
          ' · 수집 ' +
          (data.count != null ? data.count : 0) +
          '건' +
          (data.collected && data.collected.length
            ? ' <code>[' + data.collected.join(', ') + ']</code>'
            : '') +
          (data.errors && data.errors.length
            ? '<br/><span class="collect-err">오류: ' + data.errors.join(' / ') + '</span>'
            : '');
      }
      await loadCollectStatus();
      await loadDashboard();
      await loadBrainMeta();
    } catch (e) {
      if (logEl) logEl.textContent = '오류: ' + (e.message || e);
      if (summ) summ.textContent = '';
    } finally {
      if (busy) busy.classList.add('hidden');
    }
  }

  async function loadBrainStatus() {
    const host = document.getElementById('brainStatusHost');
    if (!host) return;
    host.innerHTML = '불러오는 중…';
    try {
      const res = await fetch(API + '/brain/status');
      const data = await res.json();
      const profiles = data.brain_profiles || [];
      let html =
        '<div style="font-size:0.9rem;margin-bottom:12px">' +
        (data.grade_emoji || '') +
        ' <strong>' +
        (data.grade || '') +
        '</strong> · 총 예측 ' +
        (data.total_predictions || 0) +
        '건</div>';
      html +=
        '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:10px">';
      profiles.forEach((p) => {
        if (p.status === 'hidden') return;
        const boxStyle = 'flex-direction:column;align-items:stretch';
        html +=
          '<div class="set-row" style="' +
          boxStyle +
          '">' +
          '<strong>' +
          (p.method || brainLabelForTag(p.brain_tag)) +
          '</strong> · ' +
          canonicalBrainTag(p.brain_tag) +
          '<div style="font-size:0.78rem;color:var(--muted)">평균 ' +
          p.avg_match +
          ' · 최고 ' +
          p.best_match +
          ' · 1~5등 ' +
          p.rank1 +
          '/' +
          p.rank2 +
          '/' +
          p.rank3 +
          '/' +
          p.rank4 +
          '/' +
          p.rank5 +
          '</div>' +
          '</div>';
      });
      html += '</div>';
      host.innerHTML = html;
    } catch (e) {
      host.innerHTML = '<div class="status-line error">오류: ' + (e.message || e) + '</div>';
    }
  }

  /** 단일 회차 예측 행을 서버에서 가져와 그리드에 반영 (실행 버튼·불러오기 공용) */
  async function refreshPredictionsFromServer(drawNo) {
    const d = Number(drawNo);
    const data = await fetchJsonHandled(API + '/predictions/draw/' + d);
    const rows = data.predictions || (Array.isArray(data) ? data : []);
    if (!Array.isArray(rows)) {
      throw new Error('예측 응답 형식 오류');
    }
    _lastRows = rows;
    _lastDraw = d;
    lotto4SwitchBrainTab(_currentBrain);
    return rows.length;
  }

  let _drawSyncSeq = 0;

  /** 회차 스테퍼·셀렉트 변경 시 저장분 자동 동기화 (빠른 연속 클릭은 마지막 요청만 반영) */
  async function syncPredictionsForCurrentDraw() {
    const st = document.getElementById('actionStatus');
    const d = getDrawNoFromUi();
    if (!d || d < 1) return;
    const seq = ++_drawSyncSeq;
    if (st) setStatus(st, d + '회 불러오는 중…', true);
    try {
      const n = await refreshPredictionsFromServer(d);
      if (seq !== _drawSyncSeq) return;
      if (st) setStatus(st, d + '회 · 저장분 ' + n + '행 (자동)', true);
    } catch (e) {
      if (seq !== _drawSyncSeq) return;
      _lastRows = [];
      _lastDraw = d;
      lotto4SwitchBrainTab(_currentBrain);
      if (st) setStatus(st, d + '회: ' + (e && e.message), false);
    }
  }

  async function runPredict() {
    const st = document.getElementById('actionStatus');
    const d = getDrawNoFromUi();
    if (!d || d < 1) {
      setStatus(st, '회차를 선택하세요.', false);
      return;
    }
    setStatus(st, '예측 중…', true);
    try {
      const data = await fetchJsonHandled(API + '/predict/' + d, { method: 'POST' });
      if (data.error) {
        setStatus(st, '오류: ' + data.error, false);
        return;
      }
      if (data.reason) {
        setStatus(st, '거절: ' + data.reason, false);
        return;
      }
      _lastDraw = d;
      await loadBrainMeta();
      const n = await refreshPredictionsFromServer(d);
      setStatus(st, d + '회 예측 완료 · ' + n + '행 표시', true);
    } catch (e) {
      setStatus(st, '실패: ' + (e && e.message), false);
    }
  }

  async function loadSaved() {
    const st = document.getElementById('actionStatus');
    const d = getDrawNoFromUi();
    if (!d) {
      setStatus(st, '회차를 선택하세요.', false);
      return;
    }
    setStatus(st, 'DB에서 불러오는 중…', true);
    try {
      const n = await refreshPredictionsFromServer(d);
      setStatus(st, d + '회 · 저장분 ' + n + '행 표시 (재동기화)', true);
    } catch (e) {
      setStatus(st, '실패: ' + (e && e.message), false);
    }
  }

  async function loadTierModalContent(d) {
    const tierNoEl = document.getElementById('tierDrawNo');
    const jump = document.getElementById('tierJumpInput');
    const actualEl = document.getElementById('tierActualNumbers');
    const sectionsEl = document.getElementById('tierSections');
    if (!sectionsEl) return;
    _tierModalDraw = d;
    if (tierNoEl) tierNoEl.textContent = String(d);
    if (jump) jump.value = String(d);
    sectionsEl.innerHTML = '<p class="tier-loading">불러오는 중…</p>';
    if (actualEl) actualEl.innerHTML = '';
    try {
      const data = await fetchJsonHandled(API + '/predictions/draw/' + d + '/tier-wins');
      const win = data.actual_numbers;
      const bonusNum = data.bonus != null && data.bonus !== '' ? Number(data.bonus) : null;
      if (win && win.length === 6 && actualEl) {
        const sorted = win.map(Number).sort((a, b) => a - b);
        let h = '<div class="tier-actual-inner">';
        h += '<span class="tier-actual-label">실제 당첨번호</span>';
        h += renderBallsHtml(sorted, null, null);
        if (bonusNum != null && !Number.isNaN(bonusNum)) {
          h +=
            '<span class="tier-bonus-line"><span class="strip-bonus-label">보너스</span>' +
            renderBonusBall(bonusNum) +
            '</span>';
        }
        h += '</div>';
        actualEl.innerHTML = h;
      } else if (actualEl) {
        actualEl.innerHTML =
          '<p class="tier-no-draw">이 회차는 아직 당첨번호가 없거나 미수집입니다. (1~5등 목록은 채점 후 표시됩니다.)</p>';
      }
      const items = data.items || [];
      const byRank = { 1: [], 2: [], 3: [], 4: [], 5: [] };
      items.forEach((it) => {
        const rk = it.rank;
        if (byRank[rk]) byRank[rk].push(it);
      });
      const winSet = win && win.length === 6 ? new Set(win.map(Number)) : null;
      let html = '';
      const titles = { 1: '1등', 2: '2등', 3: '3등', 4: '4등', 5: '5등' };
      for (let r = 1; r <= 5; r++) {
        const list = byRank[r];
        html += '<section class="tier-section"><h4 class="tier-section-title t' + r + '">' + titles[r] + '</h4>';
        if (!list.length) {
          html += '<p class="tier-empty-rank">해당 등수 적중 없음</p>';
        } else {
          list.forEach((it) => {
            if (isUiHiddenBrain(it.brain_tag)) return;
            const label = brainLabelForTag(it.brain_tag);
            const nums = it.nums || [];
            html += '<div class="tier-set">';
            html += '<div class="tier-set-meta">' + label + '</div>';
            html += renderBallsHtml(nums, winSet, bonusNum);
            html += '</div>';
          });
        }
        html += '</section>';
      }
      if (!items.length) {
        html =
          '<p class="tier-global-empty">이 회차에 저장된 1~5등 적중 예측이 없습니다. 미추첨·미채점이거나 해당 회차 예측이 없을 수 있습니다.</p>' +
          html;
      }
      sectionsEl.innerHTML = html;
    } catch (e) {
      sectionsEl.innerHTML = '<p class="error">오류: ' + (e.message || e) + '</p>';
    }
  }

  async function openTierModal() {
    const d = getDrawNoFromUi();
    const modal = document.getElementById('modalTier');
    if (!d || !modal) return;
    _tierModalMode = 'predict';
    modal.classList.remove('hidden');
    await loadTierModalContent(d);
  }

  function tierModalNav(delta) {
    if (_tierModalDraw == null) return;
    let d = _tierModalDraw + delta;
    if (_tierModalMode === 'strategy-x') {
      d = Math.max(STRATEGY_X_DRAW_MIN, Math.min(Math.max(_nextDrawNo || 1229, 1228), d));
      setSxDrawNo(d);
      loadStrategyX(d, { generate: false }).then(() => renderSxTierModalFromRows(d, _sxRows));
      return;
    }
    const min = Math.max(1, _drawMin);
    const max = Math.max(min, _nextDrawNo);
    d = Math.max(min, Math.min(max, d));
    setDrawNoUi(d);
    loadTierModalContent(d);
  }

  function tierModalJump() {
    const inp = document.getElementById('tierJumpInput');
    const n = parseInt(inp && inp.value, 10);
    if (!n || n < 1) return;
    if (_tierModalMode === 'strategy-x') {
      const max = Math.max(_nextDrawNo || 1229, 1228);
      const d = Math.max(STRATEGY_X_DRAW_MIN, Math.min(n, max));
      setSxDrawNo(d);
      loadStrategyX(d, { generate: false }).then(() => renderSxTierModalFromRows(d, _sxRows));
      return;
    }
    const min = Math.max(1, _drawMin);
    const max = Math.max(min, _nextDrawNo);
    const d = Math.max(min, Math.min(n, max));
    setDrawNoUi(d);
    loadTierModalContent(d);
  }

  function closeTierModal() {
    const modal = document.getElementById('modalTier');
    if (modal) modal.classList.add('hidden');
  }

  window.tierModalNav = tierModalNav;
  window.tierModalJump = tierModalJump;
  window.closeTierModal = closeTierModal;

  function getKakaoBrainOrder() {
    const eliteOnly = document.getElementById('chkEliteOnly');
    const on = !!(eliteOnly && eliteOnly.checked);
    if (!on) return BRAIN_ORDER.slice();
    if (_eliteTags.size === 0) return [];
    return BRAIN_ORDER.filter((t) => _eliteTags.has(t));
  }

  function buildKakaoText(drawDateLine, order) {
    const lines = [];
    lines.push('🎰 [4군 AI 예측] 제' + _lastDraw + '회');
    lines.push('📅 ' + drawDateLine);
    lines.push('━━━━━━━━━━━━━━');
    const circled = ['①', '②', '③', '④', '⑤', '⑥', '⑦', '⑧', '⑨', '⑩'];
    order.forEach((tag) => {
      const list = _lastRows.filter((r) => canonicalBrainTag(r.brain_tag) === tag);
      if (!list.length) return;
      const rk = _rankByTag[tag];
      const rkTxt = rk != null ? rk + '위' : '-위';
      const tabLabel = brainLabelForTag(tag);
      lines.push('');
      lines.push('🧠 ' + tabLabel + ' (' + rkTxt + ')');
      const n = _nanoByTag[tag] || {};
      lines.push(
        '  역대 전적: 1등 ' +
          (n.r1 || 0) +
          '회 | 2등 ' +
          (n.r2 || 0) +
          '회 | 3등 ' +
          (n.r3 || 0) +
          '회 | 4등 ' +
          (n.r4 || 0) +
          '회 | 5등 ' +
          (n.r5 || 0) +
          '회',
      );
      list.forEach((r, i) => {
        const nums = fmtNums(r)
          .map((x) => String(x).padStart(2, '0'))
          .join(' ');
        const cstr = confidenceDisplayPct(r);
        const suff = cstr != null ? ' (신뢰 ' + cstr + '%)' : '';
        const emoji = circled[i] || String(i + 1) + ')';
        lines.push('  ' + emoji + ' ' + nums + suff);
      });
    });
    lines.push('');
    lines.push('━━━━━━━━━━━━━━');
    lines.push('🤖 4군 v13 독립 엔진');
    return lines.join('\n');
  }

  function lotto4CopyKakaoText() {
    if (!_lastDraw || !_lastRows.length) return '';
    const order = getKakaoBrainOrder();
    if (!order.length) return '';
    return buildKakaoText('(추첨일: 복사 버튼 사용 시 자동 조회)', order);
  }
  window.lotto4CopyKakaoText = lotto4CopyKakaoText;

  async function copyKakao() {
    const st = document.getElementById('actionStatus');
    if (!_lastDraw || !_lastRows.length) {
      setStatus(st, '먼저 예측을 불러오세요.', false);
      return;
    }
    const order = getKakaoBrainOrder();
    if (!order.length) {
      setStatus(st, '엘리트만 표시 중인데 고적중 뇌가 없습니다. 체크를 해제하세요.', false);
      return;
    }
    let dateLine = '미수집/미추첨';
    try {
      const dj = await fetchJsonHandled(API + '/draws?draw_no=' + _lastDraw);
      const dr = dj.draws && dj.draws[0];
      if (dr && dr.draw_date) dateLine = dr.draw_date + ' 추첨';
      else dateLine = '미추첨 또는 당첨 DB 미수집';
    } catch (_e) {
      dateLine = '추첨일 조회 실패';
    }
    const text = buildKakaoText(dateLine, order);
    if (!text.trim()) {
      setStatus(st, '복사할 예측이 없습니다.', false);
      return;
    }
    navigator.clipboard.writeText(text).then(
      () => setStatus(st, '카톡용 텍스트 복사됨', true),
      () => setStatus(st, '복사 실패(브라우저 권한)', false),
    );
  }

  function goToDirectDraw() {
    const inp = document.getElementById('drawDirectInput');
    const no = parseInt(inp && inp.value, 10);
    if (!no || no < 1) return;
    const min = Math.max(1, _drawMin);
    const max = Math.max(min, _nextDrawNo);
    const use = Math.max(min, Math.min(no, max));
    setDrawNoUi(use);
    if (inp && use !== no) inp.value = String(use);
    syncPredictionsForCurrentDraw();
  }
  window.goToDirectDraw = goToDirectDraw;

  document.addEventListener('DOMContentLoaded', () => {
    refreshEliteTags();
    loadDashboard()
      .then(() => loadBrainMeta())
      .then(() => syncPredictionsForCurrentDraw());

    document.querySelectorAll('.nav-btn[data-view]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const v = btn.getAttribute('data-view');
        switchView(v);
        if (v === 'predict') syncPredictionsForCurrentDraw();
        if (v === 'hall') loadHall();
        if (v === 'stats') loadStats();
        if (v === 'truth') loadTruth();
        if (v === 'strategy-x') {
          syncSxDrawOptions();
          loadStrategyX(getSxDrawNo());
        }
        if (v === 'combo-lookup') loadComboLookupView();
        if (v === 'all-combos') loadAllCombosView();
        if (v === 'brain') loadBrainStatus();
        if (v === 'data') {
          loadCollectStatus();
        }
      });
    });

    document.getElementById('btnRefreshDash')?.addEventListener('click', loadDashboard);
    document.getElementById('btnReloadTruth')?.addEventListener('click', loadTruth);

    document.getElementById('btnStrategyXGenerate')?.addEventListener('click', () => {
      loadStrategyX(getSxDrawNo(), { generate: true });
    });
    document.getElementById('btnStrategyXReload')?.addEventListener('click', () => {
      loadStrategyX(getSxDrawNo(), { generate: false });
    });
    document.getElementById('btnSxTierWins')?.addEventListener('click', openSxTierModal);
    document.getElementById('btnSxKakao')?.addEventListener('click', copySxKakao);
    document.getElementById('btnSxDrawPrev')?.addEventListener('click', () => {
      const d = getSxDrawNo();
      if (d > STRATEGY_X_DRAW_MIN) loadStrategyX(d - 1);
    });
    document.getElementById('btnSxDrawNext')?.addEventListener('click', () => {
      const d = getSxDrawNo();
      const max = Math.max(_nextDrawNo || 1229, 1228);
      if (d < max) loadStrategyX(d + 1);
    });
    document.getElementById('btnSxDrawDirectGo')?.addEventListener('click', () => {
      const inp = document.getElementById('sxDrawDirectInput');
      const no = parseInt(inp && inp.value, 10);
      if (!no || no < 1) return;
      const max = Math.max(_nextDrawNo || 1229, 1228);
      loadStrategyX(Math.max(STRATEGY_X_DRAW_MIN, Math.min(no, max)));
    });
    document.getElementById('sxDrawSelect')?.addEventListener('change', () => {
      const sx = document.getElementById('sxDrawSelect');
      const d = parseInt(sx && sx.value, 10);
      if (d) loadStrategyX(d);
    });

    document.getElementById('btnPredict')?.addEventListener('click', runPredict);
    document.getElementById('btnLoadPred')?.addEventListener('click', loadSaved);
    document.getElementById('btnKakao')?.addEventListener('click', copyKakao);
    document.getElementById('chkEliteOnly')?.addEventListener('change', () => {
      updateEliteTabVisibility();
      lotto4SwitchBrainTab(_currentBrain);
    });

    document.getElementById('btnDrawPrev')?.addEventListener('click', () => {
      const d = getDrawNoFromUi();
      const min = Math.max(1, _drawMin);
      if (d > min) {
        setDrawNoUi(d - 1);
        syncPredictionsForCurrentDraw();
      }
    });
    document.getElementById('btnDrawNext')?.addEventListener('click', () => {
      const d = getDrawNoFromUi();
      const max = Math.max(1, _nextDrawNo);
      if (d < max) {
        setDrawNoUi(d + 1);
        syncPredictionsForCurrentDraw();
      }
    });

    document.getElementById('btnDrawDirectGo')?.addEventListener('click', goToDirectDraw);
    document.getElementById('drawDirectInput')?.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter') goToDirectDraw();
    });

    document.getElementById('drawSelect')?.addEventListener('change', () => {
      syncPredictionsForCurrentDraw();
    });

    document.getElementById('btnTierWins')?.addEventListener('click', openTierModal);
    document.getElementById('modalTierClose')?.addEventListener('click', closeTierModal);
    document.getElementById('modalTier')?.addEventListener('click', (e) => {
      if (e.target.id === 'modalTier') closeTierModal();
    });

    document.getElementById('btnReloadHall')?.addEventListener('click', loadHall);
    document.getElementById('btnApplyHallFilter')?.addEventListener('click', loadHall);

    document.getElementById('btnReloadStats')?.addEventListener('click', loadStats);
    document.getElementById('btnReloadBrain')?.addEventListener('click', loadBrainStatus);

    document.getElementById('btnCollectAll')?.addEventListener('click', () => runCollectDraws('all'));
    document.getElementById('btnCollectLatest')?.addEventListener('click', () => runCollectDraws('latest'));
    document.getElementById('btnCollectSingle')?.addEventListener('click', () => {
      const inp = document.getElementById('collectDrawNoInput');
      const raw = inp && inp.value ? inp.value.trim() : '';
      if (raw !== '' && !/^\d+$/.test(raw)) {
        const logEl = document.getElementById('collectLog');
        const summ = document.getElementById('collectResultSummary');
        if (summ) summ.innerHTML = '<span class="collect-err">회차는 양의 정수만 입력하세요.</span>';
        if (logEl) logEl.textContent = '';
        return;
      }
      runCollectDraws('single', raw || null);
    });
    document.getElementById('btnCollectStatus')?.addEventListener('click', loadCollectStatus);
    document.getElementById('btnDashRankToggle')?.addEventListener('click', toggleDashRankDropdown);

    document.getElementById('btnComboLookup')?.addEventListener('click', runComboNumberLookup);
    document.getElementById('btnComboReload')?.addEventListener('click', () => loadComboDrawTable(_comboPage || 1));
    document.getElementById('comboOrderSelect')?.addEventListener('change', () => loadComboDrawTable(1));
    document.getElementById('comboPerPageSelect')?.addEventListener('change', () => loadComboDrawTable(1));
    document.getElementById('comboSearchQ')?.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter') loadComboDrawTable(1);
    });
    initComboLookupInputs();

    document.getElementById('btnAcJump')?.addEventListener('click', acDoJump);
    document.getElementById('btnAcQuickSearch')?.addEventListener('click', acDoQuickSearch);
    document.getElementById('btnAcSearch')?.addEventListener('click', acDoSearch);
    document.getElementById('btnAcCsv')?.addEventListener('click', acExportCsv);
    document.getElementById('acWinnersOnly')?.addEventListener('change', acToggleWinnersOnly);
    document.getElementById('acPerPageSelect')?.addEventListener('change', () => loadAcPage(1));
    document.getElementById('acQuickSearch')?.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter') acDoQuickSearch();
    });
    document.getElementById('acJumpInput')?.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter') acDoJump();
    });
    initAcSearchInputs();
  });
})();
