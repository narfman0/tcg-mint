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
const REMIX = {restyle: 'same picture, redrawn', repose: 'new picture in the pose image\'s pose', new: 'from the prompt alone',
               inspire: 'new picture inspired by the base: its look and character, the words decide the pose and scene'};
const REMIX_BADGE = {repose: 'repose', new: 'new scene', inspire: 'inspired'};

/* mode: plain or styled art on a board tile; show: the art alone or the whole rendered card (when
   there is one); style: which restyle label a styled tile shows ('current' = the set's own recipe,
   else any label the art cache holds); q: the board's search text. */
/* style2: a second look shown beside the first on every tile (the set-level A/B); sort: number | name |
   colour (the shown image's hue, measured in the browser); sheet: tiles without names and badges, tighter */
const state = {ws: null, set: null, setCode: null, jobs: {}, sel: new Set(), mode: 'styled', show: 'art', style: 'current', q: '',
               style2: '', sort: 'number', sheet: false, colours: {}, paper: 'letter', stock: '',
               ab: {a: null, b: null, wipe: 50, zoom: 1, x: 0, y: 0, blind: false, swap: false}, lab: null, frame: {},
               takes: 1, upscale: false, dpi: 1200, genOpen: true, missing: false, selecting: false};

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
async function submit(job, origin) {
  try { const j = await api('/api/jobs', {method: 'POST', body: {...job, origin}}); state.jobs[j.id] = j; toast(`queued: ${j.title}`); renderJobstrip(); return j; }
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
/* Style templates (styles/ and the built-ins), fetched once for the "restyle as" pickers; a view
   that finds them missing draws without and again once they arrive. */
function templates(redraw) {
  if (state.templates || STATIC) return state.templates || [];
  if (!state.templatesLoading) { state.templatesLoading = true; api('/api/styles').then(l => { state.templates = l; redraw(); }).catch(() => { state.templates = []; }); }
  return [];
}
/* The look picker (state.style): 'current' is the set's own recipe; a label is a restyle the art cache
   holds (with how many cards have it); a template not run yet is listed too. A styled tile shows the
   look, the board's filter finds cards without it, and restyle makes it -- when it is runnable: the
   set's recipe or a template (a lab label has no template to run; save one, or promote it). */
/* [value, text] for every look: the set's recipe, each label the art cache holds, each template not run yet */
function lookOptions(cards, setStyle, all = false) {
  const labels = styleLabels(cards), have = new Set(labels.map(([l]) => l));
  const tpls = templates(() => go()).filter(t => !have.has(t.name) && t.name !== setStyle?.name);
  return [['current', all ? "each set's recipe" : setStyle ? `set's recipe: ${setStyle.name}` : "set's recipe (none)"],
          ...labels.map(([l, k]) => [l, `${l} (${k})`]), ...tpls.map(t => [t.name, `${t.name} (template)`])];
}
function lookPicker(id, cards, setStyle, all = false) {
  return `<select id="${id}" title="the look: what a styled tile shows, and what restyle makes. The set's recipe, any restyle in the art cache, or a template not run yet">
    ${lookOptions(cards, setStyle, all).map(([v, t]) => `<option value="${esc(v)}" ${state.style === v ? 'selected' : ''}>${esc(t)}</option>`).join('')}</select>`;
}
/* How many takes a restyle makes per card: each from its own random seed, to choose between. */
const takesPicker = () => `<label class="takes" title="takes per card: each a variant from its own random seed, side by side in Compare. More than one = drafts without the ESRGAN pass (a large share of a take\'s time); enhance the one you keep"><span class="muted">×</span><input type="number" id="takes" min="1" max="16" value="${state.takes}"></label>`;
const bindTakes = () => { if ($('#takes')) $('#takes').onchange = e => { state.takes = Math.max(1, Math.min(16, +e.target.value || 1)); e.target.value = state.takes; }; };
/* The template a restyle in the current look runs: undefined for the set's own recipe, null when the
   look cannot be made (no template of that name), else the name. */
function lookTemplate(setStyle) {
  if (state.style === 'current' || state.style === setStyle?.name) return setStyle ? undefined : null;
  return templates(() => go()).some(t => t.name === state.style) ? state.style : null;
}
const lookTitle = setStyle => lookTemplate(setStyle) === null
  ? (state.style === 'current' ? 'the set has no style block: pick a template to restyle as' : `${state.style} is not a template; save one from the lab (styles page) or promote a variant`)
  : `generate in the look picked beside: ${lookTemplate(setStyle) || (setStyle?.name ?? '')}`;
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
    const views = {home, board, card, lab, frame, jobs, viewer, edit, styles, pdfs};
    if (r.view !== 'viewer' && !(r.view === 'card' && r.key)) closeViewer();
    (views[r.view] || home)(r);
    renderNav();
  } catch (e) {
    const down = e instanceof TypeError;  // fetch itself failed: no server behind the installed shell
    $('#main').innerHTML = down
      ? `<div class="empty">the workbench is not reachable: is <code>mint serve</code> running? <a href="#/" onclick="location.reload()">retry</a></div>`
      : `<div class="empty bad">${esc(e.message)}</div>`;
  }
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
  es.addEventListener('item', e => { const d = JSON.parse(e.data); const j = state.jobs[d.id]; if (j) { (j.items || (j.items = [])).push(d); if (route().view === 'jobs') jobs(); } arrived(d); });
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
  if (styleOf(c) && !c.current && !c.picked) b.push(['', 'no restyle']);
  if (c.entry.pick) b.push([c.picked ? 'accent' : 'bad', c.picked ? 'picked' : 'pick gone']);
  if (c.renders?.plain?.shrunk || c.renders?.styled?.shrunk) b.push(['warn', 'text shrunk']);
  if (c.renders?.plain?.stale || c.renders?.styled?.stale) b.push(['warn', 'stale render']);
  if (c.entry.art) b.push(['accent', 'own art']);
  if (c.entry.printing) b.push(['accent', c.entry.printing]);
  if (c.entry.base) b.push(['accent', 'base ' + c.entry.base]);
  if (c.entry.pose) b.push(['accent', 'pose ' + short(c.entry.pose.split('/').pop())]);
  if (c.base_missing) b.push(['warn', `no ${c.base_missing} to start from`]);
  if (c.entry.seed != null) b.push(['accent', 'seed pinned']);
  const remix = c.entry.remix || styleOf(c)?.remix || 'restyle';
  if (remix !== 'restyle') b.push(['accent', REMIX_BADGE[remix] || remix]);
  if (!c.renders?.plain && !c.renders?.styled) b.push(['', 'not rendered']);
  return b.map(([k, t]) => `<span class="badge ${k}">${esc(t)}</span>`).join('');
}
/* Restyle labels the art cache holds for these cards, most common first: [label, card count]. */
function styleLabels(cards) {
  const m = new Map();
  cards.forEach(c => (c.variants || []).forEach(v => { if (v.kind === 'restyle') (m.get(v.label) || m.set(v.label, new Set()).get(v.label)).add(c.name); }));
  return [...m].map(([l, s]) => [l, s.size]).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}
/* A card's variant for a label: its pick or the one the set's recipe names if that has the label, else the newest. */
function variantFor(c, label) {
  const vs = (c.variants || []).filter(v => v.kind === 'restyle' && v.label === label);
  return vs.find(v => v.hash === c.entry.pick) || vs.find(v => v.hash === c.style_hash) || vs.sort((a, b) => (b.created || '').localeCompare(a.created || ''))[0] || null;
}
/* The image a card shows for the current mode / show / style: {path, card: bool, what} or {none: why}.
   "card" wants the render; without one the art stands in (the tile's shape says which). */
function shown(c, style = state.style) {
  const m = state.mode;
  if (state.show === 'card' && style === 'current') {
    const r = c.renders?.[m];
    if (r) return {path: r.path, card: true, what: `render · ${m} · ${r.dpi || '?'} dpi`};
  }
  if (m === 'styled' && style !== 'current') {
    const v = variantFor(c, style);
    return v ? {path: v.path, what: `${v.label}-${v.hash}`} : {none: `no ${style}`};
  }
  const src = c[m];
  return src ? {path: src.path, what: src.label ? `${src.label}-${src.hash}` : src.kind} : {none: m === 'styled' ? 'no restyle yet' : 'crop not fetched'};
}
function tilePic(c, style = state.style) {
  const s = shown(c, style);
  if (s.none) return `<div class="pic art"><div class="none">${esc(s.none)}</div></div>`;
  return `<div class="pic ${s.card ? '' : 'art'}"><img loading="lazy" src="${img(s.path, 320)}"></div>`;
}
/* The shown image's colour, measured in the browser from its thumbnail: (hue, saturation, lightness),
   cached by path. The colour sort waits for every card's, then redraws. */
function colourOf(path) {
  if (state.colours[path]) return Promise.resolve(state.colours[path]);
  return new Promise(res => {
    const im = new Image(); im.crossOrigin = 'anonymous';
    im.onload = () => {
      const cv = document.createElement('canvas'); cv.width = cv.height = 8;
      const cx = cv.getContext('2d'); cx.drawImage(im, 0, 0, 8, 8);
      const d = cx.getImageData(0, 0, 8, 8).data; let r = 0, g = 0, b = 0;
      for (let i = 0; i < d.length; i += 4) { r += d[i]; g += d[i + 1]; b += d[i + 2]; }
      r /= 64 * 255; g /= 64 * 255; b /= 64 * 255;
      const max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2, dlt = max - min;
      const s = dlt === 0 ? 0 : dlt / (1 - Math.abs(2 * l - 1));
      let h = 0;
      if (dlt) h = max === r ? ((g - b) / dlt) % 6 : max === g ? (b - r) / dlt + 2 : (r - g) / dlt + 4;
      res(state.colours[path] = {h: (h * 60 + 360) % 360, s, l});
    };
    im.onerror = () => res(state.colours[path] = {h: 0, s: 0, l: 0.5});
    im.src = img(path, 320);
  });
}
const colourKey = c => { const p = shown(c).path, k = p && state.colours[p]; return !k ? [2, 0] : k.s < 0.12 ? [1, k.l] : [0, k.h, k.l]; };
function boardCards() {
  const st = state.set, filt = state.filter || '', q = (state.q || '').toLowerCase();
  const hit = c => !q || [c.name, c.card?.type_line, c.inSet, c.card?.artist, String(c.number ?? '')].some(v => (v || '').toLowerCase().includes(q));
  const cs = st.cards_detail.filter(c => hit(c) && (!filt || badges(c).includes(`>${filt}<`) || (filt === 'no restyle' && !c.current && !c.picked)
    || (filt === `no ${state.style}` && !variantFor(c, state.style))));
  if (state.sort === 'name') cs.sort((a, b) => a.name.localeCompare(b.name));
  else if (state.sort === 'colour') cs.sort((a, b) => { const x = colourKey(a), y = colourKey(b); for (let i = 0; i < 3; i++) { const d = (x[i] ?? 0) - (y[i] ?? 0); if (d) return d; } return 0; });
  return cs;
}
function tileHtml(c) {
  const two = state.style2 && state.mode === 'styled';
  return `
      <div class="tile ${state.sel.has(c.name) ? 'sel' : ''} ${two ? 'two' : ''}" data-name="${esc(c.name)}" data-set="${esc(setOf(c))}">
        ${two ? `<div class="pics">${tilePic(c)}${tilePic(c, state.style2)}</div>` : tilePic(c)}
        <div class="name"><b>${esc(c.name)}</b><span class="muted mono">${state.set.all ? esc(c.inSet) + ' ' : ''}${c.number ?? ''}</span></div>
        <div class="badges">${badges(c)}</div>
      </div>`;
}
/* A tile opens its card. Shift/ctrl-click selects it instead, as does any tap while the toolbar's
   "select" is on; on a touch screen a long press selects it and turns "select" on, so the taps that
   follow select too. The press redraws the board at once; the click the finger's release still
   sends (its own task, on whatever tile is there by then) is swallowed by name for a moment. */
const toggleSel = name => { state.sel.has(name) ? state.sel.delete(name) : state.sel.add(name); };
let pressed = null;  // {name, t}: the tile a long press just selected, whose click is not a click
function bindTile(t) {
  let hold = null, at = null;
  t.onpointerdown = e => {
    if (e.pointerType !== 'touch') return;
    at = {x: e.clientX, y: e.clientY};
    hold = setTimeout(() => {
      hold = null; pressed = {name: t.dataset.name, t: Date.now()}; state.selecting = true; toggleSel(t.dataset.name);
      navigator.vibrate?.(20); board();
    }, 450);
  };
  t.onpointermove = e => { if (hold && Math.hypot(e.clientX - at.x, e.clientY - at.y) > 10) { clearTimeout(hold); hold = null; } };
  t.onpointerup = t.onpointercancel = () => { if (hold) { clearTimeout(hold); hold = null; } };
  t.oncontextmenu = e => { if (hold || pressed) e.preventDefault(); };
  t.onclick = e => {
    const name = t.dataset.name;
    const swallow = pressed && pressed.name === name && Date.now() - pressed.t < 1000;
    pressed = null;
    if (swallow) { e.preventDefault(); return; }
    if (e.shiftKey || e.ctrlKey || e.metaKey || state.selecting) { toggleSel(name); board(); }
    else location.hash = `#/set/${t.dataset.set}/card/${encodeURIComponent(name)}`;
  };
}
/* A job finished one card (an `item` event): fetch that card's detail alone, swap it into the
   set, and redraw just its tile -- or the card page, if that is what is open. So a batch of 80
   restyles shows each as it lands rather than when the whole job ends; the final refresh on
   `done` still brings the look picker's counts and the filters up to date. */
async function arrived(d) {
  const st = state.set;
  if (!st || !d.set || !d.name) return;
  const all = !!st.all, code = d.set.toLowerCase();
  if (!all && st.code.toLowerCase() !== code) return;
  const i = st.cards_detail.findIndex(c => c.name === d.name && (!all || (c.inSet || '').toLowerCase() === code));
  if (i < 0) return;
  let c;
  try { c = await api(`/api/sets/${encodeURIComponent(d.set)}/cards/${encodeURIComponent(d.name)}`); } catch (e) { return; }
  if (state.set !== st) return;  // the page moved on while we fetched
  const old = st.cards_detail[i];
  st.cards_detail[i] = all ? {...c, inSet: old.inSet, setStyle: old.setStyle} : c;
  const r = route();
  if ((r.view === 'board' || r.view === 'viewer') && $('.grid')) {
    const t = document.querySelector(`.grid .tile[data-name="${CSS.escape(d.name)}"][data-set="${CSS.escape(setOf(old))}"]`);
    if (!t) return;
    const tmp = document.createElement('div'); tmp.innerHTML = tileHtml(st.cards_detail[i]);
    const fresh = tmp.firstElementChild; bindTile(fresh); t.replaceWith(fresh);
  } else if (r.view === 'card' && r.name === d.name && !r.key) card(r);
}
function board() {
  const st = state.set, code = st.code, all = !!st.all;
  const sel = state.sel, n = sel.size;
  const filt = state.filter || '';
  const labels = styleLabels(st.cards_detail);
  if (state.style !== 'current' && !labels.some(([l]) => l === state.style) && !templates(() => go()).some(t => t.name === state.style)) state.style = 'current';
  const cards = boardCards();
  const filters = ['no restyle', ...(state.style !== 'current' ? [`no ${state.style}`] : []), 'not rendered', 'stale render', 'text shrunk', 'UB art', 'own art'];
  // the two job stages. "restyle" makes art in the look picked; "render styled" composes cards from the art
  // each card's styled render uses (its pick, else the set recipe's variant), so it follows the look
  // only when that look is the set's recipe -- viewing another look, it is off rather than a surprise
  const lookName = state.style !== 'current' ? state.style : all ? "each set's recipe" : st.style?.name || '?';
  const lookIsRecipe = state.style === 'current' || (!all && state.style === st.style?.name);
  const target = n ? st.cards_detail.filter(c => sel.has(c.name)) : st.cards_detail;
  const hasStyled = c => !!(c.entry.pick ? c.picked : c.current);
  const cover = {have: target.filter(hasStyled).length, total: target.length};
  const anyStyle = all ? st.sets.some(x => x.style) : !!st.style;
  const styledOk = anyStyle && lookIsRecipe;
  // "only what's missing": each job narrows to the cards without its product
  const lacks = {
    'enhance': c => !c.plain || c.plain.kind === 'crop',
    'restyle': c => lookIsRecipe ? !hasStyled(c) : !variantFor(c, state.style),
    'render-plain': c => !c.renders?.plain || !!c.renders.plain.stale,
    'render-styled': c => !c.renders?.styled || !!c.renders.styled.stale,
  };
  const targets = job => state.missing ? target.filter(lacks[job]) : target;
  const count = job => state.missing ? ` <small>${targets(job).length}</small>` : '';
  const styledTitle = !anyStyle ? 'no style block: nothing styled to render'
    : !lookIsRecipe ? `renders each card's pick, else the set's recipe${all ? '' : ` (${st.style.name})`}, not ${state.style}. Make ${state.style} the set style (promote a take on a card page), or keep a ${state.style} take on each card, then render in the set's recipe`
    : cover.have < cover.total ? `${cover.total - cover.have} of ${cover.total} have no styled art yet: the set's art_filter over the crop stands in for those. Filter "no restyle" to see them`
    : 'each card with its styled art: its pick, else the recipe\'s variant';
  $('#main').innerHTML = `
    <div class="row"><h1>${esc(code)} <span class="muted">${esc(st.name)}</span></h1>
<button class="pill" id="gallery" title="flip through the cards full-screen">gallery</button>${all ? '' : `<a class="pill" href="#/set/${esc(code)}/edit">edit</a><a class="pill" href="#/set/${esc(code)}/lab">recipe lab</a><a class="pill" href="#/set/${esc(code)}/frame">frame</a><a class="pill" href="#/set/${esc(code)}/pdfs" title="the set's PDFs: view, download, export">pdfs</a>`}
      <span class="muted">${st.cards_detail.length} cards${all ? ` across ${st.sets.length} sets` : ''}${st.style && !all ? ` · style ${esc(st.style.name)}` : ''}${st.base && !all ? ` · from <b>${esc(st.base)}</b>` : ''}${all ? '' : ` · <span class="mono">${esc(st.path)}</span>`}</span></div>
    <div class="toolbar">
      <span class="seg">${['plain', 'styled'].map(m => `<button data-mode="${m}" class="${state.mode === m ? 'on' : ''}">${m}</button>`).join('')}</span>
      <span class="seg" title="the art alone, or the whole rendered card where there is one">${[['art', 'art'], ['card', 'card']].map(([m, t]) => `<button data-show="${m}" class="${state.show === m ? 'on' : ''}">${t}</button>`).join('')}</span>
      ${lookPicker('style', st.cards_detail, st.style, all)}
      ${state.mode === 'styled' ? `<select id="style2" title="a second look beside the first on every tile: the set-level A/B"><option value="">vs —</option>${lookOptions(st.cards_detail, st.style, all).filter(([v]) => v !== state.style).map(([v, t]) => `<option value="${esc(v)}" ${state.style2 === v ? 'selected' : ''}>vs ${esc(t)}</option>`).join('')}</select>` : ''}
      <span class="sep"></span>
      <select id="sort" title="the order of the tiles: by number, by name, or by the shown image's colour, so a take that wandered off the set's palette stands out"><option value="number" ${state.sort === 'number' ? 'selected' : ''}>by number</option><option value="name" ${state.sort === 'name' ? 'selected' : ''}>by name</option><option value="colour" ${state.sort === 'colour' ? 'selected' : ''}>by colour</option></select>
      <span class="seg" title="tiles with their names and badges, or a dense sheet of pictures alone">${[['tiles', false], ['sheet', true]].map(([t, v]) => `<button data-sheet="${v}" class="${state.sheet === v ? 'on' : ''}">${t}</button>`).join('')}</span>
      <input type="text" id="q" placeholder="search name, type, artist${all ? ', set' : ''}" value="${esc(state.q || '')}">
      <select id="filter"><option value="">all cards</option>${filters.map(f => `<option ${filt === f ? 'selected' : ''}>${f}</option>`).join('')}</select>
      ${filt || state.q ? `<button id="selshown" class="small" title="select the ${cards.length} card(s) shown, so the jobs below run on just them">select shown</button>` : ''}
      <button id="selmode" class="small ${state.selecting ? 'on' : ''}" title="on: a tap selects a card instead of opening it. Shift-click, or a long press on a phone, selects too">select</button>
    </div>
    <div class="toolbar jobs">
      <span class="muted">${n ? `${n} selected` : 'all cards'}:</span>
      <span class="stage" title="art jobs write variants to the art cache; nothing is rendered"><span class="lbl">art</span>
        <button data-job="enhance" title="an ESRGAN pass on each card's crop, the plain art; the plain render picks it up">enhance crop${count('enhance')}</button>
        <button data-job="restyle" ${all ? (st.sets.some(x => x.style) || lookTemplate(null) ? '' : 'disabled') : lookTemplate(st.style) === null ? 'disabled' : ''} title="${esc(all ? 'each set in the look picked' : lookTitle(st.style))}">restyle as ${esc(lookName)}${count('restyle')}</button>${takesPicker()}
      </span>
      <span class="stage" title="card jobs compose the frame, text and art into out/; they use the art that exists and make none"><span class="lbl">cards</span>
        <button data-job="render-plain" title="each card with its plain art: the crop, or its enhance">render plain${count('render-plain')}</button>
        <button data-job="render-styled" ${styledOk ? '' : 'disabled'} title="${esc(styledTitle)}">render styled${state.missing ? count('render-styled') : styledOk && cover.have < cover.total ? ` <small>${cover.have}/${cover.total}</small>` : ''}</button>
        <select id="dpi">${[300, 600, 1200].map(d => `<option ${state.dpi === d ? 'selected' : ''}>${d}</option>`).join('')}</select><span class="muted">dpi</span>
      </span>
      <span class="stage" title="a print run: the cards' renders in the mode picked above (made where missing or stale), laid out 3x3 as a PDF under out/${esc(code.toLowerCase())}/print/, and printed when a stock is picked"><span class="lbl">print</span>
        <button data-job="printrun" title="render what is missing or stale, impose, and print if a stock is picked">print run · ${state.mode}</button>
        <select id="paper">${(state.ws.print?.paper || ['letter']).map(p => `<option ${state.paper === p ? 'selected' : ''}>${p}</option>`).join('')}</select>
        <select id="stock" title="what is in the tray; PDF only makes the file and prints nothing"><option value="">PDF only</option>${(state.ws.print?.stocks || []).map(s => `<option ${state.stock === s ? 'selected' : ''}>${s}</option>`).join('')}</select>
      </span>
      <label class="missing" title="each job skips the cards that already have its product: an enhance of the crop, art in the look, a plain or styled render that is not stale. The count is what it would make"><input type="checkbox" id="missing" ${state.missing ? 'checked' : ''}> only what's missing</label>
      ${n ? '<button id="clearsel" class="small">clear selection</button>' : ''}
    </div>
    <div class="grid ${state.sheet ? 'sheet' : ''}"></div>`;
  const grid = () => {
    $('.grid').innerHTML = boardCards().map(tileHtml).join('') || '<div class="empty">nothing matches</div>';
    document.querySelectorAll('.tile').forEach(bindTile);
  };
  grid();
  if (state.sort === 'colour') {  // measure what is not measured yet, then lay the tiles out again
    const paths = boardCards().map(c => shown(c).path).filter(p => p && !state.colours[p]);
    if (paths.length) Promise.all(paths.map(colourOf)).then(() => { if (state.set === st && $('.grid')) grid(); });
  }
  if ($('#style2')) $('#style2').onchange = e => { state.style2 = e.target.value; board(); };
  $('#sort').onchange = e => { state.sort = e.target.value; board(); };
  document.querySelectorAll('[data-sheet]').forEach(b => b.onclick = () => { state.sheet = b.dataset.sheet === 'true'; board(); });
  $('#gallery').onclick = () => { const cs = boardCards(); if (!cs.length) return toast('nothing to show'); V.fromPage = true; location.hash = viewHash(setOf(cs[0]), cs[0].name); };
  document.querySelectorAll('[data-mode]').forEach(b => b.onclick = () => { state.mode = b.dataset.mode; board(); });
  document.querySelectorAll('[data-show]').forEach(b => b.onclick = () => { state.show = b.dataset.show; board(); });
  if ($('#style')) $('#style').onchange = e => { state.style = e.target.value; board(); };
  bindTakes();
  $('#filter').onchange = e => { state.filter = e.target.value; board(); };
  $('#q').oninput = e => { state.q = e.target.value; grid(); };  // the grid alone, so typing keeps its focus
  if ($('#clearsel')) $('#clearsel').onclick = () => { sel.clear(); state.selecting = false; board(); };
  $('#selmode').onclick = () => { state.selecting = !state.selecting; board(); };
  if ($('#selshown')) $('#selshown').onclick = () => { boardCards().forEach(c => sel.add(c.name)); board(); };
  $('#missing').onchange = e => { state.missing = e.target.checked; board(); };
  $('#dpi').onchange = e => { state.dpi = +e.target.value; };
  $('#paper').onchange = e => { state.paper = e.target.value; };
  $('#stock').onchange = e => { state.stock = e.target.value; };
  document.querySelectorAll('[data-job]').forEach(b => b.onclick = () => {
    const dpi = +$('#dpi').value, job = b.dataset.job;
    const cs = job === 'printrun' ? target : targets(job);  // a print run wants every card it is aimed at
    if (job === 'printrun' && state.stock && !confirm(`Print ${cs.length} card(s) of ${code} on ${state.stock} to ${state.ws.print?.printer}? Check what is in the tray.`)) return;
    if (!cs.length) return toast(state.missing ? 'nothing missing: every card has it' : 'no cards');
    // on the ALL board a job is one submission per set. The names go explicitly unless the job is
    // the whole set (no selection, not narrowed to the missing), which null says
    const whole = !n && !state.missing;
    const groups = all
      ? [...new Set(cs.map(setOf))].map(s => [s, whole ? null : cs.filter(c => setOf(c) === s).map(c => c.name)])
      : [[code, whole ? null : cs.map(c => c.name)]];
    groups.forEach(([s, list]) => {
      const styled = all ? st.sets.find(x => x.code === s)?.style : st.style;
      const jobs = {
        'render-plain': {kind: 'render', set: s, names: list, styled: false, dpi},
        'render-styled': styled && {kind: 'render', set: s, names: list, styled: true, dpi},
        'enhance': {kind: 'enhance', set: s, names: list, base: 'crop'},
        'restyle': lookTemplate(styled) !== null && {kind: 'restyle', set: s, names: list, template: lookTemplate(styled), takes: state.takes},
        'printrun': {kind: 'printrun', set: s, names: list, styled: state.mode === 'styled', dpi, paper: state.paper || 'letter', stock: state.stock || null},
      };
      const origin = `${all ? 'all-sets board' : code + ' board'}: ${n ? `${n} selected` : 'all cards'}${state.missing ? ', only what\'s missing' : ''}${all ? ` (${s})` : ''}`;
      if (jobs[job]) submit(jobs[job], origin);
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
  return allColumns(c).map(x => ({key: x.key, path: x.path, card: x.kind === 'card', what: x.sub, c,
                                 title: `${c.name} · ${x.title}`, sub: '', recipe: x.recipe,
                                 badges: (x.styled ? '<span class="badge accent">styled art</span>' : '') + (x.key === (c.entry.base || state.set.base) ? '<span class="badge accent">from</span>' : ''),
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
  const n = V.slides.length, onBoard = V.kind === 'board', c = s.c;
  const el = $('#viewer');
  el.innerHTML = `
    <div class="vtop">
      <span class="vtitle"><b>${esc(s.title)}</b> <span class="muted">${esc(s.sub)}</span></span>
      ${onBoard ? `<span class="seg">${['plain', 'styled'].map(m => `<button data-vmode="${m}" class="${state.mode === m ? 'on' : ''}">${m}</button>`).join('')}</span>
      <span class="seg">${['art', 'card'].map(m => `<button data-vshow="${m}" class="${state.show === m ? 'on' : ''}">${m}</button>`).join('')}</span>` : ''}
      ${onBoard ? lookPicker('vstyle', state.set.cards_detail, state.set.style, !!state.set.all) : ''}
      <span class="spacer"></span>
      <span class="mono muted wide" id="vzoom">1×</span>
      <span class="wide"><button class="small" data-v="out" title="zoom out (−)">−</button><button class="small" data-v="in" title="zoom in (+)">+</button><button class="small" data-v="fit" title="fit (0)">fit</button></span>
      ${onBoard ? `<a class="pill" href="#/set/${esc(setOf(c))}/card/${encodeURIComponent(c.name)}" title="compare (c)">compare</a>` : ''}
      ${s.path ? `<a class="pill wide" href="${file(s.path)}" target="_blank" title="the full file in a new tab">open</a>` : ''}
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
      <span class="muted wide">← → ${onBoard ? 'card' : 'image'} · wheel / pinch zoom · drag pan · double-click 2.5×${onBoard ? ' · p s plain/styled · a r art/card · c compare' : ''} · f fullscreen · Esc</span>
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
  const dbl = (x, y) => { const r = stage.getBoundingClientRect(); zoomTo(V.z > 1 ? 1 : 2.5, x - r.left, y - r.top); };
  stage.ondblclick = e => { if (!V.touch) dbl(e.clientX, e.clientY); };  // a touch screen's double tap is read below
  stage.onpointerdown = e => {
    if (e.target.classList.contains('vnav')) return;
    V.touch = e.pointerType === 'touch';
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
    // a tap is a press that went nowhere; two within 300 ms and a finger's width are a double tap
    if (V.touch && e.type === 'pointerup' && V.swipe && Math.hypot(e.clientX - V.swipe.x, e.clientY - V.swipe.y) < 10 && !V.ptrs.size) {
      const last = V.tap, now = Date.now();
      V.tap = {x: e.clientX, y: e.clientY, t: now};
      if (last && now - last.t < 300 && Math.hypot(e.clientX - last.x, e.clientY - last.y) < 40) { V.tap = null; dbl(e.clientX, e.clientY); }
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
/* --- card detail ---------------------------------------------------------------------- */
/* The page has three parts, for the three things done here. The card: what it is and what it
   prints as -- its styled art (the pick, else what the recipe hashes to) and its renders. The
   generate panel: one mode, and only that mode's inputs, all of them the card's own recipe
   overrides. The images: every picture the card has, grouped by look, to compare, keep, enhance,
   or start the next generate from. */
const newest = (a, b) => (b.created || '').localeCompare(a.created || '');
const isPath = s => !!s && (s.includes('/') || /\.(png|jpe?g|webp)$/i.test(s));
/* The card's images as compare columns, in groups: source (the crop and its enhance), one group per
   look label (its restyles newest first, each enhance right after the restyle it was made from),
   and the renders. `styled` marks the one the styled render uses. */
function columns(c) {
  const vs = c.variants || [], cur = c.current?.hash, pick = c.entry.pick, styled = pick || cur;
  const enhOf = h => vs.filter(v => v.kind === 'enhance' && v.base === h).sort(newest);
  const col = (v, extra) => ({key: v.hash, title: v.label, sub: v.hash, path: v.path, kind: v.kind, recipe: v.recipe, v,
                              styled: v.hash === styled, ...extra});
  const groups = [], src = [];
  if (c.crop) src.push({key: 'crop', title: 'crop', sub: `${c.card.set.toUpperCase()} ${c.card.collector_number} · ${c.card.artist}`,
                        path: c.crop, kind: 'crop', enhanced: enhOf('crop')});
  enhOf('crop').forEach(e => src.push(col(e, {title: 'enhance', sub: `${e.hash} · of the crop`})));
  groups.push({title: 'source', cols: src});
  const labels = [...new Set(vs.filter(v => v.kind === 'restyle').map(v => v.label))].sort();
  for (const l of labels) {
    const cols = [];
    for (const v of vs.filter(x => x.kind === 'restyle' && x.label === l).sort(newest)) {
      cols.push(col(v, {current: v.hash === cur, picked: v.hash === pick, enhanced: enhOf(v.hash),
                        sub: v.hash + (v.base !== 'crop' ? ` · from ${isPath(v.base) ? v.base.split('/').pop() : v.base}` : '')}));
      enhOf(v.hash).forEach(e => cols.push(col(e, {title: 'enhance', sub: `${e.hash} · of ${v.hash}`})));
    }
    groups.push({title: l, cols});
  }
  const orphans = vs.filter(v => v.kind === 'enhance' && v.base !== 'crop' && !vs.some(x => x.hash === v.base));
  if (orphans.length) groups.push({title: 'enhance · source deleted', cols: orphans.map(e => col(e, {title: 'enhance', sub: `${e.hash} · of ${e.base}`}))});
  const renders = [];
  for (const k of ['plain', 'styled']) {
    const r = c.renders?.[k];
    if (r) renders.push({key: 'render-' + k, title: `render · ${k}`, sub: `${r.dpi || '?'} dpi · text ${r.sizes?.text}px${r.shrunk ? ' (shrunk)' : ''}${r.stale ? ` · stale: ${r.stale}` : ''}`,
                         path: r.path, kind: 'card', which: k, file: r.file});
  }
  groups.push({title: 'renders', cols: renders, renders: true});
  return groups;
}
const allColumns = c => columns(c).flatMap(g => g.cols);
function columnHtml(x, c) {
  const ab = state.ab, tags = [];
  if (x.styled) tags.push(['accent', x.picked ? 'styled art · picked' : 'styled art']);
  else if (x.current) tags.push(['', "the recipe's"]);
  if (x.key === (c.entry.base || state.set.base)) tags.push(['accent', 'from']);
  if (x.key === c.entry.pose) tags.push(['accent', 'pose']);
  if (x.enhanced?.length) tags.push(['good', 'enhanced']);
  const menu = items => items.length ? `<details class="menu"><summary>…</summary><div>${items.map(([a, arg, t]) => `<button data-act="${a}" data-arg="${esc(arg)}">${t}</button>`).join('')}</div></details>` : '';
  let acts = '';
  if (x.kind === 'restyle') acts = `
      <button class="small ${x.picked ? 'on' : ''}" data-act="${x.picked ? 'unpick' : 'keep'}" data-arg="${x.key}" title="${x.picked ? 'back to whatever the recipe makes' : 'make this the card\'s styled art, whatever the recipe says'}">${x.picked ? 'kept ✓' : 'keep'}</button>
      ${x.enhanced?.length ? '' : `<button class="small" data-act="enhance" data-arg="${x.key}">enhance</button>`}
      ${menu([['base', x.key, 'restyle / inspire from this'], ['pose', x.key, 'repose from this'],
              ...(x.recipe?.seed != null && c.entry.seed !== x.recipe.seed ? [['pin', x.recipe.seed, `pin its seed ${x.recipe.seed}`]] : []),
              ['promote', x.key, 'make the set style from this'], ['delete', x.key, 'delete']])}`;
  else if (x.kind === 'crop') acts = `
      ${x.enhanced?.length ? '' : `<button class="small" data-act="enhance" data-arg="crop">enhance</button>`}
      ${menu([['base', 'crop', 'restyle / inspire from this'], ['pose', 'crop', 'repose from this']])}`;
  else if (x.kind === 'enhance') acts = menu([['base', x.key, 'restyle / inspire from this'], ['pose', x.key, 'repose from this'], ['delete', x.key, 'delete']]);
  else acts = `<button class="small" data-act="render-${x.which}" data-arg="">re-render</button><button class="small" data-act="delete-render" data-arg="${esc(x.file)}">delete</button>`;
  return `
      <div class="col ${x.styled ? 'styled' : ''} ${ab.a === x.key ? 'isA' : ''} ${ab.b === x.key ? 'isB' : ''}" data-key="${esc(x.key)}">
        <div class="pic ${x.kind === 'card' ? 'card' : ''}" data-open="${esc(x.path)}"><img loading="lazy" src="${img(x.path, 640)}">
          <div class="ab"><b data-ab="a">A</b><b data-ab="b">B</b></div></div>
        <div class="title"><span>${esc(x.title)} ${tags.map(([k, t]) => `<span class="badge ${k}">${esc(t)}</span>`).join(' ')}</span><small>${esc(x.sub)}</small></div>
        ${x.recipe ? `<div class="recipe">${recipeDiff(x.recipe, c.recipe)}</div>` : ''}
        <div class="acts">${acts}</div>
      </div>`;
}
/* The generate panel's inputs: the card's remix mode and, for it, what the picture starts from. */
function generatePanel(c, cols) {
  const st = state.set, e = c.entry, style = st.style;
  const mode = e.remix || style?.remix || 'restyle';
  const setBase = st.base || 'crop', from = e.base || setBase;
  const labels = styleLabels([c]).map(([l]) => l);
  const imgOpts = (val, first) => [first, ['crop', 'crop'], ...labels.map(l => [l, `${l} · newest`]),
    ...cols.filter(x => x.v).map(x => [x.key, `${x.title}-${x.key}`])]
    .map(([v, t]) => `<option value="${esc(v)}" ${val === v ? 'selected' : ''}>${esc(t)}</option>`).join('');
  const tpl = lookTemplate(style), lookName = tpl || style?.name || '';
  const overrides = ['base', 'pose', 'seed', 'remix'].filter(k => e[k] != null);
  const takes = state.takes;
  const seedRow = e.seed != null
    ? `<input type="number" id="seed" value="${e.seed}" style="width:9em"> <button class="small" id="unpin">unpin</button> <span class="muted">pinned: the same picture every run</span>`
    : `<span class="muted">fresh each run, so every click is another take</span> <button class="small" id="pinseed" title="pin the derived seed ${c.recipe?.seed ?? ''}, the one a batch restyle from the board uses">pin the set's</button>`;
  const hint = tpl === null ? `<span class="warn">${esc(lookTitle(style))}</span>`
    : takes === 1 && e.seed != null && tpl === undefined ? (c.current ? `<span class="muted">already made: <span class="mono">${c.current.hash}</span></span>` : `<span class="muted">makes <span class="mono">${c.style_hash}</span></span>`) : '';
  const ipa = !!state.ws?.comfy?.ipadapter;
  const fromRow = title => `
        <span title="${title}">from</span><span class="row"><select id="from">${imgOpts(e.base || '', ['', `set's: ${setBase}`])}</select>
          ${c.base_missing ? `<span class="warn">no ${esc(c.base_missing)} variant on this card yet</span>` : ''}</span>`;
  const rows = mode === 'restyle' ? fromRow('the image the restyle redraws')
    : mode === 'inspire' ? fromRow('the image the new picture is inspired by: its look, palette and character, not its layout') + (ipa ? '' : `
        <span></span><span class="warn">ComfyUI has no IP-Adapter nodes: install ComfyUI_IPAdapter_plus, the SDXL ip-adapter-plus vit-h weights and the CLIP ViT-H image encoder, then restart it</span>`)
    : mode === 'repose' ? `
        <span title="the image whose OpenPose skeleton the new picture takes; only the joints are kept">pose</span><span class="row"><select id="posesel">${imgOpts(isPath(e.pose) ? 'path' : e.pose || '', ['', `the from image: ${from}`])}<option value="path" ${isPath(e.pose) ? 'selected' : ''}>an image file…</option></select>
          <input type="text" id="posepath" value="${isPath(e.pose) ? esc(e.pose) : ''}" placeholder="path to any image" style="width:20em" ${isPath(e.pose) ? '' : 'hidden'}></span>`
    : `
        <span>scene</span><span class="muted">the prompt alone; the subject line above is the only thread back to the card${e.subject ? '' : ' (none set: its name and type line stand in)'}</span>`;
  return `
    <details class="sect gen" id="gen" ${state.genOpen ? 'open' : ''}>
      <summary><h2>generate</h2><span class="muted">${esc(mode)} as ${esc(lookName || '?')}${overrides.length ? ` · this card's own ${overrides.join(', ')}` : ''}</span></summary>
      <div class="kv">
        <span>mode</span><span class="row"><span class="seg">${Object.keys(REMIX).map(m => `<button data-mode="${m}" class="${mode === m ? 'on' : ''}" ${m === 'inspire' && !ipa && mode !== m ? 'disabled' : ''} title="${esc(REMIX[m])}${m === (style?.remix || 'restyle') ? ' (the style\'s default)' : ''}${m === 'inspire' && !ipa ? ' -- needs the IP-Adapter nodes in ComfyUI' : ''}">${m}</button>`).join('')}</span><span class="muted">${esc(REMIX[mode])}</span></span>
        <span>look</span><span class="row">${lookPicker('style', st.cards_detail, style)}</span>${rows}
        <span>seed</span><span class="row">${seedRow}</span>
        <span>takes</span><span class="row">${takesPicker()}${takes > 1 ? `<label title="drafts skip the ESRGAN pass, a large share of a take's time; enhance the one you keep"><input type="checkbox" id="upscale" ${state.upscale ? 'checked' : ''}> ESRGAN pass</label>` : ''}</span>
        <span></span><span class="row"><button class="primary" data-cjob="restyle" ${tpl === null || (mode === 'inspire' && !ipa) ? 'disabled' : ''}>${esc(mode)} as ${esc(lookName || '?')}${takes > 1 ? ` ×${takes}` : ''}</button>${hint}
          ${overrides.length ? `<button class="small" id="resetentry" title="clear this card's own ${overrides.join(', ')}">reset to the set's</button>` : ''}</span>
      </div>
    </details>`;
}
async function card(r) {
  const c = cardOf(r.name);
  const code = state.set.code, st = state.set;
  if (!c) { $('#main').innerHTML = `<div class="empty">no card ${esc(r.name)} in ${esc(code)}</div>`; return; }
  if (c.error) { $('#main').innerHTML = `<h1>${esc(c.name)}</h1><div class="empty bad">${esc(c.error)}</div>`; return; }
  const groups = columns(c), cols = allColumns(c);
  const ab = state.ab;
  const find = k => cols.find(x => x.key === k);
  const A = find(ab.a), B = find(ab.b);
  const styledV = c.entry.pick ? c.picked : c.current;  // the variant the styled render uses, if made
  const styledCol = styledV && find(styledV.hash);
  const styledLine = styledV
    ? `<span class="badge accent">${esc(styledV.label)}-${styledV.hash}</span> <span class="muted">${c.entry.pick ? 'picked' : "the recipe's"}${styledCol?.enhanced?.length ? ' · enhanced' : ''}</span>
       ${styledCol?.enhanced?.length ? '' : `<button class="small" data-cjob="enhance-styled" title="an ESRGAN pass on it; the render picks the enhance up">enhance</button>`}
       ${c.entry.pick ? '<button class="small" data-act="unpick" data-arg="">unpick</button>' : ''}`
    : c.entry.pick ? `<span class="warn">picked ${c.entry.pick}, which is gone</span> <button class="small" data-act="unpick" data-arg="">unpick</button>`
    : c.style_hash ? `<span class="muted">none yet: the recipe would make <span class="mono">${c.style_hash}</span>; generate one below, or keep any variant</span>`
    : '<span class="muted">no style and no pick: the plain art</span>';
  const renders = groups.find(g => g.renders);
  $('#main').innerHTML = `
    <div class="cardhead">
      <div><h1>${esc(c.name)} <span class="muted mono">${c.number ?? ''}</span></h1>
        <div class="kv">
          <span>type</span><span>${esc(c.card.type_line)}</span>
          <span>printing</span><span class="printing"><button class="small" id="printing" title="which Scryfall printing's art this card starts from">
            ${c.entry.printing ? esc(c.entry.printing.toUpperCase()) : `${esc(c.card.set.toUpperCase())} ${esc(c.card.collector_number)} · default`} ▾</button>
            <span class="muted" id="printing-n"></span><div class="printings" id="printings" hidden></div></span>
          <span>subject</span><span><input type="text" id="subject" value="${esc(c.entry.subject || '')}" placeholder="this card's own words, ahead of the style prompt: who is in it, the pose, the scene"></span>
          ${(c.warnings || []).map(w => `<span>warning</span><span class="warn">${esc(w)}</span>`).join('')}
        </div></div>
      <div class="row" style="margin-left:auto"><a class="pill" href="#/set/${esc(code)}">← ${esc(code)}</a><a class="pill" href="#/set/${esc(code)}/lab">lab</a></div>
    </div>
    ${generatePanel(c, cols)}
    <section class="sect">
      <h2>images</h2>
      ${A && B ? abPanel(A, B) : `<p class="muted">Pick <b>A</b> and <b>B</b> on two images to wipe between them.</p>`}
      <div class="groups">${groups.filter(g => !g.renders && g.cols.length).map(g => `<div class="group"><h3>${esc(g.title)}</h3><div class="cols">${g.cols.map(x => columnHtml(x, c)).join('')}</div></div>`).join('')
        || '<div class="empty">no images yet: fetch the crop (mint art) or generate one</div>'}</div>
    </section>
    <section class="sect">
      <h2>card</h2>
      <div class="kv">
        <span title="the image a styled render uses: the card's pick, else the variant its recipe hashes to">styled art</span><span class="row">${styledLine}</span>
        <span>renders</span><span class="row">
          <button data-cjob="render-plain">render plain</button>
          <button data-cjob="render-styled" ${styledV || st.style ? '' : 'disabled'} title="${styledV ? `the card with ${styledV.label}-${styledV.hash}` : st.style ? 'no styled art yet: the set\'s art_filter stands in' : 'nothing styled to render'}">render styled</button>
          <select id="dpi">${[300, 600, 1200].map(d => `<option ${state.dpi === d ? 'selected' : ''}>${d}</option>`).join('')}</select><span class="muted">dpi</span></span>
      </div>
      ${renders.cols.length ? `<div class="cols renders">${renders.cols.map(x => columnHtml(x, c)).join('')}</div>` : ''}
    </section>`;
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
  document.onclick = () => {  // anywhere else closes the printings and any open column menu
    const box = $('#printings'); if (box) box.hidden = true;
    document.querySelectorAll('details.menu[open]').forEach(d => { d.open = false; });
  };
  document.querySelectorAll('details.menu').forEach(d => d.onclick = e => e.stopPropagation());
  document.onkeydown = e => { if (e.key === 'Escape' && $('#printings') && !$('#printings').hidden) { $('#printings').hidden = true; e.preventDefault(); } };
  $('#subject').onchange = e => put({subject: e.target.value || null});
  $('#dpi').onchange = e => { state.dpi = +e.target.value; };
  // the generate panel
  $('#gen').ontoggle = e => { state.genOpen = e.target.open; };
  document.querySelectorAll('[data-mode]').forEach(b => b.onclick = () => put({remix: b.dataset.mode === (st.style?.remix || 'restyle') ? null : b.dataset.mode}));
  $('#style').onchange = e => { state.style = e.target.value; card(r); };
  if ($('#from')) $('#from').onchange = e => put({base: e.target.value || null});
  if ($('#posesel')) $('#posesel').onchange = e => {
    if (e.target.value === 'path') { $('#posepath').hidden = false; $('#posepath').focus(); }
    else put({pose: e.target.value || null});
  };
  if ($('#posepath')) $('#posepath').onchange = e => { if (e.target.value.trim()) put({pose: e.target.value.trim()}); };
  if ($('#seed')) $('#seed').onchange = e => put({seed: e.target.value === '' ? null : +e.target.value});
  if ($('#unpin')) $('#unpin').onclick = () => put({seed: null});
  if ($('#pinseed')) $('#pinseed').onclick = () => put({seed: c.recipe?.seed ?? 1 + Math.floor(Math.random() * 2 ** 31)});
  if ($('#resetentry')) $('#resetentry').onclick = () => put({base: null, pose: null, seed: null, remix: null});
  bindTakes();
  $('#takes').addEventListener('change', () => card(r));  // the ESRGAN checkbox shows for drafts
  if ($('#upscale')) $('#upscale').onchange = e => { state.upscale = e.target.checked; };
  document.querySelectorAll('[data-ab]').forEach(b => b.onclick = e => {
    e.stopPropagation(); const key = b.closest('.col').dataset.key;
    ab[b.dataset.ab] = ab[b.dataset.ab] === key ? null : key; card(r);
  });
  const origin = `card page: ${c.name}`;
  const render = styled => submit({kind: 'render', set: code, names: [c.name], styled, dpi: state.dpi}, origin);
  document.querySelectorAll('[data-cjob]').forEach(b => b.onclick = () => {
    const j = b.dataset.cjob, names = [c.name];
    if (j === 'restyle') submit({kind: 'restyle', set: code, names, template: lookTemplate(st.style), takes: state.takes,
                                 upscale: state.takes > 1 ? state.upscale : undefined,
                                 seed: c.entry.seed == null ? 1 + Math.floor(Math.random() * 2 ** 31) : undefined}, origin + ' (generate)');
    else if (j === 'enhance-styled') submit({kind: 'enhance', set: code, names, base: styledV.hash}, origin);
    else if (j === 'render-plain') render(false);
    else if (j === 'render-styled') render(true);
  });
  document.querySelectorAll('.col [data-open]').forEach(p => p.onclick = () => { V.fromPage = true; location.hash = colHash(code, c.name, p.closest('.col').dataset.key); });
  if (r.key) { const slides = columnSlides(c); openViewer('columns', slides, slides.findIndex(x => x.key === r.key)); }
  document.querySelectorAll('[data-act]').forEach(b => b.onclick = async () => {
    const act = b.dataset.act, arg = b.dataset.arg, names = [c.name];
    if (act === 'keep') put({pick: arg});
    else if (act === 'unpick') put({pick: null});
    else if (act === 'enhance') submit({kind: 'enhance', set: code, names, base: arg}, origin);
    else if (act === 'base') put({base: arg === 'crop' ? null : arg});
    else if (act === 'pose') put({pose: arg});
    else if (act === 'pin') put({seed: +arg});
    else if (act === 'delete-render') {
      if (!confirm(`Delete the render ${arg}? The PNG is removed from out/${code.toLowerCase()}/; re-render makes it again.`)) return;
      api(`/api/sets/${code}/renders/${encodeURIComponent(arg)}`, {method: 'DELETE'}).then(() => { toast(`deleted ${arg}`); refresh(); }).catch(e => toast(e.message, true));
    }
    else if (act === 'delete') {
      const v = c.variants.find(x => x.hash === arg);
      const used = v.hash === c.entry.pick ? ' (the picked styled art)' : v.hash === c.current?.hash ? " (the recipe's)" : '';
      if (!confirm(`Delete ${v.label}-${arg}${used}? The file is removed; a restyle makes it again.`)) return;
      api(`/api/sets/${code}/cards/${encodeURIComponent(c.name)}/variants/${arg}`, {method: 'DELETE'}).then(() => { toast(`deleted ${v.label}-${arg}`); refresh(); }).catch(e => toast(e.message, true));
    }
    else if (act === 'promote') api(`/api/sets/${code}/promote`, {method: 'POST', body: {name: c.name, hash: arg}}).then(() => { toast('set style updated'); refresh(); }).catch(e => toast(e.message, true));
    else if (act === 'render-plain') render(false);
    else if (act === 'render-styled') render(true);
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
      <span class="muted">drag the line · wheel / pinch to zoom · drag to pan when zoomed</span>
    </div>
    <div class="stage ${cardish ? 'card' : ''} ${ab.zoom > 1 ? 'zoomed' : ''}" id="stage">
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
    stage.classList.toggle('zoomed', ab.zoom > 1);
  };
  const zoomAt = (z, px, py) => {
    z = Math.min(8, Math.max(1, z));
    ab.x = px - (px - ab.x) * z / ab.zoom; ab.y = py - (py - ab.y) * z / ab.zoom; ab.zoom = +z.toFixed(2);
    if (ab.zoom === 1) { ab.x = ab.y = 0; } $('#zoom').value = ab.zoom; apply();
  };
  $('#wipe').oninput = e => { ab.wipe = +e.target.value; apply(); };
  $('#zoom').oninput = e => { ab.zoom = +e.target.value; apply(); };
  $('#fit').onclick = () => { ab.zoom = 1; ab.x = ab.y = 0; $('#zoom').value = 1; apply(); };
  $('#blind').onchange = e => { ab.blind = e.target.checked; ab.swap = Math.random() < 0.5; card(r); };
  if ($('#reveal')) $('#reveal').onclick = () => { toast(`left was ${ab.swap ? 'B' : 'A'}: ${(ab.swap ? B : A).title} ${(ab.swap ? B : A).sub}`); ab.blind = false; card(r); };
  const ptrs = new Map(); let drag = null, pinch = null;
  const wipeTo = x => { const r = stage.getBoundingClientRect(); ab.wipe = Math.round(Math.min(100, Math.max(0, 100 * (x - r.left) / r.width))); $('#wipe').value = ab.wipe; apply(); };
  stage.onpointerdown = e => {
    stage.setPointerCapture(e.pointerId); ptrs.set(e.pointerId, {x: e.clientX, y: e.clientY});
    if (ptrs.size === 2) { const [a, b] = [...ptrs.values()]; pinch = {d: Math.hypot(a.x - b.x, a.y - b.y), z: ab.zoom}; drag = null; }
    else if (ab.zoom > 1) drag = {x: e.clientX - ab.x, y: e.clientY - ab.y};
    else { drag = 'wipe'; wipeTo(e.clientX); }
  };
  stage.onpointermove = e => {
    if (!ptrs.has(e.pointerId)) return;
    ptrs.set(e.pointerId, {x: e.clientX, y: e.clientY});
    if (pinch && ptrs.size === 2) {
      const [a, b] = [...ptrs.values()], r = stage.getBoundingClientRect();
      zoomAt(pinch.z * Math.hypot(a.x - b.x, a.y - b.y) / pinch.d, (a.x + b.x) / 2 - r.left, (a.y + b.y) / 2 - r.top);
    } else if (drag === 'wipe') wipeTo(e.clientX);
    else if (drag) { ab.x = e.clientX - drag.x; ab.y = e.clientY - drag.y; apply(); }
  };
  stage.onpointerup = stage.onpointercancel = e => { ptrs.delete(e.pointerId); if (ptrs.size < 2) pinch = null; if (!ptrs.size) drag = null; };
  stage.onwheel = e => {
    e.preventDefault();
    const rect = stage.getBoundingClientRect();
    zoomAt(ab.zoom * (e.deltaY < 0 ? 1.15 : 1 / 1.15), e.clientX - rect.left, e.clientY - rect.top);
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
        <div class="labwrap"><div class="labgrid" style="grid-template-columns: 120px repeat(${cols.length}, minmax(140px, 1fr))">
          <div class="head"></div>${cols.map(v => `<div class="head"><b>${esc(v.label)}</b> <span class="mono">${v.hash}</span><div class="mono muted" style="font-size:.85em">${esc(labSummary(v.recipe, st))}</div></div>`).join('')}
          ${probes.map(c => `<div class="head">${esc(c.name)}</div>${cols.map(v => {
            const mine = (c.variants || []).find(x => x.label === v.label && sameKnobs(x.recipe, v.recipe));
            return `<div class="cell">${mine ? `<img loading="lazy" src="${img(mine.path, 320)}" data-open="${esc(mine.path)}"><div class="cap"><span>${mine.hash}${c.current?.hash === mine.hash ? ' · current' : ''}</span><button class="small" data-promote="${esc(c.name)}|${mine.hash}">use for set</button></div>` : '<div class="cap muted">—</div>'}</div>`;
          }).join('')}`).join('')}
        </div></div>
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
    submit({kind: 'restyle', set: code, names: L.probes, style: over, label: L.label || undefined, upscale: $('#upscale').checked}, `${code} recipe lab`);
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
const KNOBS = ['control', 'control_strength', 'control_end', 'repose_strength', 'repose_end', 'inspire_weight', 'inspire_end', 'inspire_type', 'remix', 'denoise', 'steps', 'cfg', 'sampler', 'scheduler', 'checkpoint', 'controlnet', 'loras', 'width', 'height', 'grayscale_source', 'negative'];
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
  // the frame's dressing: one slider per knob, saved to the set file as it settles
  const knobs = state.ws.frame_fields || [], fr = st.frame || {};
  $('#main').innerHTML = `
    <div class="row"><h1>${esc(code)} <span class="muted">frame</span></h1><a class="pill" href="#/set/${esc(code)}">← ${esc(code)}</a>
      <select id="fcard">${st.cards_detail.map(x => `<option ${x.name === F.name ? 'selected' : ''}>${esc(x.name)}</option>`).join('')}</select></div>
    <div class="panel" style="margin-bottom:16px">
      <h2>frame knobs</h2>
      ${knobsHtml(knobs, fr)}
      <div class="toolbar"><span class="muted">each a strength, 0 = off; saved to the set's frame block as you let go, and a proof shows them. The css below can still override any (<span class="mono">--art-bevel</span> and so on)</span>
        <button id="knobreset" class="small" ${knobs.every(f => (fr[f.name] ?? f.default) === f.default) ? 'disabled' : ''}>reset to defaults</button></div>
    </div>
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
  const putFrame = body => api(`/api/sets/${code}/frame`, {method: 'PUT', body})
    .then(d => { st.frame = d; toast('frame knobs saved'); if (route().view === 'frame') frame(); })  // not if the page moved on meanwhile
    .catch(e => toast(e.message, true));
  bindKnobs((k, v) => putFrame({[k]: v}));
  $('#knobreset').onclick = () => putFrame(Object.fromEntries(knobs.map(f => [f.name, f.default])));
  const saveCss = () => api(`/api/sets/${code}/css`, {method: 'PUT', body: {css: $('#css').value}}).then(() => { F.css = $('#css').value; st.css = F.css; toast('css saved'); });
  $('#savecss').onclick = () => saveCss().catch(e => toast(e.message, true));
  $('#proof').onclick = () => saveCss().then(() => submit({kind: 'render', set: code, names: [F.name], styled: false, dpi: 300, sub: 'proof'}, `${code} frame page`)).catch(e => toast(e.message, true));
  $('#themes').onclick = () => submit({kind: 'themes', set: code, names: [F.name]}, `${code} frame page`);
  $('#getscan').onclick = () => api(`/api/sets/${code}/cards/${encodeURIComponent(F.name)}/scan`, {method: 'POST'}).then(d => { F.scan = d.path; frame(); }).catch(e => toast(e.message, true));
  $('#op').oninput = e => { F.opacity = +e.target.value; const o = $('#ours'); if (o) o.style.opacity = 1 - F.opacity / 100; };
  document.querySelectorAll('[data-open]').forEach(p => p.onclick = () => window.open(file(p.dataset.open), '_blank'));
}

/* --- the frame knobs: a slider per sets.Frame field, on the frame page and the styles page --- */
function knobsHtml(fields, values) {
  const kv = f => values?.[f.name] ?? f.default;
  return `<div class="knobs">${fields.map(f => `<label title="${esc(FIELD_HELP[f.name] || '')}"><span class="${kv(f) !== f.default ? 'changed' : ''}">${esc(f.name)}</span>
      <input type="range" data-fk="${f.name}" min="0" max="1" step="0.05" value="${kv(f)}"><output>${kv(f)}</output></label>`).join('')}</div>`;
}
function bindKnobs(onchange) {
  document.querySelectorAll('[data-fk]').forEach(el => {
    el.oninput = () => { el.nextElementSibling.textContent = el.value; };
    el.onchange = () => onchange(el.dataset.fk, +el.value);
  });
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
  color_match: 'after the picture is made, move its colours back to the base\'s by this much (0-1): the fix for a faithful restyle whose palette drifted; 0 = off',
  clip_skip: '1 = the checkpoint\'s CLIP; 2 for Pony-family checkpoints', remix: 'restyle: redraw the base; repose: a new picture holding only the pose image\'s skeleton; new: from the prompt alone; inspire: a new picture with the base as an IP-Adapter reference',
  repose_strength: 'repose only: how hard the OpenPose skeleton is held (0-1)', repose_end: 'repose only: the fraction of the steps the skeleton is held for',
  inspire_weight: 'inspire only: the reference image\'s weight against the words (0-2; 0.6-0.8 on base-SDXL checkpoints, 0.35-0.5 on Pony, which burns above that)', inspire_end: 'inspire only: the fraction of the steps the image is read for',
  inspire_type: 'inspire only: standard; prompt first (the words settle the composition before the image weighs in); style (its look, not its subject)',
  // the frame's dressing (sets.Frame)
  watermark: 'the set symbol, faint, behind the rules text', art_bevel: 'a dark line and a light pinline around the art window',
  box_grain: 'linen grain over the bars and the text box; 1 is the text box\'s old look', foil_stamp: 'the holofoil oval under the text box, on rares and mythics',
  rarity_tint: 'the title and type bars tinted with the rarity\'s colour: silver, gold, orange',
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
          <select id="tpl">${st.style ? '' : '<option value="">choose a template…</option>'}${(E.styles || []).map(t => `<option value="${esc(t.name)}" ${t.name === st.style?.name ? 'selected' : ''}>${esc(t.name)}${t.builtin ? ' (built-in)' : ''}${t.private ? ' (private)' : ''}${t.sets.length ? ' · ' + t.sets.join(' ') : ''}</option>`).join('')}</select>
          <label title="the template's .css becomes the set's, replacing ${esc(code.toLowerCase())}.css"><input type="checkbox" id="tplcss" ${st.css ? '' : 'checked'}> its css too</label>
          <button id="applytpl" ${E.styles?.length && st.style ? '' : 'disabled'}>apply</button>
        </div>
        ${st.style && E.knobs ? `<div class="form">${styleForm(fields, E.values, f => JSON.stringify(E.values[f.name] ?? f.default) !== JSON.stringify(st.style[f.name] ?? f.default))}
          <label></label><div class="row"><button class="primary" id="saveknobs">save style</button><button id="resetknobs" class="small">reset</button>
            <span class="muted">changed knobs are lit; saving gives every card a new recipe hash</span></div></div>` : ''}
      </div>
      <div class="panel">
        <h2>cards <span class="muted" style="text-transform:none">${st.cards_detail.length}</span></h2>
        <div class="tablewrap"><table class="cards">
          <thead><tr><th title="collector number">#</th><th>card</th><th title="what the picture is of; goes ahead of the style prompt">subject</th><th title="replaces the printed flavor text">flavor</th>
            <th title="your own image instead of Scryfall's: a path under the workspace">art</th><th title="per-card CSS filter for --styled">art_filter</th><th title="pin this card's seed">seed</th><th title="what a restyle keeps of the base">remix</th><th>printing · base · pose</th><th></th></tr></thead>
          <tbody>${st.cards_detail.map((c, i) => `<tr data-name="${esc(c.name)}">
            <td><input type="number" class="num" data-k="number" value="${entryOf(c).number ?? ''}"></td>
            <td class="who"><a href="#/set/${esc(code)}/card/${encodeURIComponent(c.name)}">${esc(c.name)}</a>${c.error ? `<small class="err">${esc(c.error)}</small>` : `<small class="muted">${esc(c.card?.type_line || '')}</small>`}</td>
            <td><input type="text" data-k="subject" value="${esc(entryOf(c).subject || '')}"></td>
            <td><input type="text" data-k="flavor" value="${esc(entryOf(c).flavor || '')}"></td>
            <td><input type="text" data-k="art" value="${esc(entryOf(c).art || '')}"></td>
            <td><input type="text" data-k="art_filter" value="${esc(entryOf(c).art_filter || '')}"></td>
            <td><input type="number" class="num seed" data-k="seed" value="${entryOf(c).seed ?? ''}" placeholder="${c.recipe?.seed ?? ''}" title="pinned seed; the placeholder is the derived one"></td>
            <td><select data-k="remix">${remixOpts(c)}</select></td>
            <td class="picks">${entryOf(c).printing ? `<span class="badge accent">${esc(entryOf(c).printing)}</span>` : ''}${entryOf(c).base ? `<span class="badge accent">base ${esc(entryOf(c).base)}</span>` : ''}${entryOf(c).pose ? `<span class="badge accent" title="${esc(entryOf(c).pose)}">pose ${esc(short(entryOf(c).pose.split('/').pop()))}</span>` : ''}
              ${!entryOf(c).printing && !entryOf(c).base && !entryOf(c).pose ? `<a class="muted" href="#/set/${esc(code)}/card/${encodeURIComponent(c.name)}" title="the printing, the restyle base and the pose image are picked in the card view">pick…</a>` : ''}</td>
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
  // with no style block the picker starts on a placeholder, so apply waits for a real choice and always asks:
  // the list puts private templates first, and one click used to install the first of them unasked
  if (!st.style) $('#tpl').onchange = () => { $('#applytpl').disabled = !$('#tpl').value; };
  $('#applytpl').onclick = () => {
    const t = $('#tpl').value;
    if (!t) return;
    if (!confirm(st.style ? `Replace the style block of ${code} (${st.style.name}) with the template ${t}?` : `Style ${code} as the template ${t}?`)) return;
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
  if (!T) T = state.styles = {list: null, name: null, values: null, css: '', private: false, keep: [], draft: false, frame: null};
  if (!T.list) T.list = await api('/api/styles');
  const cur = r.name ? T.list.find(t => t.name === r.name) : null;
  if (r.name && !cur) { $('#main').innerHTML = `<div class="empty bad">no template ${esc(r.name)}</div>`; return; }
  if (cur && T.name !== cur.name) {
    T.name = cur.name; T.draft = false; T.values = {...cur.style}; T.css = cur.css || ''; T.private = cur.private; T.keep = Object.keys(cur.style);
    T.frame = cur.frame ? {...cur.frame} : null;
  }
  const knobs = state.ws.frame_fields || [];
  const frameSlim = fr => Object.fromEntries(knobs.filter(f => fr && fr[f.name] !== undefined && fr[f.name] !== f.default).map(f => [f.name, fr[f.name]]));
  if (!cur && !T.draft) T.name = null;
  const editing = cur || T.draft;
  const lit = f => JSON.stringify(T.values?.[f.name] ?? f.default) !== JSON.stringify(f.default);
  const asFile = cur ? Object.fromEntries(Object.entries(cur.style).filter(([k]) => k !== 'name')) : null;
  const dirty = cur && (JSON.stringify(slimStyle(fields, T.values, T.keep)) !== JSON.stringify(asFile) || T.css !== (cur.css || '') || T.private !== cur.private
    || JSON.stringify(frameSlim(T.frame)) !== JSON.stringify(frameSlim(cur.frame)));
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
          <label title="the frame's dressing that goes with the style: a set that takes the template takes these knobs too. All at their defaults = none saved">frame</label>${knobsHtml(knobs, T.frame)}
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
    T.values.prompt = ''; T.css = ''; T.private = false; T.keep = []; T.frame = null;
    if (location.hash !== '#/styles') location.hash = '#/styles'; else styles({view: 'styles'});
  };
  if (!editing) return;
  bindStyleForm(fields, T.values, () => styles(r));
  bindKnobs((k, v) => { T.frame = {...(T.frame || {}), [k]: v}; styles(r); });
  $('#tprivate').onchange = e => { T.private = e.target.checked; styles(r); };
  $('#tcss').onchange = e => { T.css = e.target.value; };
  if ($('#tname')) $('#tname').onchange = e => { T.name = e.target.value.trim(); };
  const save = (name, then) => {
    if (!name) { toast('a template needs a name', true); return; }
    T.css = $('#tcss').value;
    const fr = frameSlim(T.frame);
    api(`/api/styles/${encodeURIComponent(name)}`, {method: 'PUT', body: {style: slimStyle(fields, T.values, T.keep), css: T.css, private: T.private, frame: Object.keys(fr).length ? fr : null}})
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

/* --- pdfs: a set's print runs and `mint impose` file --------------------------------------- */
/* The list on one side, the picked one's pages on the other, as images the server renders
   (pdftoppm), so it works on a phone too. The file itself: the browser's own viewer in a tab,
   a download, or an export -- a copy into the workspace's export_dir (the Desktop) for another
   PDF app to print from. */
const fmtSize = b => b >= 1e9 ? `${(b / 1e9).toFixed(2)} GB` : b >= 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${Math.round(b / 1e3)} KB`;
async function pdfs(r) {
  const st = state.set, code = st.code;
  const d = await api(`/api/sets/${code}/pdfs`);
  const list = d.pdfs, cur = list.find(p => p.file === r.name) || list[0];
  const P = state.pdfs || (state.pdfs = {zoom: false});
  const pageW = P.zoom ? 1600 : 800;
  $('#main').innerHTML = `
    <div class="row"><h1>${esc(code)} <span class="muted">pdfs</span></h1><a class="pill" href="#/set/${esc(code)}">← ${esc(code)}</a>
      <span class="muted">print runs from the board land in <span class="mono">out/${esc(code.toLowerCase())}/print/</span>; <span class="mono">mint impose</span>'s file is listed too</span></div>
    ${list.length ? `<div class="pdfs">
      <div class="pdflist">${list.map(p => `<a class="pdf ${p === cur ? 'on' : ''}" href="#/set/${esc(code)}/pdfs/${encodeURIComponent(p.file)}">
        <b>${esc(p.file)}</b><small class="muted">${p.pages != null ? `${p.pages} page${p.pages === 1 ? '' : 's'} · ` : ''}${fmtSize(p.size)} · ${new Date(p.mtime * 1000).toLocaleString()} · ${esc(p.origin)}</small></a>`).join('')}</div>
      <div class="pdfview">
        <div class="toolbar">
          <b class="mono">${esc(cur.file)}</b><span class="muted">${cur.pages != null ? `${cur.pages} page${cur.pages === 1 ? '' : 's'} · ` : ''}${fmtSize(cur.size)}</span><span class="sep"></span>
          <a class="pill" href="${file(cur.path)}" target="_blank" title="the file in the browser's own PDF viewer, in a new tab">open</a>
          <a class="pill" href="${file(cur.path)}&download=1" download="${esc(cur.file)}" title="save the file with the browser (to this device)">download</a>
          <button class="primary" id="pdfexport" title="copy the file to ${esc(d.export_dir)} on the workbench's machine, for another PDF app to print">export to ${esc(d.export_dir.replace(/^\/home\/[^/]+/, '~'))}</button>
          <span class="sep"></span>
          <button id="pdfzoom" class="${P.zoom ? 'on' : ''}" title="pages at twice the width">${P.zoom ? 'smaller' : 'larger'}</button>
          <button class="danger small" id="pdfdel" style="margin-left:auto">delete</button>
        </div>
        ${cur.pages == null ? `<div class="empty">poppler (pdfinfo / pdftoppm) is not installed on the workbench's machine, so the pages cannot be shown here: <a href="${file(cur.path)}" target="_blank">open</a> the file instead</div>`
          : `<div class="pages ${P.zoom ? 'zoom' : ''}">${Array.from({length: cur.pages}, (_, i) => `<figure class="page">
              <a href="${file(cur.path)}#page=${i + 1}" target="_blank" title="page ${i + 1} in the browser's viewer"><img loading="lazy" alt="page ${i + 1}" src="/pdfpage?path=${encodeURIComponent(cur.path)}&n=${i + 1}&w=${pageW}"></a>
              <figcaption class="muted">page ${i + 1} of ${cur.pages}</figcaption></figure>`).join('')}</div>`}
      </div>
    </div>` : `<div class="empty">no PDFs yet: run a print run from the board (stock "PDF only" makes the file and prints nothing), or <span class="mono">mint impose --out out/${esc(code.toLowerCase())}.pdf out/${esc(code.toLowerCase())}/*.png</span></div>`}`;
  if (!cur) return;
  const doExport = force => api(`/api/sets/${code}/pdfs/export`, {method: 'POST', body: {file: cur.file, force}})
    .then(x => toast(`exported to ${x.exported}`))
    .catch(e => {
      if (/already there/.test(e.message) && !force) { if (confirm(`${e.message.replace(' is already there', '')} is already there. Replace it?`)) doExport(true); }
      else toast(e.message, true);
    });
  $('#pdfexport').onclick = () => doExport(false);
  $('#pdfzoom').onclick = () => { P.zoom = !P.zoom; pdfs(r); };
  $('#pdfdel').onclick = () => {
    if (!confirm(`Delete ${cur.file}? The renders it was made from stay.`)) return;
    api(`/api/sets/${code}/pdfs/${encodeURIComponent(cur.file)}`, {method: 'DELETE'}).then(() => { toast(`deleted ${cur.file}`); location.hash = `#/set/${code}/pdfs`; if (route().name === undefined) pdfs(route()); }).catch(e => toast(e.message, true));
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
      <div class="desc">${j.params?.what ? `<div>${esc(j.params.what)}</div>` : ''}
        <div class="muted">${j.params?.origin ? `from <b>${esc(j.params.origin)}</b>` : 'from the API'}${j.params?.dest ? ` · to <span class="mono">${esc(j.params.dest)}</span>` : ''}</div></div>
      ${j.items?.length ? `<div class="items">${j.items.map(itemHtml).join('')}</div>` : ''}
      ${j.log.length ? `<details class="log"><summary class="muted">log</summary><pre>${esc(j.log.slice(-40).join('\n'))}</pre></details>` : ''}
    </div>`).join('') || '<div class="empty">no jobs yet</div>');
  document.querySelectorAll('[data-cancel]').forEach(b => b.onclick = () => api(`/api/jobs/${b.dataset.cancel}/cancel`, {method: 'POST'}).then(jobs));
  // the preview loads on the first hover, not with the page
  document.querySelectorAll('.it[data-src]').forEach(a => a.addEventListener('mouseenter', () => {
    const im = a.querySelector('img'); if (im && !im.src) im.src = a.dataset.src;
  }, {once: true}));
}

/* One thing a job made: a link to that image on the card page, the picture itself on hover. */
function itemHtml(it) {
  if (it.kind === 'pdf') return `<a class="it" href="#/set/${esc(it.set)}/pdfs/${encodeURIComponent(it.file)}">${esc(it.file)} <span class="mono muted">${esc(it.name)}</span></a>`;
  const href = it.key ? colHash(it.set, it.name, it.key) : `#/set/${esc(it.set)}/card/${encodeURIComponent(it.name)}`;
  const what = it.label ? `${it.label}-${it.key}` : it.file || it.kind || '';
  return `<a class="it ${it.kind === 'render' || it.kind === 'theme' ? 'card' : ''}" href="${href}" ${it.path ? `data-src="${img(it.path, 320)}"` : ''}>
      ${esc(it.name)} <span class="mono muted">${esc(what)}</span>${it.path ? '<span class="peek"><img alt=""></span>' : ''}</a>`;
}

/* --- boot ------------------------------------------------------------------------------- */
api('/api/jobs').then(list => { list.forEach(j => state.jobs[j.id] = j); renderJobstrip(); }).catch(() => {});
connect();
go();
/* Installable: the service worker keeps the page shell so the home-screen app opens without the
   server (and says so). Browsers only register one on a secure origin -- localhost, or https --
   so over plain http on the LAN this is a no-op and the page works as a bookmark. */
if (!STATIC && 'serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
