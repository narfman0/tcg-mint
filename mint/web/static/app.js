/* tcg-mint workbench. One file, no build: hash routes, fetch, server-sent events. */
'use strict';

const $ = (sel, el = document) => el.querySelector(sel);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
/* A gallery export (mint gallery) inlines a snapshot as window.MINT_STATIC: the same page,
   read from the snapshot, with thumbnails beside it and every action a no-op. */
const STATIC = window.MINT_STATIC || null;
const snapW = w => STATIC ? [320, 640, 1280].filter(x => x <= Math.max(320, STATIC.width)).reduce((p, c) => Math.abs(c - w) < Math.abs(p - w) ? c : p) : w;
const img = (path, w = 320) => STATIC ? (STATIC.thumbs[`${path}|${snapW(w)}`] || STATIC.thumbs[`${path}|320`] || '') : `/img?path=${encodeURIComponent(path)}&w=${w}`;
const file = path => STATIC ? img(path, 1280) : `/file?path=${encodeURIComponent(path)}`;
const short = h => h ? h.slice(0, 8) : '';
const REMIX = {restyle: 'same picture, redrawn', repose: 'same layout, new picture', new: 'from the prompt alone'};

/* mode: plain or styled art on a board tile; show: the art alone or the whole rendered card (when
   there is one); style: which restyle label a styled tile shows ('current' = the set's own recipe,
   else any label the art cache holds); q: the board's search text. */
const state = {ws: null, set: null, setCode: null, jobs: {}, sel: new Set(), mode: 'styled', show: 'art', style: 'current', q: '',
               ab: {a: null, b: null, wipe: 50, zoom: 1, x: 0, y: 0, blind: false, swap: false}, lab: null, frame: {}};

async function api(path, opts = {}) {
  if (STATIC) {
    if (opts.method && opts.method !== 'GET') throw new Error('this is a read-only gallery; run `mint serve` to act on it');
    if (path === '/api/workspace') return STATIC.workspace;
    if (path === '/api/jobs') return [];
    if (path.startsWith('/api/sets/')) {
      const parts = path.split('/').map(decodeURIComponent);
      if (parts.length === 4) return STATIC.set;
      if (parts[5] === 'printings') return [];
    }
    throw new Error('not in this gallery');
  }
  const r = await fetch(path, {headers: {'Content-Type': 'application/json'}, ...opts,
                              body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined});
  const data = await r.json().catch(() => ({}));
  if (!r.ok) { throw new Error(data.error || data.detail || r.statusText); }
  return data;
}
function toast(msg, bad = false) {
  const d = document.createElement('div'); d.textContent = msg; if (bad) d.className = 'bad';
  $('#toast').appendChild(d); setTimeout(() => d.remove(), bad ? 8000 : 3500);
}
async function submit(job) {
  try { const j = await api('/api/jobs', {method: 'POST', body: job}); state.jobs[j.id] = j; toast(`queued: ${j.title}`); renderJobstrip(); return j; }
  catch (e) { toast(e.message, true); }
}

/* --- data ------------------------------------------------------------------- */
async function loadWorkspace() { state.ws = await api('/api/workspace'); renderNav(); }
async function loadSet(code) {
  if (!code) { state.set = null; state.setCode = null; return; }
  if (code.toUpperCase() === ALL) { await loadAll(); return; }
  state.set = await api(`/api/sets/${encodeURIComponent(code)}`); state.setCode = state.set.code;
}
/* The ALL board: every set's cards on one grid. Each card remembers its set (inSet) and that
   set's style, so badges, the style picker and job buttons work per set. */
const ALL = 'ALL';
async function loadAll() {
  const codes = (state.ws?.sets || []).filter(s => !s.error).map(s => s.code);
  const all = await Promise.all(codes.map(c => api(`/api/sets/${encodeURIComponent(c)}`)));
  const cards = [];
  all.forEach(st => st.cards_detail.forEach(c => cards.push({...c, inSet: st.code, setStyle: st.style})));
  state.set = {code: ALL, name: 'every set', all: true, style: all.some(st => st.style) ? {name: 'per set'} : null,
               path: '', cards_detail: cards, sets: all};
  state.setCode = ALL;
}
const setOf = c => c.inSet || state.set.code;
const styleOf = c => c.setStyle !== undefined ? c.setStyle : state.set.style;
const cardOf = name => state.set && state.set.cards_detail.find(c => c.name === name);

/* --- routing --------------------------------------------------------------- */
function route() {
  const h = location.hash.replace(/^#\/?/, '');
  const p = h.split('/').map(decodeURIComponent);
  if (!p[0]) return {view: 'home'};
  if (p[0] === 'jobs') return {view: 'jobs'};
  if (p[0] === 'styles') return {view: 'styles', name: p[1]};
  if (p[0] === 'all') return p[1] === 'view' ? {view: 'viewer', code: ALL, inSet: p[2], name: p[3]} : {view: 'board', code: ALL};
  if (p[0] === 'set') return {view: p[2] === 'view' ? 'viewer' : p[2] || 'board', code: p[1], name: p[3], key: p[4] === 'view' ? p[5] : undefined};
  return {view: 'home'};
}
async function go() {
  const r = route();
  try {
    if (!state.ws) await loadWorkspace();
    if (r.code && (!state.set || state.set.code.toLowerCase() !== r.code.toLowerCase())) { await loadSet(r.code); state.sel.clear(); }
    const views = {home, board, card, lab, frame, jobs, viewer, edit, styles};
    if (r.view !== 'viewer' && !(r.view === 'card' && r.key)) closeViewer();
    (views[r.view] || home)(r);
    renderNav();
  } catch (e) { $('#main').innerHTML = `<div class="empty bad">${esc(e.message)}</div>`; }
}
window.addEventListener('hashchange', go);

function renderNav() {
  const r = route();
  $('#setnav').innerHTML = (state.ws?.sets || []).map(s =>
    `<a href="#/set/${esc(s.code)}" class="${r.code && r.code.toLowerCase() === s.code.toLowerCase() ? 'on' : ''}"${s.private ? ' title="private: sets/private/, not in git"' : ''}>${esc(s.code)}${s.private ? ' <span class="lock">⌂</span>' : ''}</a>`).join('') +
    (STATIC ? '' : `<a href="#/all" class="all ${r.code === ALL ? 'on' : ''}" title="every set on one board">all</a><a href="#/styles" class="all ${r.view === 'styles' ? 'on' : ''}" title="style templates">styles</a>`);
  $('#comfy').className = 'dot' + (state.ws?.comfy?.alive ? ' on' : '');
  $('#comfy').title = `ComfyUI ${state.ws?.comfy?.url}: ${state.ws?.comfy?.alive ? 'running' : 'not running'}`;
}
function renderJobstrip() {
  const running = Object.values(state.jobs).filter(j => j.state === 'running')[0];
  const queued = Object.values(state.jobs).filter(j => j.state === 'queued').length;
  $('#jobstrip').innerHTML = running
    ? `<span>${esc(running.title)}</span><span class="bar"><i style="width:${running.total ? 100 * running.done / running.total : 0}%"></i></span>` +
      `<span class="mono">${running.done}/${running.total}</span>` + (queued ? `<span class="muted">+${queued}</span>` : '')
    : (queued ? `<span class="muted">${queued} queued</span>` : '');
}

/* --- events ---------------------------------------------------------------- */
function connect() {
  if (STATIC) return;
  const es = new EventSource('/api/events');
  es.addEventListener('job', e => {
    const j = JSON.parse(e.data); const was = state.jobs[j.id]?.state; state.jobs[j.id] = j; renderJobstrip();
    if (j.state !== was && (j.state === 'done' || j.state === 'failed' || j.state === 'cancelled')) {
      toast(`${j.state}: ${j.title}` + (j.error ? ` — ${j.error}` : ''), j.state === 'failed');
      refresh();
    }
    if (route().view === 'jobs') jobs();
  });
  es.addEventListener('progress', e => { const d = JSON.parse(e.data); const j = state.jobs[d.id]; if (j) { j.done = d.done; j.total = d.total; renderJobstrip(); } });
  es.addEventListener('log', e => { const d = JSON.parse(e.data); const j = state.jobs[d.id]; if (j) { j.log.push(d.msg); if (route().view === 'jobs') jobs(); } });
  es.onerror = () => setTimeout(() => { es.close(); connect(); }, 3000);
}
let refreshing = false;
async function refresh() {
  if (refreshing) return; refreshing = true;
  try { await loadWorkspace(); if (state.setCode) await loadSet(state.setCode); await go(); } finally { refreshing = false; }
}

/* --- home ---------------------------------------------------------------------- */
function home() {
  const ws = state.ws, q = (state.q || '').toLowerCase();
  const hit = s => !q || [s.code, s.name, s.style].some(v => (v || '').toLowerCase().includes(q));
  const setsHtml = () => ws.sets.filter(hit).map(s => `
      <a class="setcard" href="#/set/${esc(s.code)}">
        <h3>${esc(s.code)} <span class="muted">${esc(s.name)}</span>${s.private ? ' <span class="badge" title="sets/private/ is git-ignored">private</span>' : ''}</h3>
        <div class="meta">${s.cards} cards${s.style ? ` · style <b>${esc(s.style)}</b>` : ' · no style'}${s.error ? `<div class="bad">${esc(s.error)}</div>` : ''}</div>
      </a>`).join('') || `<div class="empty">${ws.sets.length ? 'nothing matches' : 'no set files in sets/ — <code>mint newset</code> makes one'}</div>`;
  $('#main').innerHTML = `
    <div class="row"><h1>Sets</h1>
      ${STATIC ? '' : `<a class="pill" href="#/all">all sets on one board</a><a class="pill" href="#/styles">styles</a>`}
      <input type="text" id="q" placeholder="filter sets" value="${esc(state.q || '')}" style="margin-left:auto">
      ${STATIC ? '' : '<button id="newset">new set</button>'}
    </div>
    <div class="panel newset" id="newset-form" hidden></div>
    <p class="muted">${esc(ws.home)} · ${ws.cards.count.toLocaleString()} cards on file · you are <b>${esc(ws.maker)}</b> (${esc(ws.maker_code)})</p>
    <div class="setlist">${setsHtml()}</div>`;
  $('#q').oninput = e => { state.q = e.target.value; $('.setlist').innerHTML = setsHtml(); };
  if ($('#newset')) $('#newset').onclick = newSetForm;
}

/* --- set board ------------------------------------------------------------------ */
function badges(c) {
  const b = [];
  if (c.error) b.push(['bad', 'not found']);
  (c.warnings || []).forEach(w => b.push(['warn', w.includes('Universes Beyond') ? 'UB art' : w]));
  if (styleOf(c) && !c.current) b.push(['', 'no restyle']);
  if (c.renders?.plain?.shrunk || c.renders?.styled?.shrunk) b.push(['warn', 'text shrunk']);
  if (c.entry.art) b.push(['accent', 'own art']);
  if (c.entry.printing) b.push(['accent', c.entry.printing]);
  if (c.entry.base) b.push(['accent', 'base ' + c.entry.base]);
  if (c.base_missing) b.push(['warn', `no ${c.base_missing} to start from`]);
  if (c.entry.seed != null) b.push(['accent', 'seed pinned']);
  const remix = c.entry.remix || styleOf(c)?.remix || 'restyle';
  if (remix !== 'restyle') b.push(['accent', remix === 'repose' ? 'repose' : 'new scene']);
  if (!c.renders?.plain && !c.renders?.styled) b.push(['', 'not rendered']);
  return b.map(([k, t]) => `<span class="badge ${k}">${esc(t)}</span>`).join('');
}
/* Restyle labels the art cache holds for these cards, most common first: [label, card count]. */
function styleLabels(cards) {
  const m = new Map();
  cards.forEach(c => (c.variants || []).forEach(v => { if (v.kind === 'restyle') (m.get(v.label) || m.set(v.label, new Set()).get(v.label)).add(c.name); }));
  return [...m].map(([l, s]) => [l, s.size]).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}
/* A card's variant for a label: the one the set's recipe names if it has that label, else the newest. */
function variantFor(c, label) {
  const vs = (c.variants || []).filter(v => v.kind === 'restyle' && v.label === label);
  return vs.find(v => v.hash === c.style_hash) || vs.sort((a, b) => (b.created || '').localeCompare(a.created || ''))[0] || null;
}
/* The image a card shows for the current mode / show / style: {path, card: bool, what} or {none: why}.
   "card" wants the render; without one the art stands in (the tile's shape says which). */
function shown(c) {
  const m = state.mode;
  if (state.show === 'card' && state.style === 'current') {
    const r = c.renders?.[m];
    if (r) return {path: r.path, card: true, what: `render · ${m} · ${r.dpi || '?'} dpi`};
  }
  if (m === 'styled' && state.style !== 'current') {
    const v = variantFor(c, state.style);
    return v ? {path: v.path, what: `${v.label}-${v.hash}`} : {none: `no ${state.style}`};
  }
  const src = c[m];
  return src ? {path: src.path, what: src.label ? `${src.label}-${src.hash}` : src.kind} : {none: m === 'styled' ? 'no restyle yet' : 'crop not fetched'};
}
function tilePic(c) {
  const s = shown(c);
  if (s.none) return `<div class="pic art"><div class="none">${esc(s.none)}</div></div>`;
  return `<div class="pic ${s.card ? '' : 'art'}"><img loading="lazy" src="${img(s.path, 320)}"></div>`;
}
function boardCards() {
  const st = state.set, filt = state.filter || '', q = (state.q || '').toLowerCase();
  const hit = c => !q || [c.name, c.card?.type_line, c.inSet, c.card?.artist, String(c.number ?? '')].some(v => (v || '').toLowerCase().includes(q));
  return st.cards_detail.filter(c => hit(c) && (!filt || badges(c).includes(`>${filt}<`) || (filt === 'no restyle' && !c.current)
    || (filt === `no ${state.style}` && !variantFor(c, state.style))));
}
function tileHtml(c) {
  return `
      <div class="tile ${state.sel.has(c.name) ? 'sel' : ''}" data-name="${esc(c.name)}" data-set="${esc(setOf(c))}">
        ${tilePic(c)}
        <div class="name"><b>${esc(c.name)}</b><span class="muted mono">${state.set.all ? esc(c.inSet) + ' ' : ''}${c.number ?? ''}</span></div>
        <div class="badges">${badges(c)}</div>
      </div>`;
}
function board() {
  const st = state.set, code = st.code, all = !!st.all;
  const sel = state.sel, n = sel.size, names = [...sel];
  const filt = state.filter || '';
  const labels = styleLabels(st.cards_detail);
  if (state.style !== 'current' && !labels.some(([l]) => l === state.style)) state.style = 'current';
  const cards = boardCards();
  const filters = ['no restyle', ...(state.style !== 'current' ? [`no ${state.style}`] : []), 'not rendered', 'text shrunk', 'UB art', 'own art'];
  $('#main').innerHTML = `
    <div class="row"><h1>${esc(code)} <span class="muted">${esc(st.name)}</span></h1>
      ${all ? '' : `<a class="pill" href="#/set/${esc(code)}/edit">edit</a><a class="pill" href="#/set/${esc(code)}/lab">recipe lab</a><a class="pill" href="#/set/${esc(code)}/frame">frame</a>`}
      <span class="muted">${st.cards_detail.length} cards${all ? ` across ${st.sets.length} sets` : ''}${st.style && !all ? ` · style ${esc(st.style.name)}` : ''}${st.base && !all ? ` · from <b>${esc(st.base)}</b>` : ''}${all ? '' : ` · <span class="mono">${esc(st.path)}</span>`}</span></div>
    <div class="toolbar">
      <span class="seg">${['plain', 'styled'].map(m => `<button data-mode="${m}" class="${state.mode === m ? 'on' : ''}">${m}</button>`).join('')}</span>
      <span class="seg" title="the art alone, or the whole rendered card where there is one">${[['art', 'art'], ['card', 'card']].map(([m, t]) => `<button data-show="${m}" class="${state.show === m ? 'on' : ''}">${t}</button>`).join('')}</span>
      ${state.mode === 'styled' && labels.length ? `<select id="style" title="which restyle a styled tile shows"><option value="current">${all ? "each set's recipe" : 'current recipe'}</option>
        ${labels.map(([l, k]) => `<option value="${esc(l)}" ${state.style === l ? 'selected' : ''}>${esc(l)} (${k})</option>`).join('')}</select>` : ''}
      <span class="sep"></span>
      <input type="text" id="q" placeholder="search name, type, artist${all ? ', set' : ''}" value="${esc(state.q || '')}">
      <select id="filter"><option value="">all cards</option>${filters.map(f => `<option ${filt === f ? 'selected' : ''}>${f}</option>`).join('')}</select>
      <span class="sep"></span>
      <span class="muted">${n ? `${n} selected` : 'all cards'}:</span>
      <button data-job="render-plain">render plain</button>
      <button data-job="render-styled" ${st.style ? '' : 'disabled'}>render styled</button>
      <button data-job="enhance">enhance</button>
      <button data-job="restyle" ${st.style ? '' : 'disabled'}>restyle</button>
      <select id="dpi"><option>300</option><option>600</option><option selected>1200</option></select><span class="muted">dpi</span>
      ${n ? '<button id="clearsel" class="small">clear selection</button>' : ''}
    </div>
    <div class="grid"></div>`;
  const grid = () => {
    $('.grid').innerHTML = boardCards().map(tileHtml).join('') || '<div class="empty">nothing matches</div>';
    document.querySelectorAll('.tile').forEach(t => {
      t.onclick = e => {
        const name = t.dataset.name;
        if (e.shiftKey || e.ctrlKey || e.metaKey) { sel.has(name) ? sel.delete(name) : sel.add(name); board(); }
        else { V.fromPage = true; location.hash = viewHash(t.dataset.set, name); }
      };
    });
  };
  grid();
  document.querySelectorAll('[data-mode]').forEach(b => b.onclick = () => { state.mode = b.dataset.mode; board(); });
  document.querySelectorAll('[data-show]').forEach(b => b.onclick = () => { state.show = b.dataset.show; board(); });
  if ($('#style')) $('#style').onchange = e => { state.style = e.target.value; board(); };
  $('#filter').onchange = e => { state.filter = e.target.value; board(); };
  $('#q').oninput = e => { state.q = e.target.value; grid(); };  // the grid alone, so typing keeps its focus
  if ($('#clearsel')) $('#clearsel').onclick = () => { sel.clear(); board(); };
  document.querySelectorAll('[data-job]').forEach(b => b.onclick = () => {
    const dpi = +$('#dpi').value;
    // on the ALL board a job is one submission per set: the selected cards of that set, else all of them
    const groups = all
      ? [...new Set((n ? cards.filter(c => sel.has(c.name)) : st.cards_detail).map(setOf))].map(s => [s, n ? names.filter(nm => cards.some(c => c.name === nm && setOf(c) === s)) : null])
      : [[code, n ? names : null]];
    groups.forEach(([s, list]) => {
      const styled = all ? st.sets.find(x => x.code === s)?.style : st.style;
      const jobs = {
        'render-plain': {kind: 'render', set: s, names: list, styled: false, dpi},
        'render-styled': styled && {kind: 'render', set: s, names: list, styled: true, dpi},
        'enhance': {kind: 'enhance', set: s, names: list, base: 'crop'},
        'restyle': styled && {kind: 'restyle', set: s, names: list},
      };
      if (jobs[b.dataset.job]) submit(jobs[b.dataset.job]);
    });
  });
}

/* --- viewer: one image large, over the page ------------------------------------------ */
/* Two flavours of the same overlay. From a board tile: the board's cards in their shown order
   (search and filter applied), ← → steps card to card. From a compare column: that card's
   images -- crop, every variant, the renders -- and ← → steps image to image, so two renders can
   be flipped between at full size. Either way: wheel / pinch / +− zoom, drag pans, double-click
   toggles 1× and 2.5×, f fullscreen, Esc closes; the URL follows so a view is linkable and back
   works. On the board, s/p/a switch what is shown and c opens compare. */
const viewHash = (code, name) => state.set?.all ? `#/all/view/${code}/${encodeURIComponent(name)}` : `#/set/${code}/view/${encodeURIComponent(name)}`;
const colHash = (code, name, key) => `#/set/${code}/card/${encodeURIComponent(name)}/view/${encodeURIComponent(key)}`;
const V = {open: false, kind: null, fromPage: false, slides: [], i: 0, z: 1, x: 0, y: 0, ptrs: new Map(), pinch: null, drag: null, swipe: null};

/* A slide: {key, path, card (bool: card-shaped), title, sub, what, badges, hash, c}. */
function boardSlides() {
  const cards = boardCards();
  return (cards.length ? cards : state.set.cards_detail).map(c => {
    const s = shown(c);
    return {key: setOf(c) + '/' + c.name, path: s.path, none: s.none, card: !!s.card, what: s.what, c,
            title: c.name, sub: `${setOf(c)} ${c.number ?? ''}${c.card?.type_line ? ' · ' + c.card.type_line : ''}`,
            badges: badges(c), hash: viewHash(setOf(c), c.name)};
  });
}
function columnSlides(c) {
  const code = state.set.code;
  return columns(c).map(x => ({key: x.key, path: x.path, card: x.kind === 'card', what: x.sub, c,
                              title: `${c.name} · ${x.title}`, sub: '', recipe: x.recipe,
                              badges: (x.current ? '<span class="badge accent">current</span>' : '') + (x.isBase ? '<span class="badge accent">base</span>' : ''),
                              hash: colHash(code, c.name, x.key)}));
}
function openViewer(kind, slides, i) {
  V.kind = kind; V.slides = slides; V.i = Math.max(0, i);
  if (!V.open) { V.open = true; V.z = 1; V.x = V.y = 0; document.body.classList.add('viewing'); document.addEventListener('keydown', viewerKeys); }
  $('#viewer').hidden = false;
  drawViewer();
}
function viewer(r) {  // route: a board card
  if (!$('.grid') || V.kind !== 'board') board();
  const slides = boardSlides();
  openViewer('board', slides, slides.findIndex(x => x.c.name === r.name && (!r.inSet || x.c.inSet === r.inSet)));
}
function closeViewer() {
  if (!V.open) return;
  V.open = false; V.kind = null; V.fromPage = false; $('#viewer').hidden = true; $('#viewer').innerHTML = '';
  document.body.classList.remove('viewing'); document.removeEventListener('keydown', viewerKeys);
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
}
function viewerStep(d) {
  const n = V.slides.length; if (!n) return;
  location.replace(V.slides[(V.i + d + n) % n].hash);
}
function viewerPage() {  // where Esc goes
  const c = V.slides[V.i]?.c;
  if (V.kind === 'columns') return `#/set/${state.set.code}/card/${encodeURIComponent(c.name)}`;
  return state.set.all ? '#/all' : `#/set/${state.set.code}`;
}
function viewerKeys(e) {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT' || e.target.tagName === 'TEXTAREA') return;
  const k = e.key, onBoard = V.kind === 'board';
  if (k === 'Escape') { V.fromPage ? history.back() : (location.hash = viewerPage()); }
  else if (k === 'ArrowLeft' || k === 'k') viewerStep(-1);
  else if (k === 'ArrowRight' || k === 'j' || k === ' ') viewerStep(1);
  else if (k === '+' || k === '=') zoomTo(V.z * 1.25);
  else if (k === '-') zoomTo(V.z / 1.25);
  else if (k === '0') zoomTo(1);
  else if (onBoard && (k === 's' || k === 'p')) { state.mode = {s: 'styled', p: 'plain'}[k]; board(); V.slides = boardSlides(); drawViewer(); }
  else if (onBoard && (k === 'a' || k === 'r')) { state.show = {a: 'art', r: 'card'}[k]; board(); V.slides = boardSlides(); drawViewer(); }
  else if (onBoard && k === 'c') { const c = V.slides[V.i].c; location.hash = `#/set/${setOf(c)}/card/${encodeURIComponent(c.name)}`; }
  else if (k === 'f') toggleFull();
  else return;
  e.preventDefault();
}
function toggleFull() {
  const el = $('#viewer');
  document.fullscreenElement ? document.exitFullscreen().catch(() => {}) : el.requestFullscreen?.().catch(() => {});
}
function zoomTo(z, px, py) {
  const stage = $('#vstage'); if (!stage) return;
  const rect = stage.getBoundingClientRect();
  if (px === undefined) { px = rect.width / 2; py = rect.height / 2; }
  z = Math.min(12, Math.max(1, z));
  V.x = px - (px - V.x) * z / V.z; V.y = py - (py - V.y) * z / V.z; V.z = z;
  if (z === 1) V.x = V.y = 0;
  applyZoom();
}
function applyZoom() {
  const im = $('#vimg'); if (!im) return;
  im.style.transform = `translate(${V.x}px, ${V.y}px) scale(${V.z})`;
  $('#vzoom').textContent = V.z.toFixed(2).replace(/\.?0+$/, '') + '×';
  $('#vstage').classList.toggle('zoomed', V.z > 1);
}
function drawViewer() {
  const s = V.slides[V.i]; if (!s) return closeViewer();
  const n = V.slides.length, onBoard = V.kind === 'board', c = s.c, labels = onBoard ? styleLabels(state.set.cards_detail) : [];
  const el = $('#viewer');
  el.innerHTML = `
    <div class="vtop">
      <span class="vtitle"><b>${esc(s.title)}</b> <span class="muted">${esc(s.sub)}</span></span>
      ${onBoard ? `<span class="seg">${['plain', 'styled'].map(m => `<button data-vmode="${m}" class="${state.mode === m ? 'on' : ''}">${m}</button>`).join('')}</span>
      <span class="seg">${['art', 'card'].map(m => `<button data-vshow="${m}" class="${state.show === m ? 'on' : ''}">${m}</button>`).join('')}</span>` : ''}
      ${onBoard && state.mode === 'styled' && labels.length ? `<select id="vstyle"><option value="current">${state.set.all ? "each set's recipe" : 'current recipe'}</option>
        ${labels.map(([l, k]) => `<option value="${esc(l)}" ${state.style === l ? 'selected' : ''}>${esc(l)} (${k})</option>`).join('')}</select>` : ''}
      <span class="spacer"></span>
      <span class="mono muted" id="vzoom">1×</span>
      <button class="small" data-v="out" title="zoom out (−)">−</button><button class="small" data-v="in" title="zoom in (+)">+</button><button class="small" data-v="fit" title="fit (0)">fit</button>
      ${onBoard ? `<a class="pill" href="#/set/${esc(setOf(c))}/card/${encodeURIComponent(c.name)}" title="compare (c)">compare</a>` : ''}
      ${s.path ? `<a class="pill" href="${file(s.path)}" target="_blank" title="the full file in a new tab">open</a>` : ''}
      <button class="small" data-v="full" title="fullscreen (f)">⛶</button>
      <button class="small" data-v="close" title="close (Esc)">✕</button>
    </div>
    <div class="vstage ${s.card ? 'card' : ''}" id="vstage">
      ${s.path ? `<img id="vimg" src="${file(s.path)}" draggable="false" alt="">` : `<div class="none">${esc(s.none || 'no image')}</div>`}
      <button class="vnav prev" data-v="prev" title="previous (←)">‹</button><button class="vnav next" data-v="next" title="next (→)">›</button>
    </div>
    <div class="vbottom">
      <span class="muted mono">${V.i + 1} / ${n}</span>
      <span class="muted">${s.what ? esc(s.what) : ''}</span>
      <span class="badges">${s.badges || ''}</span>
      ${s.recipe ? `<span class="recipe vrecipe">${recipeDiff(s.recipe, c.recipe)}</span>` : ''}
      <span class="spacer"></span>
      <span class="muted">← → ${onBoard ? 'card' : 'image'} · wheel / pinch zoom · drag pan · double-click 2.5×${onBoard ? ' · p s plain/styled · a r art/card · c compare' : ''} · f fullscreen · Esc</span>
    </div>`;
  applyZoom();
  el.querySelectorAll('[data-vmode]').forEach(b => b.onclick = () => { state.mode = b.dataset.vmode; board(); V.slides = boardSlides(); drawViewer(); });
  el.querySelectorAll('[data-vshow]').forEach(b => b.onclick = () => { state.show = b.dataset.vshow; board(); V.slides = boardSlides(); drawViewer(); });
  if ($('#vstyle')) $('#vstyle').onchange = e => { state.style = e.target.value; board(); V.slides = boardSlides(); drawViewer(); };
  el.querySelectorAll('[data-v]').forEach(b => b.onclick = e => {
    e.stopPropagation();
    const a = b.dataset.v;
    if (a === 'prev') viewerStep(-1); else if (a === 'next') viewerStep(1);
    else if (a === 'in') zoomTo(V.z * 1.25); else if (a === 'out') zoomTo(V.z / 1.25); else if (a === 'fit') zoomTo(1);
    else if (a === 'full') toggleFull(); else if (a === 'close') viewerKeys({key: 'Escape', target: b, preventDefault() {}});
  });
  const stage = $('#vstage');
  stage.onwheel = e => { e.preventDefault(); const r = stage.getBoundingClientRect(); zoomTo(V.z * (e.deltaY < 0 ? 1.15 : 1 / 1.15), e.clientX - r.left, e.clientY - r.top); };
  stage.ondblclick = e => { const r = stage.getBoundingClientRect(); zoomTo(V.z > 1 ? 1 : 2.5, e.clientX - r.left, e.clientY - r.top); };
  stage.onpointerdown = e => {
    if (e.target.classList.contains('vnav')) return;
    stage.setPointerCapture(e.pointerId); V.ptrs.set(e.pointerId, {x: e.clientX, y: e.clientY});
    if (V.ptrs.size === 2) { const [a, b] = [...V.ptrs.values()]; V.pinch = {d: Math.hypot(a.x - b.x, a.y - b.y), z: V.z}; V.drag = null; }
    else { V.drag = {x: e.clientX - V.x, y: e.clientY - V.y}; V.swipe = {x: e.clientX, y: e.clientY, t: Date.now()}; }
  };
  stage.onpointermove = e => {
    if (!V.ptrs.has(e.pointerId)) return;
    V.ptrs.set(e.pointerId, {x: e.clientX, y: e.clientY});
    if (V.pinch && V.ptrs.size === 2) {
      const [a, b] = [...V.ptrs.values()], r = stage.getBoundingClientRect();
      const d = Math.hypot(a.x - b.x, a.y - b.y);
      zoomTo(V.pinch.z * d / V.pinch.d, (a.x + b.x) / 2 - r.left, (a.y + b.y) / 2 - r.top);
    } else if (V.drag && V.z > 1) { V.x = e.clientX - V.drag.x; V.y = e.clientY - V.drag.y; applyZoom(); }
  };
  stage.onpointerup = stage.onpointercancel = e => {
    V.ptrs.delete(e.pointerId);
    if (V.ptrs.size < 2) V.pinch = null;
    if (V.swipe && V.z === 1 && e.type === 'pointerup') {
      const dx = e.clientX - V.swipe.x, dy = e.clientY - V.swipe.y;
      if (Math.abs(dx) > 60 && Math.abs(dx) > 2 * Math.abs(dy) && Date.now() - V.swipe.t < 600) viewerStep(dx < 0 ? 1 : -1);
    }
    V.drag = null; V.swipe = null;
  };
  // the neighbours, warmed up
  [-1, 1].forEach(d => { const ns = V.slides[(V.i + d + n) % n]; if (ns?.path) { const im = new Image(); im.src = file(ns.path); } });
}

/* --- compare ---------------------------------------------------------------------- */
function recipeDiff(recipe, ref) {
  if (!recipe) return '';
  const skip = new Set(['base']);
  const keys = Object.keys(recipe).filter(k => !skip.has(k)).sort();
  return keys.map(k => {
    const v = recipe[k], r = ref?.[k];
    const same = JSON.stringify(v) === JSON.stringify(r);
    if (same && !['prompt', 'control', 'denoise', 'seed'].includes(k)) return '';
    const val = typeof v === 'string' && v.length > 70 ? v.slice(0, 70) + '…' : JSON.stringify(v);
    return `<div>${esc(k)}: ${same ? esc(val) : `<i>${esc(val)}</i>`}</div>`;
  }).join('');
}
function columns(c) {
  const cols = [];
  const cur = c.current?.hash;
  if (c.crop) cols.push({key: 'crop', title: 'crop', sub: `${c.card.set.toUpperCase()} ${c.card.collector_number} · ${c.card.artist}`,
                         path: c.crop, kind: 'crop', acts: [['enhance', 'crop'], ['base', 'crop']]});
  const vs = [...(c.variants || [])].sort((a, b) => (a.kind === 'enhance' ? 0 : 1) - (b.kind === 'enhance' ? 0 : 1) || a.label.localeCompare(b.label) || (b.created > a.created ? 1 : -1));
  for (const v of vs) {
    const acts = v.kind === 'restyle' ? [['promote', v.hash], ['enhance', v.hash], ['base', v.hash], ['delete', v.hash]]
                                      : [['base', v.hash], ['delete', v.hash]];
    const base = c.entry.base || state.set.base || 'crop';
    cols.push({key: v.hash, title: v.label, sub: v.hash + (v.hash === cur ? ' · current' : '') + (v.base !== 'crop' ? ` · from ${v.base}` : ''),
               path: v.path, kind: v.kind, recipe: v.recipe, current: v.hash === cur, acts,
               isBase: base === v.hash || (base === v.label && v === c.variants.filter(x => x.kind === 'restyle' && x.label === v.label).sort((a, b) => (b.created || '').localeCompare(a.created || ''))[0])});
  }
  for (const k of ['plain', 'styled']) {
    const r = c.renders?.[k];
    if (r) cols.push({key: 'render-' + k, title: `render · ${k}`, sub: `${r.dpi || '?'} dpi · text ${r.sizes?.text}px${r.shrunk ? ' (shrunk)' : ''}`,
                      path: r.path, kind: 'card', acts: [[k === 'plain' ? 'render-plain' : 'render-styled', ''], ['delete-render', r.file]]});
  }
  return cols;
}
async function card(r) {
  const c = cardOf(r.name);
  const code = state.set.code;
  if (!c) { $('#main').innerHTML = `<div class="empty">no card ${esc(r.name)} in ${esc(code)}</div>`; return; }
  if (c.error) { $('#main').innerHTML = `<h1>${esc(c.name)}</h1><div class="empty bad">${esc(c.error)}</div>`; return; }
  const cols = columns(c);
  const ab = state.ab;
  const find = k => cols.find(x => x.key === k);
  const A = find(ab.a), B = find(ab.b);
  $('#main').innerHTML = `
    <div class="cardhead">
      <div><h1>${esc(c.name)} <span class="muted mono">${c.number ?? ''}</span></h1>
        <div class="kv">
          <span>type</span><span>${esc(c.card.type_line)}</span>
          <span>printing</span><span class="printing"><button class="small" id="printing" title="which Scryfall printing's art this card starts from">
            ${c.entry.printing ? esc(c.entry.printing.toUpperCase()) : `${esc(c.card.set.toUpperCase())} ${esc(c.card.collector_number)} · default`} ▾</button>
            <span class="muted" id="printing-n"></span><div class="printings" id="printings" hidden></div></span>
          <span>restyle base</span><span><span class="badge">${esc(c.entry.base || state.set.base || 'crop')}</span>${!c.entry.base && state.set.base ? ' <span class="muted">(set-wide)</span>' : ''} ${c.entry.base ? '<button class="small" id="basecrop">use set default</button>' : ''}
            <select id="setbase" title="set-wide base: every card starts its restyle from this"><option value="">set-wide: crop</option>${styleLabels(state.set.cards_detail).filter(([l]) => l !== state.set.style?.name).map(([l, k]) => `<option value="${esc(l)}" ${state.set.base === l ? 'selected' : ''}>set-wide: ${esc(l)} (${k})</option>`).join('')}</select></span>
          <span>subject</span><span><input type="text" id="subject" value="${esc(c.entry.subject || '')}" placeholder="this card's own words, ahead of the style prompt: who is in it, the pose, the scene"></span>
          <span>seed</span><span><input type="number" id="seed" value="${c.entry.seed ?? ''}" placeholder="derived: ${c.recipe?.seed ?? '-'}" style="width:9em" title="the number the picture is generated from; same seed + same recipe = same picture. Empty = a fixed value derived from the set, so it is reproducible. Pin a number (or roll one) to explore other takes.">
            <button class="small" id="roll" title="put a random seed here (then generate)">🎲</button>${c.entry.seed != null ? ' <button class="small" id="unpin" title="back to the derived, reproducible seed">unpin</button>' : ''}</span>
          <span>remix</span><span><select id="remix" title="what the next restyle keeps of the base image">
            <option value="">style's (${state.set.style?.remix || 'restyle'})</option>
            ${Object.entries(REMIX).map(([m, d]) => `<option value="${m}" ${c.entry.remix === m ? 'selected' : ''}>${m} · ${d}</option>`).join('')}</select></span>
          ${(c.warnings || []).map(w => `<span>warning</span><span class="warn">${esc(w)}</span>`).join('')}
        </div></div>
      <div><div class="muted" style="font-size:.85em">current recipe ${c.style_hash ? `<span class="mono">${c.style_hash}</span>` : '(no style)'}</div>
        <div class="recipe mono" style="font-size:.78em;max-width:520px;color:var(--ink-2)">${c.recipe ? esc(c.recipe.prompt) : ''}</div></div>
      <div class="row" style="margin-left:auto"><a class="pill" href="#/set/${esc(code)}">← ${esc(code)}</a><a class="pill" href="#/set/${esc(code)}/lab">lab</a></div>
    </div>
    <div class="toolbar" title="jobs for this card; a restyle starts from the base shown above">
      <span class="muted">this card:</span>
      <button data-cjob="restyle" ${state.set.style ? '' : 'disabled'} title="generate: the base, subject and remix mode above, in the set's style">${esc(c.entry.remix || state.set.style?.remix || 'restyle')}</button>
      <button data-cjob="another" ${state.set.style ? '' : 'disabled'} title="the same, but with a fresh random seed — a different take you can compare, then pin or promote if you like it">another take</button>
      <span class="sep"></span>
      <button data-cjob="enhance">enhance</button>
      <button data-cjob="render-plain">render plain</button>
      <button data-cjob="render-styled" ${state.set.style ? '' : 'disabled'}>render styled</button>
    </div>
    ${A && B ? abPanel(A, B) : `<p class="muted">Pick <b>A</b> and <b>B</b> on two images to wipe between them.</p>`}
    <div class="cols">${cols.map(x => `
      <div class="col ${x.current ? 'current' : ''} ${ab.a === x.key ? 'isA' : ''} ${ab.b === x.key ? 'isB' : ''}" data-key="${esc(x.key)}">
        <div class="pic ${x.kind === 'card' ? 'card' : ''}" data-open="${esc(x.path)}"><img loading="lazy" src="${img(x.path, 640)}">
          <div class="ab"><b data-ab="a">A</b><b data-ab="b">B</b></div></div>
        <div class="title"><span>${esc(x.title)}${x.isBase ? ' <span class="badge accent">base</span>' : ''}</span><small>${esc(x.sub)}</small></div>
        ${x.recipe ? `<div class="recipe">${recipeDiff(x.recipe, c.recipe)}</div>` : ''}
        <div class="acts">${x.acts.map(([a, arg]) => `<button class="small" data-act="${a}" data-arg="${esc(arg)}">${
          {enhance: 'enhance', base: 'use as base', promote: 'use recipe for set',
           'render-plain': 're-render', 'render-styled': 're-render', delete: 'delete', 'delete-render': 'delete'}[a]}</button>`).join('')}</div>
      </div>`).join('')}
    </div>`;
  const put = body => api(`/api/sets/${code}/cards/${encodeURIComponent(c.name)}`, {method: 'PUT', body}).then(() => refresh()).catch(e => toast(e.message, true));
  // printings: a grid of art crops, each fetched from Scryfall the first time it is shown
  const cardUrl = `/api/sets/${code}/cards/${encodeURIComponent(c.name)}`;
  api(`${cardUrl}/printings`).then(ps => {
    const box = $('#printings'); if (!box) return;
    $('#printing-n').textContent = ps.length < 2 ? 'one printing on file — `mint cards --kind default_cards` fetches them all' : `${ps.length} printings`;
    const d = ps.find(p => p.default);
    const tile = (p, key, head, note, on) => `<div class="p ${on ? 'on' : ''} ${p.penalty >= 100 ? 'unusable' : ''}" data-p="${key}" title="${esc(p.set_name || '')}">
        <div class="pic">${p.illustration_id ? `<img loading="lazy" src="${cardUrl}/printings/${p.set}:${encodeURIComponent(p.collector_number)}/crop?w=320" alt="">` : '<span class="none">no art</span>'}</div>
        <div class="cap"><b>${head}</b> <span class="muted">${esc(p.artist || '')}</span><small>${esc(note)}</small></div></div>`;
    const note = p => [p.released_at?.slice(0, 4), ...(p.odd || [])].filter(Boolean).join(' · ');
    box.innerHTML = (d ? tile(d, '', `default → ${d.set.toUpperCase()} ${d.collector_number}`, 'the newest plain printing; follows the card file', !c.entry.printing) : '') +
      ps.map(p => tile(p, `${p.set}:${p.collector_number}`, `${p.set.toUpperCase()} ${p.collector_number}`, note(p), p.selected)).join('');
    box.querySelectorAll('.p').forEach(el => el.onclick = () => { box.hidden = true; put({printing: el.dataset.p || null}); });
  }).catch(e => toast(e.message, true));
  $('#printing').onclick = e => { e.stopPropagation(); const box = $('#printings'); box.hidden = !box.hidden; };
  $('#printings').onclick = e => e.stopPropagation();
  document.onclick = () => { const box = $('#printings'); if (box) box.hidden = true; };  // anywhere else closes it
  document.onkeydown = e => { if (e.key === 'Escape' && $('#printings') && !$('#printings').hidden) { $('#printings').hidden = true; e.preventDefault(); } };
  $('#subject').onchange = e => put({subject: e.target.value || null});
  $('#seed').onchange = e => put({seed: e.target.value === '' ? null : +e.target.value});
  $('#remix').onchange = e => put({remix: e.target.value || null});
  if ($('#unpin')) $('#unpin').onclick = () => put({seed: null});
  $('#roll').onclick = () => put({seed: 1 + Math.floor(Math.random() * 2 ** 31)});
  if ($('#basecrop')) $('#basecrop').onclick = () => put({base: null});
  $('#setbase').onchange = e => api(`/api/sets/${code}/base`, {method: 'PUT', body: {base: e.target.value || null}}).then(() => { toast(e.target.value ? `every ${code} restyle now starts from its ${e.target.value}` : 'restyles start from the crop'); refresh(); }).catch(e => toast(e.message, true));
  document.querySelectorAll('[data-ab]').forEach(b => b.onclick = e => {
    e.stopPropagation(); const key = b.closest('.col').dataset.key;
    ab[b.dataset.ab] = ab[b.dataset.ab] === key ? null : key; card(r);
  });
  document.querySelectorAll('[data-cjob]').forEach(b => b.onclick = () => {
    const j = b.dataset.cjob, names = [c.name];
    if (j === 'restyle') submit({kind: 'restyle', set: code, names});
    else if (j === 'another') { const seed = 1 + Math.floor(Math.random() * 2 ** 31); put({seed}).then(() => submit({kind: 'restyle', set: code, names})); }
    else if (j === 'enhance') submit({kind: 'enhance', set: code, names, base: c.entry.base || state.set.base || 'crop'});
    else if (j === 'render-plain') submit({kind: 'render', set: code, names, styled: false, dpi: 1200});
    else if (j === 'render-styled') submit({kind: 'render', set: code, names, styled: true, dpi: 1200});
  });
  document.querySelectorAll('.col [data-open]').forEach(p => p.onclick = () => { V.fromPage = true; location.hash = colHash(code, c.name, p.closest('.col').dataset.key); });
  if (r.key) { const slides = columnSlides(c); openViewer('columns', slides, slides.findIndex(x => x.key === r.key)); }
  document.querySelectorAll('[data-act]').forEach(b => b.onclick = async () => {
    const act = b.dataset.act, arg = b.dataset.arg, names = [c.name];
    if (act === 'enhance') submit({kind: 'enhance', set: code, names, base: arg});
    else if (act === 'base') put({base: arg === 'crop' ? null : arg});
    else if (act === 'delete-render') {
      if (!confirm(`Delete the render ${arg}? The PNG is removed from out/${code.toLowerCase()}/; re-render makes it again.`)) return;
      api(`/api/sets/${code}/renders/${encodeURIComponent(arg)}`, {method: 'DELETE'}).then(() => { toast(`deleted ${arg}`); refresh(); }).catch(e => toast(e.message, true));
    }
    else if (act === 'delete') {
      const v = c.variants.find(x => x.hash === arg);
      if (!confirm(`Delete ${v.label}-${arg}${v.hash === c.current?.hash ? ' (the current variant)' : ''}? The file is removed; a restyle makes it again.`)) return;
      api(`/api/sets/${code}/cards/${encodeURIComponent(c.name)}/variants/${arg}`, {method: 'DELETE'}).then(() => { toast(`deleted ${v.label}-${arg}`); refresh(); }).catch(e => toast(e.message, true));
    }
    else if (act === 'promote') api(`/api/sets/${code}/promote`, {method: 'POST', body: {name: c.name, hash: arg}}).then(() => { toast('set style updated'); refresh(); }).catch(e => toast(e.message, true));
    else if (act === 'render-plain') submit({kind: 'render', set: code, names, styled: false, dpi: 1200});
    else if (act === 'render-styled') submit({kind: 'render', set: code, names, styled: true, dpi: 1200});
  });
  bindAB(A, B, r);
}
function abPanel(A, B) {
  const ab = state.ab, cardish = A.kind === 'card' || B.kind === 'card';
  const [L, R] = ab.blind && ab.swap ? [B, A] : [A, B];
  const t = `translate(${ab.x}px, ${ab.y}px) scale(${ab.zoom})`;
  return `<div class="ab-panel">
    <div class="toolbar">
      <span class="muted">wipe</span><input type="range" id="wipe" min="0" max="100" value="${ab.wipe}">
      <span class="muted">zoom</span><input type="range" id="zoom" min="1" max="8" step="0.25" value="${ab.zoom}"><span class="mono" id="zoomv">${ab.zoom}×</span>
      <button class="small" id="fit">fit</button>
      <label><input type="checkbox" id="blind" ${ab.blind ? 'checked' : ''}> blind</label>
      ${ab.blind ? '<button class="small" id="reveal">reveal</button>' : ''}
      <span class="muted">drag to pan · wheel to zoom</span>
    </div>
    <div class="stage ${cardish ? 'card' : ''}" id="stage">
      <img src="${file(R.path)}" style="transform:${t}">
      <div class="clip" id="clip" style="clip-path: inset(0 ${100 - ab.wipe}% 0 0)"><img src="${file(L.path)}" style="transform:${t}"></div>
      <div class="split" style="left:${ab.wipe}%"></div>
      ${ab.blind ? '<span class="tag a">?</span><span class="tag b">?</span>' : `<span class="tag a">A · ${esc(A.title)} ${esc(short(A.sub))}</span><span class="tag b">B · ${esc(B.title)} ${esc(short(B.sub))}</span>`}
    </div></div>`;
}
function bindAB(A, B, r) {
  if (!A || !B) return;
  const ab = state.ab, stage = $('#stage');
  const apply = () => {
    const t = `translate(${ab.x}px, ${ab.y}px) scale(${ab.zoom})`;
    stage.querySelectorAll('img').forEach(i => i.style.transform = t);
    $('#clip').style.clipPath = `inset(0 ${100 - ab.wipe}% 0 0)`; $('.split', stage).style.left = ab.wipe + '%'; $('#zoomv').textContent = ab.zoom + '×';
  };
  $('#wipe').oninput = e => { ab.wipe = +e.target.value; apply(); };
  $('#zoom').oninput = e => { ab.zoom = +e.target.value; apply(); };
  $('#fit').onclick = () => { ab.zoom = 1; ab.x = ab.y = 0; $('#zoom').value = 1; apply(); };
  $('#blind').onchange = e => { ab.blind = e.target.checked; ab.swap = Math.random() < 0.5; card(r); };
  if ($('#reveal')) $('#reveal').onclick = () => { toast(`left was ${ab.swap ? 'B' : 'A'}: ${(ab.swap ? B : A).title} ${(ab.swap ? B : A).sub}`); ab.blind = false; card(r); };
  let drag = null;
  stage.onpointerdown = e => { drag = {x: e.clientX - ab.x, y: e.clientY - ab.y}; stage.setPointerCapture(e.pointerId); };
  stage.onpointermove = e => { if (drag) { ab.x = e.clientX - drag.x; ab.y = e.clientY - drag.y; apply(); } };
  stage.onpointerup = stage.onpointercancel = () => { drag = null; };
  stage.onwheel = e => {
    e.preventDefault();
    const rect = stage.getBoundingClientRect(), px = e.clientX - rect.left, py = e.clientY - rect.top;
    const z = Math.min(8, Math.max(1, ab.zoom * (e.deltaY < 0 ? 1.15 : 1 / 1.15)));
    ab.x = px - (px - ab.x) * z / ab.zoom; ab.y = py - (py - ab.y) * z / ab.zoom; ab.zoom = +z.toFixed(2);
    if (ab.zoom === 1) { ab.x = ab.y = 0; } $('#zoom').value = ab.zoom; apply();
  };
}

/* --- recipe lab -------------------------------------------------------------------- */
function lab() {
  const st = state.set, code = st.code, fields = state.ws.style_fields;
  const base = st.style || {name: 'lab', prompt: ''};
  if (!state.lab || state.lab.code !== code) state.lab = {code, values: {...base}, probes: st.cards_detail.slice(0, 3).map(c => c.name), label: (base.name || 'lab') + '-lab'};
  const L = state.lab;
  const changed = f => JSON.stringify(L.values[f.name] ?? f.default) !== JSON.stringify(base[f.name] ?? f.default);
  const probes = st.cards_detail.filter(c => L.probes.includes(c.name));
  const labels = new Map();  // label-hash -> {label, hash, recipe} across probe cards, newest first
  for (const c of probes) for (const v of c.variants || []) if (v.kind === 'restyle') { const k = v.label + '-' + v.hash; if (!labels.has(k)) labels.set(k, v); }
  const cols = [...labels.values()].sort((a, b) => ((b.label === base.name) - (a.label === base.name)) || (b.created > a.created ? 1 : -1)).slice(0, 8);
  $('#main').innerHTML = `
    <div class="row"><h1>${esc(code)} <span class="muted">recipe lab</span></h1><a class="pill" href="#/set/${esc(code)}">← ${esc(code)}</a></div>
    <div class="lab">
      <div>
        <div class="form">
          ${styleForm(fields, L.values, changed)}
          <label>run as</label><input type="text" id="label" value="${esc(L.label)}" title="the label the variants get; the set's style name keeps them comparable side by side">
          <label>probe cards</label><div class="probe">${st.cards_detail.map(c => `<label class="${L.probes.includes(c.name) ? 'on' : ''}" data-probe="${esc(c.name)}">${esc(c.name)}</label>`).join('')}</div>
          <label></label><div class="row">
            <button class="primary" id="run">run on ${probes.length} card(s)</button>
            <label><input type="checkbox" id="upscale" checked> ESRGAN pass</label>
            <button id="save" title="write these values into the set file as its style">save as set style</button>
            <button id="reset" class="small">reset to set</button></div>
        </div>
        <p class="muted" style="font-size:.85em">Changed knobs are highlighted. A run makes one variant per probe card under the label; variants that match the set's current recipe are marked current. "Use recipe for set" on a variant (in the card view) promotes it.</p>
      </div>
      <div>
        <div class="labgrid" style="grid-template-columns: 120px repeat(${cols.length}, minmax(140px, 1fr))">
          <div class="head"></div>${cols.map(v => `<div class="head"><b>${esc(v.label)}</b> <span class="mono">${v.hash}</span><div class="mono muted" style="font-size:.85em">${esc(labSummary(v.recipe, st))}</div></div>`).join('')}
          ${probes.map(c => `<div class="head">${esc(c.name)}</div>${cols.map(v => {
            const mine = (c.variants || []).find(x => x.label === v.label && sameKnobs(x.recipe, v.recipe));
            return `<div class="cell">${mine ? `<img loading="lazy" src="${img(mine.path, 320)}" data-open="${esc(mine.path)}"><div class="cap"><span>${mine.hash}${c.current?.hash === mine.hash ? ' · current' : ''}</span><button class="small" data-promote="${esc(c.name)}|${mine.hash}">use for set</button></div>` : '<div class="cap muted">—</div>'}</div>`;
          }).join('')}`).join('')}
        </div>
        ${cols.length ? '' : '<div class="empty">no restyle variants for the probe cards yet — run one</div>'}
      </div>
    </div>`;
  bindStyleForm(fields, L.values, () => lab());
  $('#label').onchange = e => { L.label = e.target.value; };
  document.querySelectorAll('[data-probe]').forEach(el => el.onclick = () => { const n = el.dataset.probe; L.probes = L.probes.includes(n) ? L.probes.filter(x => x !== n) : [...L.probes, n]; lab(); });
  $('#reset').onclick = () => { L.values = {...base}; lab(); };
  $('#run').onclick = () => {
    const over = {}; for (const f of fields) if (f.name !== 'name' && changed(f)) over[f.name] = L.values[f.name];
    if (!st.style) over.prompt = L.values.prompt || '';
    submit({kind: 'restyle', set: code, names: L.probes, style: over, label: L.label || undefined, upscale: $('#upscale').checked});
  };
  $('#save').onclick = () => {
    const body = {}; for (const f of fields) if (f.name !== 'name' && changed(f) || ['prompt'].includes(f.name)) body[f.name] = L.values[f.name];
    const style = {...(st.style || {}), ...body, name: st.style?.name || L.label.replace(/-lab$/, '') || 'style'};
    api(`/api/sets/${code}/style`, {method: 'PUT', body: style}).then(() => { toast('set style saved'); refresh(); }).catch(e => toast(e.message, true));
  };
  document.querySelectorAll('[data-open]').forEach(p => p.onclick = () => window.open(file(p.dataset.open), '_blank'));
  document.querySelectorAll('[data-promote]').forEach(b => b.onclick = () => {
    const [name, hash] = b.dataset.promote.split('|');
    api(`/api/sets/${code}/promote`, {method: 'POST', body: {name, hash}}).then(() => { toast('set style updated'); refresh(); }).catch(e => toast(e.message, true));
  });
}
const KNOBS = ['control', 'control_strength', 'control_end', 'denoise', 'steps', 'cfg', 'sampler', 'scheduler', 'checkpoint', 'controlnet', 'loras', 'width', 'height', 'grayscale_source', 'negative'];
function sameKnobs(a, b) { return KNOBS.every(k => JSON.stringify(a?.[k]) === JSON.stringify(b?.[k])) && stripSubject(a?.prompt) === stripSubject(b?.prompt); }
function stripSubject(p) { return (p || '').split(', ').slice(-1)[0]; }
function labSummary(recipe, st) {
  const ref = st.style || {};
  const diff = KNOBS.filter(k => JSON.stringify(recipe[k]) !== JSON.stringify(ref[k]) && recipe[k] !== undefined && k !== 'negative');
  const show = diff.slice(0, 4).map(k => `${k} ${JSON.stringify(recipe[k])}`);
  if (diff.length > 4) show.push(`+${diff.length - 4} more`);
  if (stripSubject(recipe.prompt) !== stripSubject(ref.prompt)) show.unshift('prompt differs');
  return show.join(' · ') || 'set recipe';
}

/* --- frame tools -------------------------------------------------------------------- */
function frame() {
  const st = state.set, code = st.code, F = state.frame;
  if (F.code !== code) { Object.assign(F, {code, name: st.cards_detail[0]?.name, css: st.css, opacity: 50, scan: null}); }
  const c = cardOf(F.name);
  const proof = c?.renders?.proof, themes = c?.renders?.themes || [];
  $('#main').innerHTML = `
    <div class="row"><h1>${esc(code)} <span class="muted">frame</span></h1><a class="pill" href="#/set/${esc(code)}">← ${esc(code)}</a>
      <select id="fcard">${st.cards_detail.map(x => `<option ${x.name === F.name ? 'selected' : ''}>${esc(x.name)}</option>`).join('')}</select></div>
    <div class="frame-tools">
      <div class="panel">
        <h2>set css <span class="muted mono" style="text-transform:none">${esc(code.toLowerCase())}.css</span></h2>
        <textarea class="css" id="css">${esc(F.css)}</textarea>
        <div class="toolbar"><button class="primary" id="savecss">save</button><button id="proof">save &amp; render proof (300 dpi)</button>
          <span class="muted">injected after the frame's own rules; a proof renders into out/${esc(code.toLowerCase())}/proof/</span></div>
        ${proof ? `<div class="row"><img src="${img(proof.path, 640)}" style="max-width:340px;border-radius:3px" data-open="${esc(proof.path)}"><div class="muted">${esc(proof.file)}<br>text ${proof.sizes?.text}px · name ${proof.sizes?.name}px<br>${new Date(proof.rendered_at).toLocaleString()}</div></div>` : '<div class="muted">no proof yet</div>'}
      </div>
      <div class="panel">
        <h2>calibration overlay</h2>
        <div class="toolbar"><button id="getscan">${F.scan ? 'refresh scan' : "fetch Scryfall's scan"}</button>
          <span class="muted">ours</span><input type="range" id="op" min="0" max="100" value="${F.opacity}"><span class="muted">scan</span></div>
        ${F.scan && (proof || c?.renders?.plain) ? `<div class="overlay"><img class="scan" src="${file(F.scan)}"><img class="ours" id="ours" src="${file((proof || c.renders.plain).path)}" style="opacity:${1 - F.opacity / 100}"></div>` :
          `<div class="empty">${F.scan ? 'render a proof (or a plain render) of this card to overlay' : 'fetch the scan, and render a proof, to compare text placement'}</div>`}
      </div>
      <div class="panel" style="grid-column: 1 / -1">
        <h2>themes</h2>
        <div class="toolbar"><button id="themes">render every theme for ${esc(F.name || '')}</button><span class="muted">${state.ws.themes.join(' · ')}</span></div>
        <div class="themes">${themes.map(t => `<div class="t"><img loading="lazy" src="${img(t.path, 320)}" data-open="${esc(t.path)}"><div class="cap">${esc(t.theme)}</div></div>`).join('')}</div>
      </div>
    </div>`;
  $('#fcard').onchange = e => { F.name = e.target.value; frame(); };
  const saveCss = () => api(`/api/sets/${code}/css`, {method: 'PUT', body: {css: $('#css').value}}).then(() => { F.css = $('#css').value; st.css = F.css; toast('css saved'); });
  $('#savecss').onclick = () => saveCss().catch(e => toast(e.message, true));
  $('#proof').onclick = () => saveCss().then(() => submit({kind: 'render', set: code, names: [F.name], styled: false, dpi: 300, sub: 'proof'})).catch(e => toast(e.message, true));
  $('#themes').onclick = () => submit({kind: 'themes', set: code, names: [F.name]});
  $('#getscan').onclick = () => api(`/api/sets/${code}/cards/${encodeURIComponent(F.name)}/scan`, {method: 'POST'}).then(d => { F.scan = d.path; frame(); }).catch(e => toast(e.message, true));
  $('#op').oninput = e => { F.opacity = +e.target.value; const o = $('#ours'); if (o) o.style.opacity = 1 - F.opacity / 100; };
  document.querySelectorAll('[data-open]').forEach(p => p.onclick = () => window.open(file(p.dataset.open), '_blank'));
}

/* --- style form: one input per Style field, shared by the lab, the set editor and the styles page --- */
const FIELD_HELP = {
  prompt: 'the medium, palette and mood; a card\'s subject goes ahead of it', negative: 'what the sampler steers away from',
  control: 'which ControlNet reads the base image', control_strength: 'how hard the control holds the base\'s structure (0-1)',
  control_end: 'the fraction of the steps the control is on for (0-1)', denoise: 'how much of the base is redrawn (0-1)',
  steps: 'sampling steps', cfg: 'prompt strength', seed: 'the set seed; each card\'s comes from it by the rule',
  seed_rule: 'stable: from the illustration id, so adding a card moves no other; position: seed*1000+index',
  sampler: 'ComfyUI sampler name', scheduler: 'ComfyUI scheduler name', checkpoint: 'the SDXL checkpoint file',
  controlnet: 'the ControlNet model file', upscaler: 'the ESRGAN model file', loras: 'JSON: [{"name": "x.safetensors", "strength": 0.7}]',
  width: 'generation width', height: 'generation height', grayscale_source: 'desaturate the base first (for ink styles)',
  refine: 'a second pass at refine_scale x the size with this denoise; 0 = off', refine_scale: '1-3',
  clip_skip: '1 = the checkpoint\'s CLIP; 2 for Pony-family checkpoints', remix: 'restyle: redraw the base; repose: new picture on its layout; new: from the prompt alone',
};
function fieldInput(f, v) {
  if (f.choices) return `<select data-f="${f.name}">${f.choices.map(c => `<option ${v === c ? 'selected' : ''}>${c}</option>`).join('')}</select>`;
  if (f.type === 'bool') return `<input type="checkbox" data-f="${f.name}" ${v ? 'checked' : ''}>`;
  if (f.type === 'list') return `<input type="text" data-f="${f.name}" value="${esc(JSON.stringify(v || []))}" placeholder='[{"name": "x.safetensors", "strength": 0.7}]'>`;
  if (f.name === 'prompt' || f.name === 'negative') return `<textarea data-f="${f.name}">${esc(v ?? '')}</textarea>`;
  if (f.type === 'int' || f.type === 'float') return `<input type="number" data-f="${f.name}" value="${esc(v ?? '')}" step="${f.type === 'int' ? 1 : 0.05}">`;
  return `<input type="text" data-f="${f.name}" value="${esc(v ?? '')}">`;
}
/* The value an input holds, typed as its field is; undefined when it cannot be read (a toast says why). */
function fieldValue(f, el) {
  let v = el.type === 'checkbox' ? el.checked : el.value;
  if (f.type === 'int') v = parseInt(v, 10); else if (f.type === 'float') v = parseFloat(v);
  else if (f.type === 'list') { try { v = JSON.parse(v || '[]'); } catch { toast('loras must be JSON', true); return undefined; } }
  if ((f.type === 'int' || f.type === 'float') && Number.isNaN(v)) { toast(`${f.name} must be a number`, true); return undefined; }
  return v;
}
/* The form's rows: every field but name; a label is lit when `lit(f)` says so. */
function styleForm(fields, values, lit) {
  return fields.filter(f => f.name !== 'name').map(f =>
    `<label class="${lit(f) ? 'changed' : ''}" title="${esc(FIELD_HELP[f.name] || '')}">${esc(f.name)}</label>${fieldInput(f, values[f.name] ?? f.default ?? '')}`).join('');
}
/* Wire the form: each change goes through fieldValue into `values`, then `after()`. */
function bindStyleForm(fields, values, after) {
  document.querySelectorAll('[data-f]').forEach(el => el.onchange = () => {
    const f = fields.find(x => x.name === el.dataset.f), v = fieldValue(f, el);
    if (v === undefined) return;
    values[f.name] = v; after(f);
  });
}
/* A style block as a file would hold it: the prompt, every knob off its default, and the keys in
   `keep` (what the file spelled out before), so saving never bloats a file nor loses a spelled-out default. */
function slimStyle(fields, values, keep = []) {
  const out = {};
  for (const f of fields) {
    if (f.name === 'name' || values[f.name] === undefined) continue;
    if (f.name === 'prompt' || keep.includes(f.name) || JSON.stringify(values[f.name]) !== JSON.stringify(f.default)) out[f.name] = values[f.name];
  }
  return out;
}

/* --- new set (on the home page) --------------------------------------------------------------- */
async function newSetForm() {
  const box = $('#newset-form'); if (!box) return;
  box.hidden = !box.hidden;
  if (box.hidden) return;
  const templates = await api('/api/styles').catch(() => []);
  box.innerHTML = `<h2>new set</h2>
    <div class="form">
      <label>code</label><input type="text" id="ns-code" placeholder="SAT" style="width:8em" title="letters and digits; the file is sets/<code>.json and renders go to out/<code>/">
      <label>name</label><input type="text" id="ns-name" placeholder="Satoru, forgot his ninjas at home">
      <label>style</label><select id="ns-style"><option value="">none — add one later</option>${templates.map(t => `<option value="${esc(t.name)}">${esc(t.name)}${t.builtin ? ' (built-in)' : ''}${t.private ? ' (private)' : ''}</option>`).join('')}</select>
      <label>private</label><span><input type="checkbox" id="ns-private"> <span class="muted">sets/private/, which git ignores</span></span>
      <label>cards</label><textarea id="ns-deck" rows="8" placeholder="a decklist: '1 Card Name' per line, commander(s) after a blank line — or just names, one per line"></textarea>
      <label></label><div class="row"><button class="primary" id="ns-go">create</button><button id="ns-cancel">cancel</button></div>
    </div>`;
  $('#ns-cancel').onclick = () => { box.hidden = true; };
  $('#ns-go').onclick = () => {
    const body = {code: $('#ns-code').value.trim(), name: $('#ns-name').value.trim(), style: $('#ns-style').value || null,
                  private: $('#ns-private').checked, decklist: $('#ns-deck').value};
    if (!body.code) { toast('a set needs a code', true); return; }
    api('/api/sets', {method: 'POST', body}).then(d => { toast(`${d.code}: ${d.cards_detail.length} cards`); state.ws = null; location.hash = `#/set/${d.code}/edit`; })
      .catch(e => toast(e.message, true));
  };
  $('#ns-code').focus();
}

/* --- set editor: the file's own fields, its style block, and the card list ------------------------ */
function edit() {
  const st = state.set, code = st.code, fields = state.ws.style_fields;
  if (st.all) { location.hash = '#/all'; return; }
  let E = state.edit;
  if (!E || E.code !== code) E = state.edit = {code, knobs: false, values: null, styles: null};
  if (!E.styles) api('/api/styles').then(l => { E.styles = l; if (route().view === 'edit') edit(); }).catch(() => { E.styles = []; });
  const labels = styleLabels(st.cards_detail);
  const baseOpts = ['crop', ...labels.map(([l]) => l), ...(st.base && st.base !== 'crop' && !labels.some(([l]) => l === st.base) ? [st.base] : [])];
  const entryOf = c => c.entry || {};
  const remixOpts = c => `<option value="">style's (${esc(st.style?.remix || 'restyle')})</option>` +
    Object.keys(REMIX).map(m => `<option value="${m}" ${entryOf(c).remix === m ? 'selected' : ''}>${m}</option>`).join('');
  $('#main').innerHTML = `
    <div class="row"><h1>${esc(code)} <span class="muted">edit</span></h1>
      <a class="pill" href="#/set/${esc(code)}">← ${esc(code)}</a><a class="pill" href="#/set/${esc(code)}/lab">recipe lab</a><a class="pill" href="#/set/${esc(code)}/frame">frame</a>
      <span class="muted mono">${esc(st.path)}</span></div>
    <div class="editor">
      <div class="panel">
        <h2>set</h2>
        <div class="form meta">
          <label title="the file keeps its name; renders move to out/<new code>/">code</label><input type="text" data-s="code" value="${esc(st.code)}" style="width:8em">
          <label>name</label><input type="text" data-s="name" value="${esc(st.name)}">
          <label title="how many cards the set is meant to have (informational)">size</label><input type="number" data-s="size" value="${st.size ?? ''}" style="width:6em">
          <label title="what every restyle starts from unless a card says otherwise">base</label><select data-s="base">${baseOpts.map(b => `<option value="${b === 'crop' ? '' : esc(b)}" ${(st.base || 'crop') === b ? 'selected' : ''}>${esc(b)}</option>`).join('')}</select>
          <label title="a CSS filter for --styled renders when no restyle exists, e.g. saturate(1.4)">art_filter</label><input type="text" data-s="art_filter" value="${esc(st.art_filter || '')}" placeholder="none">
          <label>note</label><input type="text" data-s="note" value="${esc(st.note || '')}" placeholder="anything worth remembering about this set">
        </div>
      </div>
      <div class="panel">
        <h2>style ${st.style ? `<span class="muted mono" style="text-transform:none">${esc(st.style.name)}</span>` : '<span class="muted" style="text-transform:none">none</span>'}</h2>
        <div class="toolbar">
          ${st.style ? `<button id="knobs">${E.knobs ? 'hide knobs' : 'edit knobs'}</button>
            <button id="savetpl" title="write this style block (and the set's css) to styles/ for other sets">save as template…</button>
            <button id="dropstyle" title="remove the style block; the variants it made stay in the art cache">remove style</button><span class="sep"></span>` : ''}
          <span class="muted">${st.style ? 'replace with' : 'start from'} template</span>
          <select id="tpl">${(E.styles || []).map(t => `<option value="${esc(t.name)}" ${t.name === st.style?.name ? 'selected' : ''}>${esc(t.name)}${t.builtin ? ' (built-in)' : ''}${t.private ? ' (private)' : ''}${t.sets.length ? ' · ' + t.sets.join(' ') : ''}</option>`).join('')}</select>
          <label title="the template's .css becomes the set's, replacing ${esc(code.toLowerCase())}.css"><input type="checkbox" id="tplcss" ${st.css ? '' : 'checked'}> its css too</label>
          <button id="applytpl" ${E.styles?.length ? '' : 'disabled'}>apply</button>
        </div>
        ${st.style && E.knobs ? `<div class="form">${styleForm(fields, E.values, f => JSON.stringify(E.values[f.name] ?? f.default) !== JSON.stringify(st.style[f.name] ?? f.default))}
          <label></label><div class="row"><button class="primary" id="saveknobs">save style</button><button id="resetknobs" class="small">reset</button>
            <span class="muted">changed knobs are lit; saving gives every card a new recipe hash</span></div></div>` : ''}
      </div>
      <div class="panel">
        <h2>cards <span class="muted" style="text-transform:none">${st.cards_detail.length}</span></h2>
        <div class="tablewrap"><table class="cards">
          <thead><tr><th title="collector number">#</th><th>card</th><th title="what the picture is of; goes ahead of the style prompt">subject</th><th title="replaces the printed flavor text">flavor</th>
            <th title="your own image instead of Scryfall's: a path under the workspace">art</th><th title="per-card CSS filter for --styled">art_filter</th><th title="pin this card's seed">seed</th><th title="what a restyle keeps of the base">remix</th><th>printing · base</th><th></th></tr></thead>
          <tbody>${st.cards_detail.map((c, i) => `<tr data-name="${esc(c.name)}">
            <td><input type="number" class="num" data-k="number" value="${entryOf(c).number ?? ''}"></td>
            <td class="who"><a href="#/set/${esc(code)}/card/${encodeURIComponent(c.name)}">${esc(c.name)}</a>${c.error ? `<small class="err">${esc(c.error)}</small>` : `<small class="muted">${esc(c.card?.type_line || '')}</small>`}</td>
            <td><input type="text" data-k="subject" value="${esc(entryOf(c).subject || '')}"></td>
            <td><input type="text" data-k="flavor" value="${esc(entryOf(c).flavor || '')}"></td>
            <td><input type="text" data-k="art" value="${esc(entryOf(c).art || '')}"></td>
            <td><input type="text" data-k="art_filter" value="${esc(entryOf(c).art_filter || '')}"></td>
            <td><input type="number" class="num seed" data-k="seed" value="${entryOf(c).seed ?? ''}" placeholder="${c.recipe?.seed ?? ''}" title="pinned seed; the placeholder is the derived one"></td>
            <td><select data-k="remix">${remixOpts(c)}</select></td>
            <td class="picks">${entryOf(c).printing ? `<span class="badge accent">${esc(entryOf(c).printing)}</span>` : ''}${entryOf(c).base ? `<span class="badge accent">base ${esc(entryOf(c).base)}</span>` : ''}
              ${!entryOf(c).printing && !entryOf(c).base ? `<a class="muted" href="#/set/${esc(code)}/card/${encodeURIComponent(c.name)}" title="the printing and the restyle base are picked in the card view">pick…</a>` : ''}</td>
            <td class="acts"><button class="small" data-move="${i}|-1" title="move up" ${i ? '' : 'disabled'}>↑</button><button class="small" data-move="${i}|1" title="move down" ${i < st.cards_detail.length - 1 ? '' : 'disabled'}>↓</button>
              <button class="small" data-rename="${esc(c.name)}" title="change which card this entry names, keeping its edits">rename</button><button class="small" data-remove="${esc(c.name)}" title="remove from the set">✕</button></td>
          </tr>`).join('')}</tbody></table></div>
        <div class="toolbar">
          <button id="renumber" title="number the cards 1..n in this order">renumber</button>
          <span class="muted">numbers follow the order above only after a renumber; ↑ ↓ change the order, not the number</span>
        </div>
        <div class="form">
          <label>add cards</label><textarea id="addcards" rows="3" placeholder="a decklist or names, one per line; appended after the last number"></textarea>
          <label></label><div class="row"><button class="primary" id="addgo">add</button></div>
        </div>
      </div>
      <div class="panel">
        <h2>danger</h2>
        <div class="toolbar"><button class="danger" id="delset">delete set ${esc(code)}</button>
          <span class="muted">removes ${esc(st.path)} and its .css; renders in out/${esc(code.toLowerCase())}/ and the art cache stay</span></div>
      </div>
    </div>`;
  // set fields: one PATCH per change; a new code moves the page to it
  document.querySelectorAll('[data-s]').forEach(el => el.onchange = () => {
    const k = el.dataset.s; let v = el.value;
    if (k === 'size') v = v === '' ? null : parseInt(v, 10);
    api(`/api/sets/${code}`, {method: 'PATCH', body: {[k]: v === '' ? null : v}})
      .then(d => { state.set = d; state.setCode = d.code; toast(`${k} saved`); if (k === 'code') { state.ws = null; location.hash = `#/set/${d.code}/edit`; } else loadWorkspace().then(() => { if (k === 'base') edit(); }); })
      .catch(e => { toast(e.message, true); edit(); });
  });
  // style block
  if ($('#knobs')) $('#knobs').onclick = () => { E.knobs = !E.knobs; E.values = {...st.style}; edit(); };
  if ($('#savetpl')) $('#savetpl').onclick = () => saveTemplateFromSet(st);
  if ($('#dropstyle')) $('#dropstyle').onclick = () => {
    if (!confirm(`Remove the style block from ${code}? Its restyle variants stay in the art cache; a template can bring it back.`)) return;
    api(`/api/sets/${code}/style`, {method: 'PUT', body: {}}).then(() => { toast('style removed'); refresh(); }).catch(e => toast(e.message, true));
  };
  $('#applytpl').onclick = () => {
    const t = $('#tpl').value;
    if (st.style && !confirm(`Replace the style block of ${code} (${st.style.name}) with the template ${t}?`)) return;
    api(`/api/sets/${code}/style/template`, {method: 'POST', body: {template: t, css: $('#tplcss').checked}})
      .then(() => { toast(`${code} now styled as ${t}`); E.knobs = false; refresh(); }).catch(e => toast(e.message, true));
  };
  if (E.knobs && st.style) {
    bindStyleForm(fields, E.values, () => edit());
    $('#resetknobs').onclick = () => { E.values = {...st.style}; edit(); };
    $('#saveknobs').onclick = () => {
      const body = {name: st.style.name, ...slimStyle(fields, E.values, Object.keys(st.style))};
      api(`/api/sets/${code}/style`, {method: 'PUT', body}).then(() => { toast('style saved'); E.knobs = false; refresh(); }).catch(e => toast(e.message, true));
    };
  }
  // cards: a field change is one PUT and no re-render, so typing down a column keeps its focus
  document.querySelectorAll('tr[data-name] [data-k]').forEach(el => el.onchange = () => {
    const name = el.closest('tr').dataset.name, k = el.dataset.k; let v = el.value;
    if (k === 'number' || k === 'seed') v = v === '' ? null : parseInt(v, 10);
    else v = v || null;
    api(`/api/sets/${code}/cards/${encodeURIComponent(name)}`, {method: 'PUT', body: {[k]: v}})
      .then(d => { const i = st.cards_detail.findIndex(c => c.name === name); if (i >= 0) st.cards_detail[i] = d; toast(`${name}: ${k} saved`); })
      .catch(e => toast(e.message, true));
  });
  const order = () => st.cards_detail.map(c => c.name);
  const putCards = (body, msg) => api(`/api/sets/${code}/cards`, {method: 'PUT', body}).then(d => { state.set = d; toast(msg); edit(); }).catch(e => toast(e.message, true));
  document.querySelectorAll('[data-move]').forEach(b => b.onclick = () => {
    const [i, d] = b.dataset.move.split('|').map(Number), o = order(), j = i + d;
    [o[i], o[j]] = [o[j], o[i]];
    putCards({order: o}, 'order saved');
  });
  $('#renumber').onclick = () => putCards({order: order(), renumber: true}, 'renumbered');
  document.querySelectorAll('[data-rename]').forEach(b => b.onclick = () => {
    const name = b.dataset.rename, to = prompt(`Rename the entry ${name} to which card? Its edits and place are kept.`, name);
    if (!to || to === name) return;
    api(`/api/sets/${code}/cards/${encodeURIComponent(name)}/rename`, {method: 'POST', body: {name: to}}).then(d => { state.set = d; toast(`${name} → ${to}`); edit(); }).catch(e => toast(e.message, true));
  });
  document.querySelectorAll('[data-remove]').forEach(b => b.onclick = () => {
    const name = b.dataset.remove;
    if (!confirm(`Remove ${name} from ${code}? Its entry (subject, seed, base…) is lost; variants and renders stay on disk.`)) return;
    api(`/api/sets/${code}/cards/${encodeURIComponent(name)}`, {method: 'DELETE'}).then(d => { state.set = d; toast(`removed ${name}`); loadWorkspace().then(edit); }).catch(e => toast(e.message, true));
  });
  $('#addgo').onclick = () => {
    const text = $('#addcards').value; if (!text.trim()) return;
    const add = force => api(`/api/sets/${code}/cards`, {method: 'POST', body: {decklist: text, force}})
      .then(d => { state.set = d; toast(`${d.added} card(s) added`); loadWorkspace().then(edit); })
      .catch(e => { if (!force && e.message.startsWith('not in the card file') && confirm(`${e.message}\n\nAdd them anyway? They show as "not found" until the name is fixed or the card file has them.`)) add(true); else toast(e.message, true); });
    add(false);
  };
  $('#delset').onclick = () => {
    if (!confirm(`Delete the set ${code}? ${st.path} and its .css are removed. Renders in out/ and the art cache stay.`)) return;
    api(`/api/sets/${code}`, {method: 'DELETE'}).then(() => { toast(`deleted ${code}`); state.set = null; state.setCode = null; state.ws = null; location.hash = '#/'; }).catch(e => toast(e.message, true));
  };
}
/* Save a set's style block as a template, as `mint style save` does: asks for the name and the tier,
   and offers to replace one that exists. */
function saveTemplateFromSet(st) {
  const name = prompt(`Save ${st.code}'s style as which template? (styles/<name>.json; letters, digits, - and _)`, st.style.name);
  if (!name) return;
  const priv = confirm('Private (styles/private/, which git ignores)?\n\nOK = private, Cancel = shared in styles/');
  const save = force => api('/api/styles', {method: 'POST', body: {set: st.code, name, private: priv, force}})
    .then(t => { toast(`saved ${t.path}`); if (state.styles) state.styles.list = null; if (state.edit) state.edit.styles = null; })
    .catch(e => { if (!force && / exists|needs --force/.test(e.message) && confirm(`${e.message}\n\nReplace / share it anyway?`)) save(true); else toast(e.message, true); });
  save(false);
}

/* --- styles: the templates in styles/, and a form to make or change one ---------------------------- */
async function styles(r) {
  const fields = state.ws.style_fields;
  let T = state.styles;
  if (!T) T = state.styles = {list: null, name: null, values: null, css: '', private: false, keep: [], draft: false};
  if (!T.list) T.list = await api('/api/styles');
  const cur = r.name ? T.list.find(t => t.name === r.name) : null;
  if (r.name && !cur) { $('#main').innerHTML = `<div class="empty bad">no template ${esc(r.name)}</div>`; return; }
  if (cur && T.name !== cur.name) {
    T.name = cur.name; T.draft = false; T.values = {...cur.style}; T.css = cur.css || ''; T.private = cur.private; T.keep = Object.keys(cur.style);
  }
  if (!cur && !T.draft) T.name = null;
  const editing = cur || T.draft;
  const lit = f => JSON.stringify(T.values?.[f.name] ?? f.default) !== JSON.stringify(f.default);
  const asFile = cur ? Object.fromEntries(Object.entries(cur.style).filter(([k]) => k !== 'name')) : null;
  const dirty = cur && (JSON.stringify(slimStyle(fields, T.values, T.keep)) !== JSON.stringify(asFile) || T.css !== (cur.css || '') || T.private !== cur.private);
  const sets = (state.ws.sets || []).filter(s => !s.error);
  $('#main').innerHTML = `
    <div class="row"><h1>Styles</h1><span class="muted">templates in styles/ — a set starts from one, or is saved as one</span>
      ${STATIC ? '' : '<button id="newtpl" style="margin-left:auto">new template</button>'}</div>
    <div class="styles">
      <div class="tlist panel">
        ${T.list.map(t => `<div class="t ${t.name === T.name && !T.draft ? 'on' : ''}" data-tpl="${esc(t.name)}"><b>${esc(t.name)}</b>
          ${t.builtin ? '<span class="badge">built-in</span>' : ''}${t.private ? '<span class="badge" title="styles/private/, not in git">private</span>' : ''}${t.shadowed ? '<span class="badge warn" title="a private template of the same name is the one that is found">shadowed</span>' : ''}
          <small>${esc((t.style.prompt || '').slice(0, 80))}${(t.style.prompt || '').length > 80 ? '…' : ''}</small>
          ${t.sets.length ? `<small>used by ${t.sets.map(c => `<a href="#/set/${esc(c)}">${esc(c)}</a>`).join(' ')}</small>` : ''}</div>`).join('') || '<div class="empty">no templates yet</div>'}
      </div>
      <div class="panel">
        ${!editing ? '<div class="empty">pick a template, or make a new one</div>' : `
        <div class="row"><h2 style="margin:0">${T.draft ? 'new template' : esc(T.name)}</h2>
          ${cur?.builtin ? '<span class="muted">a built-in recipe: saving writes styles/' + esc(T.name) + '.json, which then shadows it</span>' : ''}
          ${cur?.path ? `<span class="muted mono">${esc(cur.path)}</span>` : ''}
          ${dirty ? '<span class="badge warn">unsaved</span>' : ''}</div>
        <div class="form">
          ${T.draft ? '<label>name</label><input type="text" id="tname" value="' + esc(T.name || '') + '" placeholder="letters, digits, - and _">' : ''}
          <label title="styles/private/ is git-ignored; a private template shadows a shared one of the same name">private</label><span><input type="checkbox" id="tprivate" ${T.private ? 'checked' : ''}></span>
          ${styleForm(fields, T.values, lit)}
          <label title="frame rules that go with the style; a set that starts from the template gets them as its css">css</label><textarea class="css" id="tcss" style="min-height:90px">${esc(T.css)}</textarea>
          <label></label><div class="row">
            <button class="primary" id="tsave">save</button>
            <button id="tsaveas" title="a copy under another name">save as…</button>
            ${cur && !cur.builtin ? '<button id="treset" class="small">reset</button>' : ''}
            ${cur && !cur.builtin ? `<button id="tdelete" class="danger" ${cur.sets.length ? `title="used by ${cur.sets.join(', ')} — their style blocks are copies and stay"` : ''}>delete</button>` : ''}
          </div>
          ${cur ? `<label>apply to set</label><div class="row"><select id="tset">${sets.map(s => `<option value="${esc(s.code)}">${esc(s.code)}${s.style ? ' (' + esc(s.style) + ')' : ' (no style)'}</option>`).join('')}</select>
            <label><input type="checkbox" id="tsetcss"> its css too</label><button id="tapply" ${sets.length ? '' : 'disabled'}>apply</button>
            <span class="muted">replaces that set's style block with this template as saved</span></div>` : ''}
        </div>
        <p class="muted" style="font-size:.85em">Lit knobs are off their default. A file holds the prompt, every lit knob, and whatever it spelled out before; the rest fall back to the defaults in <code>sets.Style</code>. Keep prompts about medium, palette and mood — a content noun here becomes the picture of any card without a subject.</p>`}
      </div>
    </div>`;
  document.querySelectorAll('[data-tpl]').forEach(el => el.onclick = e => { if (e.target.tagName !== 'A') location.hash = `#/styles/${encodeURIComponent(el.dataset.tpl)}`; });
  if ($('#newtpl')) $('#newtpl').onclick = () => {
    T.draft = true; T.name = ''; T.values = {}; fields.forEach(f => { if (f.name !== 'name' && f.default !== null) T.values[f.name] = f.default; });
    T.values.prompt = ''; T.css = ''; T.private = false; T.keep = [];
    if (location.hash !== '#/styles') location.hash = '#/styles'; else styles({view: 'styles'});
  };
  if (!editing) return;
  bindStyleForm(fields, T.values, () => styles(r));
  $('#tprivate').onchange = e => { T.private = e.target.checked; styles(r); };
  $('#tcss').onchange = e => { T.css = e.target.value; };
  if ($('#tname')) $('#tname').onchange = e => { T.name = e.target.value.trim(); };
  const save = (name, then) => {
    if (!name) { toast('a template needs a name', true); return; }
    T.css = $('#tcss').value;
    api(`/api/styles/${encodeURIComponent(name)}`, {method: 'PUT', body: {style: slimStyle(fields, T.values, T.keep), css: T.css, private: T.private}})
      .then(t => { toast(`saved ${t.path}`); T.list = null; T.name = null; T.draft = false; if (state.edit) state.edit.styles = null; (then || (() => { location.hash = `#/styles/${encodeURIComponent(name)}`; if (r.name === name) styles({view: 'styles', name}); }))(); })
      .catch(e => toast(e.message, true));
  };
  $('#tsave').onclick = () => save(T.draft ? T.name : cur.name);
  $('#tsaveas').onclick = () => { const n = prompt('Save as which template?', (T.name || '') + '-2'); if (n) save(n.trim()); };
  if ($('#treset')) $('#treset').onclick = () => { T.name = null; styles(r); };
  if ($('#tdelete')) $('#tdelete').onclick = () => {
    if (!confirm(`Delete the template ${cur.name} (${cur.path})?${cur.sets.length ? ` The sets ${cur.sets.join(', ')} keep their own copies.` : ''}`)) return;
    api(`/api/styles/${encodeURIComponent(cur.name)}`, {method: 'DELETE'}).then(() => { toast(`deleted ${cur.name}`); T.list = null; T.name = null; if (state.edit) state.edit.styles = null; location.hash = '#/styles'; }).catch(e => toast(e.message, true));
  };
  if ($('#tapply')) $('#tapply').onclick = () => {
    const code = $('#tset').value, s = sets.find(x => x.code === code);
    if (s.style && !confirm(`Replace the style block of ${code} (${s.style}) with ${cur.name}?`)) return;
    api(`/api/sets/${code}/style/template`, {method: 'POST', body: {template: cur.name, css: $('#tsetcss').checked}})
      .then(async () => { toast(`${code} now styled as ${cur.name}`); T.list = null; state.set = null; await loadWorkspace(); styles(r); }).catch(e => toast(e.message, true));
  };
}

/* --- jobs ----------------------------------------------------------------------------- */
async function jobs() {
  if (!Object.keys(state.jobs).length) (await api('/api/jobs')).forEach(j => state.jobs[j.id] = j);
  const list = Object.values(state.jobs).sort((a, b) => b.created - a.created);
  $('#main').innerHTML = `<h1>Jobs</h1>` + (list.map(j => `
    <div class="job">
      <div class="head"><span class="st ${j.state}">${j.state}</span><b>${esc(j.title)}</b>
        <span class="muted mono">${j.done}/${j.total}</span>
        ${j.state === 'queued' || j.state === 'running' ? `<button class="small" data-cancel="${j.id}">cancel</button>` : ''}
        <span class="muted" style="margin-left:auto">${new Date(j.created * 1000).toLocaleTimeString()}${j.finished ? ` · ${Math.round(j.finished - (j.started || j.created))}s` : ''}</span></div>
      ${j.state === 'running' ? `<div class="bar"><i style="width:${j.total ? 100 * j.done / j.total : 0}%"></i></div>` : ''}
      ${j.error ? `<div class="bad">${esc(j.error)}</div>` : ''}
      ${j.log.length ? `<pre>${esc(j.log.slice(-40).join('\n'))}</pre>` : ''}
    </div>`).join('') || '<div class="empty">no jobs yet</div>');
  document.querySelectorAll('[data-cancel]').forEach(b => b.onclick = () => api(`/api/jobs/${b.dataset.cancel}/cancel`, {method: 'POST'}).then(jobs));
}

/* --- boot ------------------------------------------------------------------------------- */
api('/api/jobs').then(list => { list.forEach(j => state.jobs[j.id] = j); renderJobstrip(); }).catch(() => {});
connect();
go();
