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

const state = {ws: null, set: null, setCode: null, jobs: {}, sel: new Set(), mode: 'styled',
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
  state.set = await api(`/api/sets/${encodeURIComponent(code)}`); state.setCode = state.set.code;
}
const cardOf = name => state.set && state.set.cards_detail.find(c => c.name === name);

/* --- routing --------------------------------------------------------------- */
function route() {
  const h = location.hash.replace(/^#\/?/, '');
  const p = h.split('/').map(decodeURIComponent);
  if (!p[0]) return {view: 'home'};
  if (p[0] === 'jobs') return {view: 'jobs'};
  if (p[0] === 'set') return {view: p[2] || 'board', code: p[1], name: p[3]};
  return {view: 'home'};
}
async function go() {
  const r = route();
  try {
    if (!state.ws) await loadWorkspace();
    if (r.code && (!state.set || state.set.code.toLowerCase() !== r.code.toLowerCase())) { await loadSet(r.code); state.sel.clear(); }
    const views = {home, board, card, lab, frame, jobs};
    (views[r.view] || home)(r);
    renderNav();
  } catch (e) { $('#main').innerHTML = `<div class="empty bad">${esc(e.message)}</div>`; }
}
window.addEventListener('hashchange', go);

function renderNav() {
  const r = route();
  $('#setnav').innerHTML = (state.ws?.sets || []).map(s =>
    `<a href="#/set/${esc(s.code)}" class="${r.code && r.code.toLowerCase() === s.code.toLowerCase() ? 'on' : ''}">${esc(s.code)}</a>`).join('');
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
  const ws = state.ws;
  $('#main').innerHTML = `
    <h1>Sets</h1>
    <p class="muted">${esc(ws.home)} · ${ws.cards.count.toLocaleString()} cards on file · you are <b>${esc(ws.maker)}</b> (${esc(ws.maker_code)})</p>
    <div class="setlist">${ws.sets.map(s => `
      <a class="setcard" href="#/set/${esc(s.code)}">
        <h3>${esc(s.code)} <span class="muted">${esc(s.name)}</span></h3>
        <div class="meta">${s.cards} cards${s.style ? ` · style <b>${esc(s.style)}</b>` : ' · no style'}${s.error ? `<div class="bad">${esc(s.error)}</div>` : ''}</div>
      </a>`).join('') || '<div class="empty">no set files in sets/ — <code>mint newset</code> makes one</div>'}
    </div>`;
}

/* --- set board ------------------------------------------------------------------ */
function badges(c) {
  const b = [];
  if (c.error) b.push(['bad', 'not found']);
  (c.warnings || []).forEach(w => b.push(['warn', w.includes('Universes Beyond') ? 'UB art' : w]));
  if (state.set.style && !c.current) b.push(['', 'no restyle']);
  if (c.renders?.plain?.shrunk || c.renders?.styled?.shrunk) b.push(['warn', 'text shrunk']);
  if (c.entry.art) b.push(['accent', 'own art']);
  if (c.entry.printing) b.push(['accent', c.entry.printing]);
  if (c.entry.base) b.push(['accent', 'base ' + c.entry.base]);
  if (c.entry.seed != null) b.push(['accent', 'seed pinned']);
  if (!c.renders?.plain && !c.renders?.styled) b.push(['', 'not rendered']);
  return b.map(([k, t]) => `<span class="badge ${k}">${esc(t)}</span>`).join('');
}
function tilePic(c) {
  const m = state.mode;
  if (m === 'plain' || m === 'styled') {
    const r = c.renders?.[m];
    if (r) return `<div class="pic"><img loading="lazy" src="${img(r.path, 320)}"></div>`;
    const src = c[m];
    return src ? `<div class="pic art"><img loading="lazy" src="${img(src.path, 320)}"></div>` : `<div class="pic art"><div class="none">no image yet</div></div>`;
  }
  const src = c.styled || c.plain;
  return src ? `<div class="pic art"><img loading="lazy" src="${img(src.path, 320)}"></div>` : `<div class="pic art"><div class="none">crop not fetched</div></div>`;
}
function board() {
  const st = state.set, code = st.code;
  const sel = state.sel, n = sel.size, names = [...sel];
  const filt = state.filter || '';
  const cards = st.cards_detail.filter(c => !filt || badges(c).includes(`>${filt}<`) || (filt === 'no restyle' && !c.current));
  $('#main').innerHTML = `
    <div class="row"><h1>${esc(code)} <span class="muted">${esc(st.name)}</span></h1>
      <a class="pill" href="#/set/${esc(code)}/lab">recipe lab</a><a class="pill" href="#/set/${esc(code)}/frame">frame</a>
      <span class="muted">${st.cards_detail.length} cards${st.style ? ` · style ${esc(st.style.name)}` : ''} · <span class="mono">${esc(st.path)}</span></span></div>
    <div class="toolbar">
      <span class="seg">${['styled', 'plain', 'art'].map(m => `<button data-mode="${m}" class="${state.mode === m ? 'on' : ''}">${m}</button>`).join('')}</span>
      <span class="sep"></span>
      <select id="filter"><option value="">all cards</option>${['no restyle', 'not rendered', 'text shrunk', 'UB art', 'own art'].map(f => `<option ${filt === f ? 'selected' : ''}>${f}</option>`).join('')}</select>
      <span class="sep"></span>
      <span class="muted">${n ? `${n} selected` : 'all cards'}:</span>
      <button data-job="render-plain">render plain</button>
      <button data-job="render-styled" ${st.style ? '' : 'disabled'}>render styled</button>
      <button data-job="enhance">enhance</button>
      <button data-job="restyle" ${st.style ? '' : 'disabled'}>restyle</button>
      <select id="dpi"><option>300</option><option>600</option><option selected>1200</option></select><span class="muted">dpi</span>
      ${n ? '<button id="clearsel" class="small">clear selection</button>' : ''}
    </div>
    <div class="grid">${cards.map(c => `
      <div class="tile ${sel.has(c.name) ? 'sel' : ''}" data-name="${esc(c.name)}">
        ${tilePic(c)}
        <div class="name"><b>${esc(c.name)}</b><span class="muted mono">${c.number ?? ''}</span></div>
        <div class="badges">${badges(c)}</div>
      </div>`).join('') || '<div class="empty">nothing matches</div>'}
    </div>`;
  document.querySelectorAll('[data-mode]').forEach(b => b.onclick = () => { state.mode = b.dataset.mode; board(); });
  $('#filter').onchange = e => { state.filter = e.target.value; board(); };
  if ($('#clearsel')) $('#clearsel').onclick = () => { sel.clear(); board(); };
  document.querySelectorAll('.tile').forEach(t => {
    t.onclick = e => {
      const name = t.dataset.name;
      if (e.shiftKey || e.ctrlKey || e.metaKey) { sel.has(name) ? sel.delete(name) : sel.add(name); board(); }
      else location.hash = `#/set/${code}/card/${encodeURIComponent(name)}`;
    };
  });
  document.querySelectorAll('[data-job]').forEach(b => b.onclick = () => {
    const dpi = +$('#dpi').value, list = n ? names : null;
    const jobs = {
      'render-plain': {kind: 'render', set: code, names: list, styled: false, dpi},
      'render-styled': {kind: 'render', set: code, names: list, styled: true, dpi},
      'enhance': {kind: 'enhance', set: code, names: list, base: 'crop'},
      'restyle': {kind: 'restyle', set: code, names: list},
    };
    submit(jobs[b.dataset.job]);
  });
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
                         path: c.crop, kind: 'crop', acts: [['enhance', 'crop'], ['restyle-from', 'crop'], ['base', 'crop']]});
  const vs = [...(c.variants || [])].sort((a, b) => (a.kind === 'enhance' ? 0 : 1) - (b.kind === 'enhance' ? 0 : 1) || a.label.localeCompare(b.label) || (b.created > a.created ? 1 : -1));
  for (const v of vs) {
    const acts = v.kind === 'restyle' ? [['promote', v.hash], ['enhance', v.hash], ['restyle-from', v.hash], ['base', v.hash]] : [['restyle-from', v.hash], ['base', v.hash]];
    cols.push({key: v.hash, title: v.label, sub: v.hash + (v.hash === cur ? ' · current' : '') + (v.base !== 'crop' ? ` · from ${v.base}` : ''),
               path: v.path, kind: v.kind, recipe: v.recipe, current: v.hash === cur, acts, isBase: (c.entry.base || 'crop') === v.hash});
  }
  for (const k of ['plain', 'styled']) {
    const r = c.renders?.[k];
    if (r) cols.push({key: 'render-' + k, title: `render · ${k}`, sub: `${r.dpi || '?'} dpi · text ${r.sizes?.text}px${r.shrunk ? ' (shrunk)' : ''}`,
                      path: r.path, kind: 'card', acts: [[k === 'plain' ? 'render-plain' : 'render-styled', '']]});
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
          <span>printing</span><span><select id="printing"><option value="">${esc(c.card.set.toUpperCase())} ${esc(c.card.collector_number)} (default)</option></select></span>
          <span>restyle base</span><span><span class="badge">${esc(c.entry.base || 'crop')}</span> ${c.entry.base ? '<button class="small" id="basecrop">use crop</button>' : ''}</span>
          <span>subject</span><span><input type="text" id="subject" value="${esc(c.entry.subject || '')}" placeholder="what the picture is of (prepended to the prompt)"></span>
          <span>seed</span><span><input type="number" id="seed" value="${c.entry.seed ?? ''}" placeholder="derived: ${c.recipe?.seed ?? '-'}" style="width:9em"> ${c.entry.seed != null ? '<button class="small" id="unpin">unpin</button>' : ''}</span>
          ${(c.warnings || []).map(w => `<span>warning</span><span class="warn">${esc(w)}</span>`).join('')}
        </div></div>
      <div><div class="muted" style="font-size:.85em">current recipe ${c.style_hash ? `<span class="mono">${c.style_hash}</span>` : '(no style)'}</div>
        <div class="recipe mono" style="font-size:.78em;max-width:520px;color:var(--ink-2)">${c.recipe ? esc(c.recipe.prompt) : ''}</div></div>
      <div class="row" style="margin-left:auto"><a class="pill" href="#/set/${esc(code)}">← ${esc(code)}</a><a class="pill" href="#/set/${esc(code)}/lab">lab</a></div>
    </div>
    ${A && B ? abPanel(A, B) : `<p class="muted">Pick <b>A</b> and <b>B</b> on two images to wipe between them.</p>`}
    <div class="cols">${cols.map(x => `
      <div class="col ${x.current ? 'current' : ''} ${ab.a === x.key ? 'isA' : ''} ${ab.b === x.key ? 'isB' : ''}" data-key="${esc(x.key)}">
        <div class="pic ${x.kind === 'card' ? 'card' : ''}" data-open="${esc(x.path)}"><img loading="lazy" src="${img(x.path, 640)}">
          <div class="ab"><b data-ab="a">A</b><b data-ab="b">B</b></div></div>
        <div class="title"><span>${esc(x.title)}${x.isBase ? ' <span class="badge accent">base</span>' : ''}</span><small>${esc(x.sub)}</small></div>
        ${x.recipe ? `<div class="recipe">${recipeDiff(x.recipe, c.recipe)}</div>` : ''}
        <div class="acts">${x.acts.map(([a, arg]) => `<button class="small" data-act="${a}" data-arg="${esc(arg)}">${
          {enhance: 'enhance', 'restyle-from': 'restyle from this', base: 'use as base', promote: 'use recipe for set',
           'render-plain': 're-render', 'render-styled': 're-render'}[a]}</button>`).join('')}</div>
      </div>`).join('')}
    </div>`;
  // printings
  api(`/api/sets/${code}/cards/${encodeURIComponent(c.name)}/printings`).then(ps => {
    const sel = $('#printing'); if (!sel) return;
    sel.innerHTML = `<option value="">default (newest non-crossover)</option>` + ps.map(p =>
      `<option value="${p.set}:${p.collector_number}" ${p.selected ? 'selected' : ''}>${p.set.toUpperCase()} ${p.collector_number} · ${esc(p.artist)}${p.ub ? ' · UB' : ''}${p.released_at ? ' · ' + p.released_at.slice(0, 4) : ''}</option>`).join('');
    if (ps.length < 2) sel.title = 'one printing on file; `mint cards --kind default_cards` fetches them all';
  }).catch(() => {});
  const put = body => api(`/api/sets/${code}/cards/${encodeURIComponent(c.name)}`, {method: 'PUT', body}).then(() => refresh()).catch(e => toast(e.message, true));
  $('#printing').onchange = e => put({printing: e.target.value || null});
  $('#subject').onchange = e => put({subject: e.target.value || null});
  $('#seed').onchange = e => put({seed: e.target.value === '' ? null : +e.target.value});
  if ($('#unpin')) $('#unpin').onclick = () => put({seed: null});
  if ($('#basecrop')) $('#basecrop').onclick = () => put({base: null});
  document.querySelectorAll('[data-ab]').forEach(b => b.onclick = e => {
    e.stopPropagation(); const key = b.closest('.col').dataset.key;
    ab[b.dataset.ab] = ab[b.dataset.ab] === key ? null : key; card(r);
  });
  document.querySelectorAll('[data-open]').forEach(p => p.onclick = () => window.open(file(p.dataset.open), '_blank'));
  document.querySelectorAll('[data-act]').forEach(b => b.onclick = async () => {
    const act = b.dataset.act, arg = b.dataset.arg, names = [c.name];
    if (act === 'enhance') submit({kind: 'enhance', set: code, names, base: arg});
    else if (act === 'restyle-from') { await put({base: arg === 'crop' ? null : arg}); submit({kind: 'restyle', set: code, names}); }
    else if (act === 'base') put({base: arg === 'crop' ? null : arg});
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
  const val = f => L.values[f.name] ?? f.default ?? '';
  const changed = f => JSON.stringify(L.values[f.name] ?? f.default) !== JSON.stringify(base[f.name] ?? f.default);
  const input = f => {
    if (f.choices) return `<select data-f="${f.name}">${f.choices.map(c => `<option ${val(f) === c ? 'selected' : ''}>${c}</option>`).join('')}</select>`;
    if (f.type === 'bool') return `<input type="checkbox" data-f="${f.name}" ${val(f) ? 'checked' : ''}>`;
    if (f.type === 'list') return `<input type="text" data-f="${f.name}" value="${esc(JSON.stringify(val(f) || []))}" placeholder='[{"name": "x.safetensors", "strength": 0.7}]'>`;
    if (f.name === 'prompt' || f.name === 'negative') return `<textarea data-f="${f.name}">${esc(val(f))}</textarea>`;
    if (f.type === 'int' || f.type === 'float') return `<input type="number" data-f="${f.name}" value="${esc(val(f))}" step="${f.type === 'int' ? 1 : 0.05}">`;
    return `<input type="text" data-f="${f.name}" value="${esc(val(f))}">`;
  };
  const probes = st.cards_detail.filter(c => L.probes.includes(c.name));
  const labels = new Map();  // label-hash -> {label, hash, recipe} across probe cards, newest first
  for (const c of probes) for (const v of c.variants || []) if (v.kind === 'restyle') { const k = v.label + '-' + v.hash; if (!labels.has(k)) labels.set(k, v); }
  const cols = [...labels.values()].sort((a, b) => ((b.label === base.name) - (a.label === base.name)) || (b.created > a.created ? 1 : -1)).slice(0, 8);
  $('#main').innerHTML = `
    <div class="row"><h1>${esc(code)} <span class="muted">recipe lab</span></h1><a class="pill" href="#/set/${esc(code)}">← ${esc(code)}</a></div>
    <div class="lab">
      <div>
        <div class="form">
          ${fields.filter(f => f.name !== 'name').map(f => `<label class="${changed(f) ? 'changed' : ''}">${esc(f.name)}</label>${input(f)}`).join('')}
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
  document.querySelectorAll('[data-f]').forEach(el => el.onchange = () => {
    const f = fields.find(x => x.name === el.dataset.f); let v = el.type === 'checkbox' ? el.checked : el.value;
    if (f.type === 'int') v = parseInt(v, 10); else if (f.type === 'float') v = parseFloat(v);
    else if (f.type === 'list') { try { v = JSON.parse(v || '[]'); } catch { toast('loras must be JSON', true); return; } }
    L.values[f.name] = v; lab();
  });
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
