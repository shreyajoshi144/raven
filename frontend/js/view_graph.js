import { get } from './api.js';
import { el, mount, spinner, badge, resolutionBadge, sourceLabel, debounce } from './util.js';
import { icon, ROLE_ICON, ROLE_LABEL } from './icons.js';
import { createFlow } from './flow.js';
import { inline } from './markdown.js';
import { errorBox } from './app.js';

const ROLES = ['frontend', 'entry', 'router', 'service', 'model', 'worker', 'config', 'module', 'external'];
const ROLE_VAR = { frontend: 'var(--r-frontend)', entry: 'var(--r-entry)', router: 'var(--r-router)', model: 'var(--r-model)', service: 'var(--r-service)', config: 'var(--r-config)', worker: 'var(--r-worker)', module: 'var(--r-module)', external: 'var(--r-external)', test: 'var(--r-test)' };

export async function graphView(a, query, ctx) {
  const id = a.analysis_id; let dead = false;
  let mode = query.mode === 'trace' ? 'trace' : 'files';
  const st = { focus: query.focus || '', tests: false, external: true, hidden: new Set(), data: null, routes: null, traceId: query.node || null };
  const host = el('div', { class: 'canvas-wrap' }); const drawer = el('aside', { class: 'drawer', 'aria-live': 'polite' });
  const status = el('span', { class: 'small muted', 'aria-live': 'polite' });
  let flow = null;

  const search = el('input', { type: 'search', placeholder: 'Find a file or symbol…', 'aria-label': 'Find a file or symbol', maxlength: 100 });
  const folder = el('select', { 'aria-label': 'Focus on a folder', on: { change: () => { st.focus = folder.value; loadFiles(); } } }, el('option', { value: '', text: 'All folders' }));
  const routeSel = el('select', { 'aria-label': 'Route to trace', on: { change: () => { st.traceId = routeSel.value; loadTrace(); } } });
  const chipsBox = el('div', { class: 'role-chips', role: 'group', 'aria-label': 'Show or hide file roles' });
  const modeSeg = el('div', { class: 'seg', role: 'group', 'aria-label': 'View mode' });
  const mk = (t, k, l) => el('label', { class: 'toggle' }, el('input', { type: 'checkbox', checked: st[k], on: { change: (e) => { st[k] = e.target.checked; loadFiles(); } } }), l);
  const filesTools = el('div', { class: 'row', style: '' }, folder, mk('t', 'tests', 'Tests'), mk('x', 'external', 'Packages'));
  const traceTools = el('div', { class: 'row grow' }, routeSel);

  function paintMode() {
    mount(modeSeg, [['files', 'File flow', 'files'], ['trace', 'Route trace', 'trace']].map(([k, l]) => el('button', { type: 'button', 'aria-pressed': mode === k ? 'true' : 'false', on: { click: () => { if (mode !== k) { mode = k; paintMode(); (k === 'files' ? loadFiles() : openTrace()); } } } }, l)));
    filesTools.style.display = mode === 'files' ? '' : 'none'; traceTools.style.display = mode === 'trace' ? '' : 'none'; chipsBox.style.display = mode === 'files' ? '' : 'none';
  }
  function paintChips() {
    if (!st.data) return; const present = new Set(st.data.nodes.map((n) => n.role)); mount(chipsBox, el('span', { class: 'small muted', style: '', text: 'Roles' }),
      ROLES.filter((r) => present.has(r) || st.hidden.has(r)).map((r) => el('button', { class: 'rchip', type: 'button', 'aria-pressed': st.hidden.has(r) ? 'false' : 'true', on: { click: () => { st.hidden.has(r) ? st.hidden.delete(r) : st.hidden.add(r); paintChips(); applyData(); } } }, el('i', { style: `background:${ROLE_VAR[r]}` }), ROLE_LABEL[r])));
  }
  function ensureFlow() {
    if (flow) return flow;
    flow = createFlow(host, { id: 'atlas', onSelect: (n) => showNode(n), onEdge: (e, s, t) => showEdge(e, s, t), onOpen: (n) => open(n), transitive: true });
    const controls = el('div', { class: 'flow-controls' }, el('button', { class: 'btn icon', type: 'button', 'aria-label': 'Zoom in', on: { click: () => flow.zoom(1.25) } }, icon('plus')), el('button', { class: 'btn icon', type: 'button', 'aria-label': 'Zoom out', on: { click: () => flow.zoom(0.8) } }, icon('minus')), el('button', { class: 'btn icon', type: 'button', 'aria-label': 'Fit to screen', on: { click: () => flow.fit() } }, icon('fit')));
    const legend = el('div', { class: 'legend', 'aria-label': 'Legend' }, el('span', {}, el('i', { class: 'line' }), 'verified'), el('span', {}, el('i', { class: 'line dash' }), 'inferred'), el('span', {}, el('i', { class: 'line dot' }), 'unresolved'), el('span', { class: 'muted', text: 'Click a node to trace its connections · double-click to open source' }));
    host.append(controls, legend); return flow;
  }
  function visible(data) { const hide = mode === 'files' ? st.hidden : new Set(); const nodes = data.nodes.filter((n) => !hide.has(n.role)); const ids = new Set(nodes.map((n) => n.id)); return { ...data, nodes, edges: data.edges.filter((e) => ids.has(e.source) && ids.has(e.target)) }; }
  function applyData() { if (!st.data) return; const f = ensureFlow(); const v = visible(st.data); f.setData(v); f.transitive = true; status.textContent = mode === 'files' ? `${v.nodes.filter((n) => n.kind === 'file').length} of ${st.data.total_files} files · ${v.edges.length} connections` : `${v.nodes.length} nodes · ${v.edges.length} connections`; if (st.selectId && f.nodes.has(st.selectId)) f.select(st.selectId, true); }
  async function loadFiles() {
    mount(drawer, intro());
    host.classList.add('loading'); const p = new URLSearchParams({ limit: st.focus ? '120' : '70', include_tests: st.tests, include_external: st.external }); if (st.focus) p.set('focus', st.focus);
    try { st.data = await get(`/api/v1/analyses/${id}/graph/flow?${p}`); if (dead) return;
      if (folder.options.length <= 1) for (const f of st.data.folders) folder.appendChild(el('option', { value: f, text: f || '/' }));
      folder.value = st.focus; paintChips(); applyData();
      if (!st.data.nodes.length) status.textContent = 'Nothing to draw for this scope.';
      if (query.select) { const hit = st.data.nodes.find((n) => n.path === query.select); if (hit) flow.select(hit.id, true); query.select = null; }
    } catch (e) { if (!dead) mount(drawer, errorBox(e, loadFiles)); }
  }
  async function openTrace() {
    if (!st.routes) { try { st.routes = (await get(`/api/v1/analyses/${id}/graph?types=route&limit=500`)).nodes; } catch (e) { mount(drawer, errorBox(e)); return; }
      mount(routeSel, st.routes.map((r) => el('option', { value: r.id, text: r.name }))); }
    if (!st.routes.length) { mount(drawer, el('div', { class: 'empty small', text: 'No routes were detected in this repository, so there is nothing to trace.' })); return; }
    if (!st.traceId || !st.routes.some((r) => r.id === st.traceId)) st.traceId = st.routes[0].id; routeSel.value = st.traceId; loadTrace();
  }
  async function loadTrace() {
    mount(drawer, intro());
    try { st.data = await get(`/api/v1/analyses/${id}/graph/trace?node_id=${st.traceId}&depth=3`); if (dead) return; st.selectId = null; applyData(); if (flow) flow.select(st.data.root, false); } catch (e) { if (!dead) mount(drawer, errorBox(e, loadTrace)); }
  }
  const intro = () => el('div', { class: 'stack' }, el('div', { class: 'eyebrow', text: mode === 'files' ? 'File flow' : 'Route trace' }), el('h2', { text: mode === 'files' ? 'Follow the connections' : 'Follow a request' }),
    el('p', { class: 'small muted', text: mode === 'files' ? 'Each card is a file. Arrows point from a file to what it depends on. Select a card to light up everything upstream and downstream; click a line to see the code that creates it.' : 'Pick a route to see its handler, dependencies, models and the functions it calls — each step with its evidence.' }),
    el('div', { class: 'small stack' }, el('div', {}, el('span', { class: 'badge ok', text: 'verified' }), ' proven by syntax'), el('div', {}, el('span', { class: 'badge warn', text: 'inferred' }), ' heuristic'), el('div', {}, el('span', { class: 'badge bad', text: 'unresolved' }), ' target not determinable')),
    el('p', { class: 'small muted' }, el('span', { class: 'kbd', text: 'Tab' }), ' focus a node · ', el('span', { class: 'kbd', text: '←→' }), ' follow links · ', el('span', { class: 'kbd', text: 'Esc' }), ' clear'));
  const open = (n) => { if (n && n.path) ctx.goto('files', { path: n.path, line: n.start_line ? (n.end_line && n.end_line !== n.start_line ? `${n.start_line}-${n.end_line}` : n.start_line) : '' }); };
  const evBtn = (e) => el('button', { class: 'linklike mono small', type: 'button', on: { click: () => ctx.goto('files', { path: e.path, line: e.end_line !== e.start_line ? `${e.start_line}-${e.end_line}` : e.start_line }) }, text: `${e.path}:${e.start_line}` });

  function showNode(n) {
    if (!n) { mount(drawer, intro()); st.selectId = null; return; }
    st.selectId = n.id; const f = flow; const ins = f.edges.filter((e) => e.target === n.id), outs = f.edges.filter((e) => e.source === n.id);
    const list = (es, dir) => es.length ? el('div', { class: 'rel' }, es.map((e) => { const o = f.nodes.get(dir === 'out' ? e.target : e.source); return o ? el('button', { type: 'button', on: { click: () => { f.select(o.id, true); } } }, icon(ROLE_ICON[o.role] || 'module'), el('span', { class: 'mono', text: o.label }), el('span', { class: 'tag' }, resolutionBadge(e.resolution)), ) : null; })) : el('p', { class: 'small muted', text: 'None in this view.' });
    mount(drawer, el('div', { class: 'stack' },
      el('div', { class: 'row' }, badge(n.kind === 'file' || n.kind === 'external' ? (ROLE_LABEL[n.role] || n.kind) : n.kind.charAt(0).toUpperCase() + n.kind.slice(1).replace('_', ' '), n.role === 'entry' ? 'bad' : 'info'), n.context ? badge('context', 'neutral') : null, n.unresolved ? badge('unresolved', 'bad') : null),
      el('h2', { class: 'mono', text: n.label }), n.path ? el('div', { class: 'small muted mono', text: n.path + (n.start_line ? `:${n.start_line}` : '') }) : null,
      n.counts && Object.keys(n.counts).length ? el('div', { class: 'row' }, Object.entries(n.counts).map(([k, v]) => badge(`${v} ${k}`, 'neutral'))) : null,
      n.summary ? el('div', {}, sourceLabel(n.summary_source), el('p', { class: 'small', text: n.summary })) : null,
      n.facts && n.facts.length ? el('ul', { class: 'small' }, n.facts.map((x) => el('li', {}, inline(x)))) : null,
      el('div', { class: 'row' }, n.path ? el('button', { class: 'btn sm primary', type: 'button', on: { click: () => open(n) } }, icon('files'), 'Open source') : null,
        n.kind === 'file' && n.counts && n.counts.routes ? el('button', { class: 'btn sm', type: 'button', on: { click: () => traceFile(n) } }, icon('trace'), 'Trace routes') : null,
        n.kind === 'file' ? el('button', { class: 'btn sm', type: 'button', on: { click: () => { st.focus = n.dir; loadFiles(); } } }, icon('focus'), 'Focus folder') : null,
        mode === 'trace' && n.kind !== 'external' && n.id !== st.traceId ? el('button', { class: 'btn sm', type: 'button', on: { click: () => { st.traceId = n.id; loadTrace(); } } }, icon('trace'), 'Trace from here') : null),
      el('div', {}, el('h3', { text: `Depends on (${outs.length})` }), list(outs, 'out')), el('div', {}, el('h3', { text: `Used by (${ins.length})` }), list(ins, 'in'))));
  }
  async function traceFile(n) { mode = 'trace'; paintMode(); if (!st.routes) await openTrace(); const r = (st.routes || []).find((x) => x.path === n.path); if (r) { st.traceId = r.id; routeSel.value = r.id; loadTrace(); } }
  function showEdge(e, s, t) {
    mount(drawer, el('div', { class: 'stack' }, el('div', { class: 'row' }, badge('connection', 'info'), resolutionBadge(e.resolution)), el('h2', {}, el('span', { class: 'mono', text: s.label }), ' → ', el('span', { class: 'mono', text: t.label })),
      el('div', { class: 'row' }, Object.entries(e.kinds || { [e.relation]: 1 }).map(([k, v]) => badge(`${k.replaceAll('_', ' ')}${v > 1 ? ' ×' + v : ''}`, 'neutral'))),
      e.labels && e.labels.length ? el('ul', { class: 'small' }, e.labels.map((l) => el('li', { text: l }))) : (e.label ? el('p', { class: 'small', text: e.label }) : null),
      el('h3', { text: 'Evidence in the source' }), e.evidence && e.evidence.length ? el('ul', { class: 'list-reset stack small' }, e.evidence.map((x) => el('li', {}, evBtn(x)))) : el('p', { class: 'small muted', text: 'No line evidence recorded.' }),
      e.resolution !== 'verified_static' ? el('p', { class: 'small muted', text: e.resolution === 'unresolved' ? 'Raven found a reference here but could not determine its target statically.' : 'At least one underlying relationship is heuristic, so this connection is shown as inferred.' }) : null,
      el('button', { class: 'btn sm', type: 'button', on: { click: () => flow.select(flow.sel) } }, 'Back to node')));
  }
  let sdeb = debounce((v) => { const first = flow && flow.search(v); if (first && v.trim()) flow.centerOn(first, 0.9); }, 200);
  search.addEventListener('input', () => sdeb(search.value));
  search.addEventListener('keydown', (e) => { if (e.key === 'Enter' && flow) { const first = flow.search(search.value); if (first) flow.select(first, true); } });
  paintMode(); mount(drawer, intro());
  const node = el('div', { class: 'stack' }, el('div', { class: 'row spread' }, el('div', {}, el('div', { class: 'eyebrow', text: 'Map' }), el('h2', { text: 'How the code connects' })), status),
    el('div', { class: 'atlas' }, el('div', { class: 'atlas-main' }, el('div', { class: 'toolbar' }, modeSeg, el('div', { class: 'grow' }, search), filesTools, traceTools), chipsBox, host), drawer));
  return { node, after: () => { mode === 'files' ? loadFiles() : openTrace(); }, cleanup: () => { dead = true; } };
}
