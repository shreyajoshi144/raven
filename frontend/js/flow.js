// Interactive flowchart engine: layered layout, bezier-routed edges, animated flow, pan/zoom, minimap, focus mode.
import { iconPath, ROLE_LABEL } from './icons.js';
const NS = 'http://www.w3.org/2000/svg';
const CARD = { W: 226, H: 84, GX: 96, GY: 22, PAD: 56 };
// n8n-style node: a square icon tile with ports, label underneath (opts.tile)
const TILE = { W: 120, H: 96, GX: 112, GY: 18, PAD: 56, T: 60, tile: true };
const ROLE_COLOR = { frontend: 'var(--r-frontend)', entry: 'var(--r-entry)', router: 'var(--r-router)', model: 'var(--r-model)', service: 'var(--r-service)', config: 'var(--r-config)', worker: 'var(--r-worker)', module: 'var(--r-module)', test: 'var(--r-test)', external: 'var(--r-external)' };
const ROLE_ORDER = ['frontend', 'entry', 'router', 'service', 'model', 'worker', 'config', 'module', 'test', 'external'];
const s = (tag, attrs = {}, ...kids) => { const n = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) if (v != null) n.setAttribute(k, v); for (const c of kids) if (c != null) n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); return n; };
const clip = (t, n) => (t.length > n ? t.slice(0, n - 1) + '…' : t);

export function layout(nodes, edges, D = CARD) {
  const { W, H, GX, GY, PAD } = D;
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const internal = nodes.filter((n) => n.role !== 'external');
  const externals = nodes.filter((n) => n.role === 'external');
  const out = new Map(internal.map((n) => [n.id, []])), inn = new Map(internal.map((n) => [n.id, []]));
  const real = edges.filter((e) => byId.has(e.source) && byId.has(e.target) && e.source !== e.target);
  for (const e of real) if (out.has(e.source) && out.has(e.target)) { out.get(e.source).push(e.target); inn.get(e.target).push(e.source); }
  // cycle breaking by DFS (back edges are ignored for layering)
  const color = new Map(), back = new Set();
  const order = [...internal].sort((a, b) => ROLE_ORDER.indexOf(a.role) - ROLE_ORDER.indexOf(b.role) || (a.path || a.label).localeCompare(b.path || b.label));
  const visit = (id) => { color.set(id, 1); for (const t of out.get(id)) { if (color.get(t) === 1) back.add(id + '>' + t); else if (!color.has(t)) visit(t); } color.set(id, 2); };
  for (const n of order) if (!color.has(n.id)) visit(n.id);
  const indeg = new Map(internal.map((n) => [n.id, 0])), fwd = new Map(internal.map((n) => [n.id, []]));
  for (const [a, ts] of out) for (const t of ts) if (!back.has(a + '>' + t)) { fwd.get(a).push(t); indeg.set(t, indeg.get(t) + 1); }
  const layer = new Map(), q = [];
  for (const n of order) if (indeg.get(n.id) === 0) { layer.set(n.id, 0); q.push(n.id); }
  while (q.length) { const a = q.shift(); for (const t of fwd.get(a)) { layer.set(t, Math.max(layer.get(t) ?? 0, layer.get(a) + 1)); indeg.set(t, indeg.get(t) - 1); if (indeg.get(t) === 0) q.push(t); } }
  const linked = new Set(); for (const e of real) { linked.add(e.source); linked.add(e.target); }
  const unlinked = internal.filter((n) => !linked.has(n.id));
  const connected = internal.filter((n) => linked.has(n.id));
  const maxL = Math.max(0, ...connected.map((n) => layer.get(n.id) ?? 0));
  const cols = Array.from({ length: maxL + 1 }, () => []);
  for (const n of connected) cols[layer.get(n.id) ?? 0].push(n);
  const pos = new Map();
  const ordIdx = () => { cols.forEach((c) => c.forEach((n, i) => pos.set(n.id, i))); };
  cols.forEach((c) => c.sort((a, b) => ROLE_ORDER.indexOf(a.role) - ROLE_ORDER.indexOf(b.role) || (a.path || a.label).localeCompare(b.path || b.label))); ordIdx();
  const bary = (n, nb) => { const v = nb.get(n.id).map((x) => pos.get(x)).filter((x) => x != null); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : pos.get(n.id); };
  for (let it = 0; it < 6; it++) {
    for (let l = 1; l < cols.length; l++) { cols[l].sort((a, b) => bary(a, inn) - bary(b, inn)); ordIdx(); }
    for (let l = cols.length - 2; l >= 0; l--) { cols[l].sort((a, b) => bary(a, out) - bary(b, out)); ordIdx(); }
  }
  const extraCols = [];
  if (unlinked.length) { const per = Math.max(6, Math.ceil(Math.sqrt(unlinked.length * 1.5))); for (let i = 0; i < unlinked.length; i += per) extraCols.push(unlinked.slice(i, i + per)); }
  const allCols = [...cols, ...extraCols, ...(externals.length ? [externals.sort((a, b) => b.degree - a.degree)] : [])];
  const maxRows = Math.max(1, ...allCols.map((c) => c.length));
  const place = new Map();
  allCols.forEach((col, ci) => {
    const colH = col.length * (H + GY) - GY, total = maxRows * (H + GY) - GY, off = (total - colH) / 2;
    col.forEach((n, ri) => place.set(n.id, { x: PAD + ci * (W + GX), y: PAD + 20 + off + ri * (H + GY), col: ci }));
  });
  const colRoles = allCols.map((col, ci) => { const c = {}; col.forEach((n) => (c[n.role] = (c[n.role] || 0) + 1)); const top = Object.entries(c).sort((a, b) => b[1] - a[1])[0]; return { ci, label: ci >= cols.length + extraCols.length && externals.length ? 'External packages' : ci >= cols.length ? 'Unlinked files' : (ci === 0 ? 'Start · ' : '') + (top ? ROLE_LABEL[top[0]] : '') }; });
  return { place, back, cols: allCols.length, colRoles, width: PAD * 2 + allCols.length * (W + GX) - GX, height: PAD * 2 + 20 + maxRows * (H + GY) - GY };
}

function tileBody(g, n, D) {
  const { W, T } = D, x0 = (W - T) / 2, col = ROLE_COLOR[n.role] || ROLE_COLOR.module, c = n.counts || {};
  g.appendChild(s('rect', { class: 'hit', x: 0, y: -10, width: W, height: D.H + 10, fill: 'transparent' }));
  g.appendChild(s('rect', { class: 'card', x: x0, y: 0, width: T, height: T, rx: 16 }));
  g.appendChild(s('rect', { class: 'bar', x: x0 + 15, y: T - 9, width: T - 30, height: 3, rx: 1.5, fill: col }));
  const gl = s('g', { transform: `translate(${x0 + T / 2 - 15},${T / 2 - 20}) scale(1.25)` });
  gl.appendChild(s('path', { class: 'glyph', style: `stroke:${col}`, d: iconPath({ entry: 'entry', router: 'route', model: 'model', service: 'service', config: 'config', worker: 'worker', test: 'test', external: 'external' }[n.role] || 'module') })); g.appendChild(gl);
  g.appendChild(s('circle', { class: 'port', cx: x0, cy: T / 2, r: 4.5 })); g.appendChild(s('circle', { class: 'port', cx: x0 + T, cy: T / 2, r: 4.5 }));
  const title = s('text', { class: 'ttl', x: W / 2, y: T + 17, 'text-anchor': 'middle' }, clip(n.label, 17)); title.appendChild(s('title', {}, n.path || n.label)); g.appendChild(title);
  const sub = n.kind === 'file' ? (n.dir || '/') : n.kind === 'external' ? (n.category || 'package') : (n.path ? `${n.kind} · ${n.path.split('/').pop()}` : n.kind);
  g.appendChild(s('text', { class: 'sub', x: W / 2, y: T + 31, 'text-anchor': 'middle' }, clip(sub.split('/').slice(-2).join('/'), 20)));
  const badge = n.tag || (c.routes ? `${c.routes} route${c.routes > 1 ? 's' : ''}` : c.models ? `${c.models} model${c.models > 1 ? 's' : ''}` : c.functions ? `ƒ ${c.functions}` : '');
  if (badge) { const bw = badge.length * 5.6 + 12; g.appendChild(s('rect', { class: 'chip', x: x0 + T - bw + 10, y: -9, width: bw, height: 16, rx: 8 })); g.appendChild(s('text', { class: 'chip-t', x: x0 + T - bw / 2 + 10, y: 2.4, 'text-anchor': 'middle' }, badge)); }
}

function nodeEl(n, ctl, D = CARD) {
  const { W, H } = D;
  const g = s('g', { class: 'fnode' + (n.context ? ' ctx' : '') + (n.role === 'external' ? ' ext' : '') + (n.unresolved ? ' unres' : ''), tabindex: 0, role: 'button', 'data-id': n.id, 'aria-label': `${n.label}${n.role ? ', ' + (ROLE_LABEL[n.role] || n.role) : ''}${n.path ? ', ' + n.path : ''}` });
  if (D.tile) tileBody(g, n, D);
  else {
  g.appendChild(s('rect', { class: 'shadow', x: 4, y: 4, width: W, height: H, rx: 12 }));
  g.appendChild(s('rect', { class: 'card', width: W, height: H, rx: 12 }));
  g.appendChild(s('rect', { x: 0, y: 0, width: 9, height: H, rx: 4, fill: ROLE_COLOR[n.role] || ROLE_COLOR.module }));
  g.appendChild(s('rect', { x: 5, y: 0, width: 5, height: H, fill: ROLE_COLOR[n.role] || ROLE_COLOR.module }));
  const gl = s('g', { transform: 'translate(24,16) scale(.9)' }); gl.appendChild(s('path', { class: 'glyph', d: iconPath({ entry: 'entry', router: 'route', model: 'model', service: 'service', config: 'config', worker: 'worker', test: 'test', external: 'external' }[n.role] || 'module') })); g.appendChild(gl);
  const title = s('text', { class: 'ttl', x: 52, y: 29 }, clip(n.label, 22)); title.appendChild(s('title', {}, n.path || n.label)); g.appendChild(title);
  const sub = n.kind === 'file' ? (n.dir || '/') : n.kind === 'external' ? (n.category || 'package') : (n.path ? `${n.kind} · ${n.path.split('/').pop()}${n.start_line ? ':' + n.start_line : ''}` : n.kind);
  g.appendChild(s('text', { class: 'sub', x: 52, y: 46 }, clip(sub, 30)));
  const chips = []; const c = n.counts || {};
  if (c.routes) chips.push(`${c.routes} route${c.routes > 1 ? 's' : ''}`); if (c.models) chips.push(`${c.models} model${c.models > 1 ? 's' : ''}`);
  if (c.functions) chips.push(`ƒ ${c.functions}`); if (c.env) chips.push(`env ${c.env}`); if (c.api) chips.push(`${c.api} api call${c.api > 1 ? 's' : ''}`); if (n.tag) chips.unshift(n.tag); if (n.lines) chips.push(`${n.lines} ln`);
  let cx = 16; for (const t of chips.slice(0, 4)) { const w = t.length * 6 + 12; g.appendChild(s('rect', { class: 'chip', x: cx, y: 58, width: w, height: 18, rx: 9 })); g.appendChild(s('text', { class: 'chip-t', x: cx + 6, y: 70.5 }, t)); cx += w + 5; }
  }
  g.addEventListener('click', (e) => { e.stopPropagation(); ctl.select(n.id); });
  g.addEventListener('dblclick', (e) => { e.stopPropagation(); ctl.opts.onOpen && ctl.opts.onOpen(ctl.nodes.get(n.id)); });
  g.addEventListener('keydown', (e) => ctl.key(e, n.id));
  return g;
}

export function createFlow(host, opts = {}) {
  const D = opts.tile ? TILE : CARD; const { W, H, GX, GY, PAD } = D;
  const outX = D.tile ? (W + D.T) / 2 : W, inX = D.tile ? (W - D.T) / 2 : 0, cyy = D.tile ? D.T / 2 : H / 2;
  const svg = s('svg', { class: 'flow', role: 'application', 'aria-label': opts.label || 'Flow diagram. Use Tab to move between nodes, Enter to select, arrow keys to follow connections.' });
  const defs = s('defs', {}, s('marker', { id: 'arrow-' + (opts.id || 'f'), viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: 'auto-start-reverse' }, s('path', { d: 'M0 1 L9 5 L0 9z', fill: 'context-stroke' })));
  const vp = s('g', { class: 'vp' }), gCols = s('g'), gEdges = s('g'), gNodes = s('g');
  vp.append(gCols, gEdges, gNodes); svg.append(defs, vp);
  const mini = document.createElement('canvas'); mini.className = 'minimap'; mini.width = 380; mini.height = 248; mini.setAttribute('aria-hidden', 'true');
  host.append(svg); if (opts.minimap !== false) host.append(mini);
  const ctl = { opts, nodes: new Map(), edges: [], place: new Map(), sel: null, t: { x: 0, y: 0, k: 1 }, el: new Map(), edgeEl: new Map(), lay: null };
  const apply = (anim) => { vp.classList.toggle('anim', !!anim); vp.setAttribute('transform', `translate(${ctl.t.x},${ctl.t.y}) scale(${ctl.t.k})`); drawMini(); if (opts.onView) opts.onView(ctl.t); };
  const size = () => svg.getBoundingClientRect();
  function drawMini() {
    if (!ctl.lay || opts.minimap === false) return; const c = mini.getContext('2d'); c.clearRect(0, 0, mini.width, mini.height);
    const sc = Math.min(mini.width / ctl.lay.width, mini.height / ctl.lay.height) * .92, ox = (mini.width - ctl.lay.width * sc) / 2, oy = (mini.height - ctl.lay.height * sc) / 2;
    ctl.mm = { sc, ox, oy }; const cv = (n) => getComputedStyle(mini).getPropertyValue(n).trim();
    for (const [id, p] of ctl.place) { const n = ctl.nodes.get(id); c.fillStyle = id === ctl.sel ? (cv('--accent') || '#84cc16') : (cv('--ink') || '#0a0a0a'); c.globalAlpha = id === ctl.sel ? 1 : .55; c.fillRect(ox + p.x * sc, oy + p.y * sc, W * sc, H * sc); }
    c.globalAlpha = 1; const r = size(), x0 = -ctl.t.x / ctl.t.k, y0 = -ctl.t.y / ctl.t.k; c.strokeStyle = cv('--accent-2') || '#047857'; c.lineWidth = 3; c.strokeRect(ox + x0 * sc, oy + y0 * sc, (r.width / ctl.t.k) * sc, (r.height / ctl.t.k) * sc);
  }
  const fit = (anim = true) => { if (!ctl.lay) return; const r = size(); const k = Math.min(1.1, (r.width - 40) / ctl.lay.width, (r.height - 40) / ctl.lay.height); ctl.t.k = Math.max(0.12, k); ctl.t.x = (r.width - ctl.lay.width * ctl.t.k) / 2; ctl.t.y = (r.height - ctl.lay.height * ctl.t.k) / 2; apply(anim); };
  // readable first view for tall graphs: fit the width (never below the whole-graph fit), anchored at the top
  const overview = (anim = false) => { if (!ctl.lay) return; const r = size(); const all = Math.min(1.1, (r.width - 40) / ctl.lay.width, (r.height - 40) / ctl.lay.height);
    const k = Math.max(all, Math.min(0.62, (r.width - 40) / ctl.lay.width)); ctl.t.k = Math.max(0.12, k); ctl.t.x = Math.max(20, (r.width - ctl.lay.width * ctl.t.k) / 2); ctl.t.y = Math.max(20, (r.height - ctl.lay.height * ctl.t.k) / 2); apply(anim); };
  const centerOn = (id, k = Math.max(ctl.t.k, 0.85)) => { const p = ctl.place.get(id); if (!p) return; const r = size(); ctl.t.k = k; ctl.t.x = r.width / 2 - (p.x + W / 2) * k; ctl.t.y = r.height / 2 - (p.y + H / 2) * k; apply(true); };
  const zoomAt = (f, cx, cy, anim = false) => { const k = Math.min(2.6, Math.max(0.12, ctl.t.k * f)); ctl.t.x = cx - (cx - ctl.t.x) * (k / ctl.t.k); ctl.t.y = cy - (cy - ctl.t.y) * (k / ctl.t.k); ctl.t.k = k; apply(anim); };
  // Scrolling moves the canvas (like a map or a document); zooming needs ⌘/Ctrl + scroll, a trackpad pinch (which browsers report as ctrl+wheel), or the +/- buttons.
  svg.addEventListener('wheel', (e) => { e.preventDefault(); const r = size();
    if (e.ctrlKey || e.metaKey) { zoomAt(Math.exp(-Math.max(-60, Math.min(60, e.deltaY)) * 0.012), e.clientX - r.left, e.clientY - r.top); return; }
    const k = e.deltaMode === 1 ? 16 : 1; const dx = (e.shiftKey && !e.deltaX ? e.deltaY : e.deltaX) * k, dy = (e.shiftKey && !e.deltaX ? 0 : e.deltaY) * k; ctl.t.x -= dx; ctl.t.y -= dy; apply(false); }, { passive: false });
  const ptrs = new Map(); let pan = null, pinch = null;
  svg.addEventListener('pointerdown', (e) => { if (e.target.closest('.fnode')) return; ptrs.set(e.pointerId, e); svg.setPointerCapture(e.pointerId); if (ptrs.size === 1) { pan = { x: e.clientX - ctl.t.x, y: e.clientY - ctl.t.y, moved: false }; svg.classList.add('panning'); } if (ptrs.size === 2) { const [a, b] = [...ptrs.values()]; pinch = { d: Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY) }; pan = null; } });
  svg.addEventListener('pointermove', (e) => { if (!ptrs.has(e.pointerId)) return; ptrs.set(e.pointerId, e); if (pinch && ptrs.size === 2) { const [a, b] = [...ptrs.values()]; const d = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY), r = size(); zoomAt(d / pinch.d, (a.clientX + b.clientX) / 2 - r.left, (a.clientY + b.clientY) / 2 - r.top); pinch.d = d; } else if (pan) { if (Math.abs(e.clientX - pan.x - ctl.t.x) + Math.abs(e.clientY - pan.y - ctl.t.y) > 3) pan.moved = true; ctl.t.x = e.clientX - pan.x; ctl.t.y = e.clientY - pan.y; apply(false); } });
  const up = (e) => { ptrs.delete(e.pointerId); if (ptrs.size < 2) pinch = null; if (!ptrs.size) { svg.classList.remove('panning'); if (pan && !pan.moved) ctl.select(null); pan = null; } };
  svg.addEventListener('pointerup', up); svg.addEventListener('pointercancel', up);
  const mmPan = (e) => { if (!ctl.mm) return; const r = mini.getBoundingClientRect(), mx = ((e.clientX - r.left) / r.width) * mini.width, my = ((e.clientY - r.top) / r.height) * mini.height; const wx = (mx - ctl.mm.ox) / ctl.mm.sc, wy = (my - ctl.mm.oy) / ctl.mm.sc, sr = size(); ctl.t.x = sr.width / 2 - wx * ctl.t.k; ctl.t.y = sr.height / 2 - wy * ctl.t.k; apply(false); };
  mini.addEventListener('pointerdown', (e) => { mini.setPointerCapture(e.pointerId); mmPan(e); mini.onpointermove = mmPan; }); mini.addEventListener('pointerup', () => { mini.onpointermove = null; });

  function edgePath(a, b, back) {
    const x1 = a.x + outX, y1 = a.y + cyy, x2 = b.x + inX, y2 = b.y + cyy;
    if (!back && x2 > x1 + 8) { const dx = Math.max(60, (x2 - x1) * 0.5); return `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`; }
    const up = Math.min(a.y, b.y) - 42 - Math.abs(a.col - b.col) * 6; return `M${a.x + W / 2},${a.y} C${a.x + W / 2},${up} ${b.x + W / 2},${up} ${b.x + W / 2},${b.y}`;
  }
  ctl.setData = (data) => {
    ctl.nodes = new Map(data.nodes.map((n) => [n.id, n])); ctl.edges = data.edges; ctl.sel = null; ctl.el.clear(); ctl.edgeEl.clear();
    for (const g of [gCols, gEdges, gNodes]) while (g.firstChild) g.removeChild(g.firstChild);
    ctl.lay = layout(data.nodes, data.edges, D); ctl.place = ctl.lay.place;
    ctl.lay.colRoles.forEach((c) => { const x = PAD + c.ci * (W + GX); gCols.appendChild(s('text', { class: 'col-label', x, y: PAD - 8 }, c.label.toUpperCase())); gCols.appendChild(s('line', { class: 'col-rule', x1: x, x2: x + W, y1: PAD, y2: PAD })); });
    for (const e of data.edges) {
      const a = ctl.place.get(e.source), b = ctl.place.get(e.target); if (!a || !b) continue;
      const d = edgePath(a, b, ctl.lay.back.has(e.source + '>' + e.target) || b.x <= a.x);
      const g = s('g', { class: 'edge-g', 'data-id': e.id }); const mid = { x: (a.x + outX + b.x + inX) / 2, y: (a.y + b.y) / 2 + cyy - 6 };
      const label = Object.entries(e.kinds || {}).map(([k, v]) => `${k.replace('_', ' ')}${v > 1 ? ' ×' + v : ''}`).join(' · ') || (e.relation || '').replace('_', ' ');
      g.append(s('path', { class: 'edge ' + e.resolution, d, 'marker-end': `url(#arrow-${opts.id || 'f'})` }), s('path', { class: 'edge-flow', d }), s('path', { class: 'edge-hit', d }), s('text', { class: 'edge-label', x: mid.x, y: mid.y, 'text-anchor': 'middle' }, clip(label, 34)));
      g.addEventListener('click', (ev) => { ev.stopPropagation(); opts.onEdge && opts.onEdge(e, ctl.nodes.get(e.source), ctl.nodes.get(e.target)); });
      gEdges.appendChild(g); ctl.edgeEl.set(e.id, g);
    }
    for (const n of data.nodes) { const p = ctl.place.get(n.id); if (!p) continue; const el = nodeEl(n, ctl, D); el.setAttribute('transform', `translate(${p.x},${p.y})`); gNodes.appendChild(el); ctl.el.set(n.id, el); }
    if (opts.initialView === 'overview') overview(false); else fit(false);
  };
  const related = (id, all) => { const up = new Set([id]), down = new Set([id]); const walk = (set, dir) => { const fr = [id]; while (fr.length) { const c = fr.shift(); for (const e of ctl.edges) { const [from, to] = dir === 'down' ? [e.source, e.target] : [e.target, e.source]; if (from === c && !set.has(to)) { set.add(to); if (all) fr.push(to); } } } }; walk(up, 'up'); walk(down, 'down'); return new Set([...up, ...down]); };
  ctl.select = (id, center = false) => {
    ctl.sel = id;
    const rel = id ? related(id, opts.transitive !== false) : null;
    for (const [nid, el] of ctl.el) { el.classList.toggle('sel', nid === id); el.classList.toggle('dim', !!rel && !rel.has(nid)); }
    for (const e of ctl.edges) { const g = ctl.edgeEl.get(e.id); if (!g) continue; const on = id && rel.has(e.source) && rel.has(e.target) && (opts.transitive !== false ? true : e.source === id || e.target === id); g.classList.toggle('hl', !!on); g.classList.toggle('dim', !!id && !on); }
    if (center && id) centerOn(id); drawMini();
    opts.onSelect && opts.onSelect(id ? ctl.nodes.get(id) : null);
  };
  ctl.key = (e, id) => {
    const k = e.key; if (k === 'Enter' || k === ' ') { e.preventDefault(); ctl.select(id); return; }
    if (k === 'Escape') { ctl.select(null); return; }
    const move = (ids) => { if (!ids.length) return; const t = ids[0]; ctl.el.get(t)?.focus(); ctl.select(t, true); e.preventDefault(); };
    if (k === 'ArrowRight') move(ctl.edges.filter((x) => x.source === id).map((x) => x.target));
    else if (k === 'ArrowLeft') move(ctl.edges.filter((x) => x.target === id).map((x) => x.source));
    else if (k === 'ArrowDown' || k === 'ArrowUp') { const p = ctl.place.get(id); const col = [...ctl.place].filter(([, q]) => q.col === p.col).sort((a, b) => a[1].y - b[1].y).map(([i]) => i); const i = col.indexOf(id) + (k === 'ArrowDown' ? 1 : -1); if (col[i]) move([col[i]]); }
  };
  ctl.search = (q) => { const t = q.trim().toLowerCase(); let first = null; for (const [id, el] of ctl.el) { const n = ctl.nodes.get(id); const hit = !!t && ((n.path || '').toLowerCase().includes(t) || n.label.toLowerCase().includes(t)); el.classList.toggle('match', hit); el.classList.toggle('dim', !!t && !hit); if (hit && !first) first = id; } if (!t) ctl.select(ctl.sel); return first; };
  ctl.fit = () => fit(true); ctl.zoom = (f) => { const r = size(); zoomAt(f, r.width / 2, r.height / 2, true); };
  ctl.reset = () => { if (!ctl.lay) return; const r = size(); ctl.t.k = 1; ctl.t.x = (r.width - ctl.lay.width) / 2; ctl.t.y = Math.min(24, (r.height - ctl.lay.height) / 2); apply(true); }; ctl.centerOn = centerOn;
  ctl.destroy = () => { host.replaceChildren(); };
  new ResizeObserver(() => drawMini()).observe(host);
  return ctl;
}
