import { get, post, del, ApiError } from './api.js';
import { el, mount, spinner, statusBadge, badge, fmtDate, fmtDuration, shortSha, PIPELINE, isActive, toast } from './util.js';
import { icon } from './icons.js';
import { createFlow } from './flow.js';
import { inline } from './markdown.js';
import { navigate, errorBox, session } from './app.js';
import { graphView } from './view_graph.js';
import { filesView } from './view_files.js';
import { docsView } from './view_docs.js';
import { chatView } from './view_chat.js';
import { healthView } from './view_health.js';
import { impactView } from './view_impact.js';

const TABS = [['overview', 'Overview', 'overview'], ['graph', 'Map', 'graph'], ['files', 'Files', 'files'], ['docs', 'Guide', 'docs'], ['health', 'Health', 'test'], ['impact', 'Impact', 'branch'], ['chat', 'Ask', 'chat']];
const STEP_LABEL = { QUEUED: 'Queued', FETCHING: 'Fetch', PARSING: 'Parse', BUILDING_GRAPH: 'Graph', GENERATING_DOCS: 'Guide', READY: 'Ready' };

export async function analysisView(id, tab, query) {
  let a = await get(`/api/v1/analyses/${id}`); session.analysis = a;
  const head = el('div', { class: 'ws-head' }); const body = el('div', { class: 'page', style: '' });
  const root = el('div', {}, head, body);
  let dead = false, timer = null, inner = null, renderedFor = null, delay = 2500;

  function pipeline() {
    const idx = PIPELINE.indexOf(a.status); const failedIdx = a.status === 'FAILED' ? (a.graph_complete ? 4 : (a.progress.files_parsed ? 2 : 1)) : -1;
    const out = [];
    PIPELINE.forEach((s, i) => {
      const done = a.status === 'READY' || (idx >= 0 && i < idx), active = i === idx && a.status !== 'READY', failed = i === failedIdx;
      out.push(el('div', { class: 'pstep ' + (failed ? 'failed' : done ? 'done' : active ? 'active' : ''), 'aria-current': active ? 'step' : null }, el('div', { class: 'node' }, done ? icon('check') : failed ? icon('x') : active ? el('span', { class: 'spinner' }) : null), STEP_LABEL[s]));
      if (i < PIPELINE.length - 1) out.push(el('div', { class: 'pline ' + (done ? 'done' : active ? 'active' : '') }));
    });
    return el('div', { class: 'pipeline', role: 'group', 'aria-label': 'Analysis progress' }, out);
  }
  async function act(fn, ok) { try { a = await fn(); session.analysis = a; if (ok) toast(ok); renderHead(); poll(true); } catch (e) { toast(e instanceof ApiError ? e.message : 'Action failed', 'bad'); } }
  function progressText() { const p = a.progress || {}; return p.files_total ? `Parsed ${p.files_parsed || 0} of ${p.files_total} Python files.` : p.files_considered ? `Inspected ${p.files_considered} files.` : ''; }
  function renderHead() {
    const actions = [];
    if (isActive(a.status)) actions.push(el('button', { class: 'btn sm', type: 'button', on: { click: () => act(() => post(`/api/v1/analyses/${id}/cancel`), 'Cancel requested') } }, icon('x'), 'Cancel'));
    if (a.retry_eligible) actions.push(el('button', { class: 'btn sm primary', type: 'button', on: { click: () => act(() => post(`/api/v1/analyses/${id}/retry`), 'Retrying…') } }, icon('refresh'), 'Retry analysis'));
    actions.push(el('button', { class: 'btn sm danger', type: 'button', on: { click: async () => {
      if (!confirm('Delete this analysis and all of its stored data (source text, graph, documentation, chat)? This cannot be undone.')) return;
      try { await del(`/api/v1/analyses/${id}`); toast('Analysis deleted'); navigate('/'); } catch (e) { toast(e.message, 'bad'); } } } }, icon('trash'), 'Delete'));
    mount(head, el('div', { class: 'inner' },
      el('div', { class: 'crumbs' }, el('a', { href: '#/' }, 'Analyses'), icon('arrow'), a.repository.full_name),
      el('div', { class: 'row spread' }, el('div', {}, el('div', { class: 'repo-title' }, el('h1', { text: a.repository.full_name }), statusBadge(a.status), a.summary.partial ? badge('partial analysis', 'warn') : null),
        el('div', { class: 'small muted row', style: '' }, icon('branch'), `${a.default_branch} @ `, el('a', { class: 'mono', href: `${a.repository.url}/commit/${a.commit_sha}`, rel: 'noopener noreferrer', target: '_blank', text: shortSha(a.commit_sha) }), a.repository.language ? ` · ${a.repository.language}` : '', a.repository.description ? ` · ${a.repository.description}` : '')), el('div', { class: 'row' }, actions)),
      isActive(a.status) ? el('div', { 'aria-live': 'polite' }, pipeline(), el('p', { class: 'small muted' }, a.stage ? `${a.stage}… ` : '', progressText(), ` Elapsed ${fmtDuration(a.elapsed_seconds)}.`, a.status === 'RETRYING' ? ` Temporary error — retry scheduled${a.retry_after ? ' around ' + fmtDate(a.retry_after) : ''}.` : '')) : null,
      a.status === 'FAILED' ? el('div', { class: 'banner bad', role: 'alert' }, icon('alert'), el('div', {}, el('strong', { text: 'Analysis failed. ' }), a.error ? a.error.message : '', a.retry_eligible ? ' This kind of failure is usually temporary — you can retry.' : ' Retrying will not help until the input changes.', a.error ? el('span', { class: 'small', text: ` (code ${a.error.code})` }) : null)) : null,
      a.status === 'CANCELLED' ? el('div', { class: 'banner' }, icon('x'), 'This analysis was cancelled.') : null,
      a.summary.partial ? el('div', { class: 'banner warn' }, icon('alert'), el('div', {}, el('strong', { text: 'Partial analysis: ' }), a.summary.partial_reasons.join('; '))) : null,
      el('nav', { class: 'tabs', 'aria-label': 'Analysis sections' }, TABS.map(([k, label, ic]) => { const on = k === 'overview' || a.graph_complete;
        return el('a', { href: on ? `#/a/${id}${k === 'overview' ? '' : '/' + k}` : '#', 'aria-current': k === tab ? 'page' : null, 'aria-disabled': on ? null : 'true', title: on ? null : 'Available once the code graph has been built', on: on ? {} : { click: (e) => e.preventDefault() } }, icon(ic), label); }))));
  }
  async function renderBody(force) {
    const key = `${tab}:${a.graph_complete}`;
    if (!force && renderedFor === key) { if (tab === 'overview') mount(body, overview()); return; }
    renderedFor = key; if (inner && inner.cleanup) inner.cleanup(); inner = null;
    body.className = 'page' + (tab === 'graph' ? '' : '');
    if (tab === 'overview') { mount(body, overview()); return; }
    if (!a.graph_complete) { mount(body, el('div', { class: 'card empty' }, spinner('Waiting for the code graph…'))); return; }
    mount(body, el('div', { class: 'skeleton', style: '' }));
    try {
      const mod = { graph: graphView, files: filesView, docs: docsView, health: healthView, impact: impactView, chat: chatView }[tab]; if (!mod) throw new Error('Unknown section');
      inner = await mod(a, query, { goto: (t, q) => navigate(`/a/${id}/${t}${q ? '?' + new URLSearchParams(q) : ''}`) });
      mount(body, inner.node); if (inner.after) inner.after();
    } catch (e) { mount(body, errorBox(e, () => renderBody(true))); }
  }
  function overview() {
    const g = a.summary.graph, inv = a.summary.inventory; const cards = [];
    if (g) {
      const nt = g.nodes_by_type || {}, er = g.edges_by_resolution || {}; const tot = Math.max(1, (er.verified_static || 0) + (er.inferred || 0) + (er.unresolved || 0));
      cards.push(el('section', { class: 'card w12' }, el('div', { class: 'stats' },
        ...[[inv ? inv.python_analyzed : 0, 'Python files'], [g.route_count || 0, 'Routes'], [nt.model || 0, 'Data models'], [nt.external_dependency || 0, 'Packages'], [g.edge_count || 0, 'Connections'], [a.summary.parse ? a.summary.parse.failed : 0, 'Parse failures']]
          .map(([n, l]) => el('div', { class: 'stat' }, el('b', { text: String(n) }), el('span', { text: l }))))));
      cards.push(el('section', { class: 'card w8' }, el('div', { class: 'row spread' }, el('h2', { text: 'Architecture at a glance' }), el('a', { class: 'btn sm', href: `#/a/${id}/graph` }, 'Open the map', icon('arrow'))), el('div', { class: 'neigh', id: 'glance', style: '' })));
      cards.push(el('section', { class: 'card w4' }, el('h2', { text: 'How far to trust the map' }), el('div', { class: 'trustbar', role: 'img', 'aria-label': `${er.verified_static || 0} verified, ${er.inferred || 0} inferred, ${er.unresolved || 0} unresolved connections` },
        el('i', { class: 'v', style: `width:${(100 * (er.verified_static || 0)) / tot}%` }), el('i', { class: 'i', style: `width:${(100 * (er.inferred || 0)) / tot}%` }), el('i', { class: 'u', style: `width:${(100 * (er.unresolved || 0)) / tot}%` })),
        el('dl', { class: 'kv' }, el('dt', {}, badge('verified', 'ok')), el('dd', { text: `${er.verified_static || 0} — proven by syntax` }), el('dt', {}, badge('inferred', 'warn')), el('dd', { text: `${er.inferred || 0} — heuristic` }), el('dt', {}, badge('unresolved', 'bad')), el('dd', { text: `${er.unresolved || 0} — target unknown` })),
        el('p', { class: 'small muted', text: 'No numeric confidence is shown: there is no calibrated way to produce one.' }),
        el('div', { class: 'small muted', style: '', text: (g.detected_frameworks || []).length ? 'Detected: ' + g.detected_frameworks.join(', ') : '' })));
    }
    if (inv) { const ex = Object.entries(inv.excluded_by_reason || {}); cards.push(el('section', { class: 'card w4' }, el('h2', { text: 'Coverage' }), el('p', { class: 'small', text: `${inv.files_considered} files inspected at ${shortSha(a.commit_sha)}.` }),
      ex.length ? el('p', { class: 'small muted', text: 'Excluded: ' + ex.map(([k, v]) => `${k.replaceAll('_', ' ')} (${v})`).join(', ') }) : null,
      inv.redacted_files ? el('p', { class: 'small' }, badge('redacted', 'warn'), ` ${inv.redacted_files} file(s) had secret-like text redacted before storage.`) : null)); }
    const eps = (a.summary.entry_points || []).slice(0, 6);
    if (eps.length) cards.push(el('section', { class: 'card w4' }, el('h2', { text: 'Entry points' }), el('ul', { class: 'list-reset small stack' }, eps.map((e) => el('li', {}, el('button', { class: 'linklike mono', type: 'button', on: { click: () => navigate(`/a/${id}/files?path=${encodeURIComponent(e.path)}&line=${e.line}`) }, text: `${e.path}:${e.line}` }), el('div', { class: 'muted' }, inline(e.reason)))))));
    if (a.transitions) cards.push(el('section', { class: 'card w4' }, el('h2', { text: 'Timeline' }), el('ol', { class: 'timeline' }, a.transitions.map((t) => el('li', { class: t.to === 'FAILED' ? 'bad' : t.to === 'RETRYING' ? 'warn' : '' }, el('strong', { text: t.to }), el('span', { class: 'muted', text: ` · ${t.actor}${t.error_code ? ' · ' + t.error_code : ''}` }), el('div', { class: 'muted', text: fmtDate(t.at) }))))));
    if (!cards.length) cards.push(el('div', { class: 'card empty w12' }, isActive(a.status) ? spinner('Analysis in progress — results appear here as stages complete.') : 'No results.'));
    return el('div', { class: 'bento' }, cards);
  }
  let glance = null;
  async function mountGlance() {
    const host = body.querySelector('#glance'); if (!host || !a.graph_complete || glance === host) return; glance = host;
    try { const d = await get(`/api/v1/analyses/${id}/graph/flow?limit=14&include_external=false`); if (dead || !host.isConnected) return; host.replaceChildren(); const f = createFlow(host, { id: 'glance', minimap: false, label: 'Architecture preview' }); f.setData(d); host.addEventListener('dblclick', () => navigate(`/a/${id}/graph`)); } catch { host.replaceChildren(el('p', { class: 'empty small', text: 'Preview unavailable.' })); }
  }
  async function poll(immediate) {
    clearTimeout(timer); if (dead) return;
    const run = async () => {
      if (dead) return; if (document.hidden) { timer = setTimeout(run, 5000); return; }
      try { const pg = a.graph_complete, ps = a.status; a = await get(`/api/v1/analyses/${id}`); session.analysis = a; renderHead(); if (a.graph_complete !== pg || a.status !== ps) { await renderBody(a.graph_complete !== pg); if (tab === 'overview') mountGlance(); } else if (tab === 'overview') { await renderBody(false); glance = null; mountGlance(); } delay = 2500; }
      catch { delay = Math.min(delay * 2, 15000); }
      if (isActive(a.status)) timer = setTimeout(run, delay);
    };
    if (immediate) await run(); else if (isActive(a.status)) timer = setTimeout(run, delay);
  }
  renderHead(); await renderBody(true); if (tab === 'overview') mountGlance(); poll(false);
  return { node: root, cleanup: () => { dead = true; clearTimeout(timer); if (inner && inner.cleanup) inner.cleanup(); } };
}
