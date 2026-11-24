import { get, post, ApiError } from './api.js';
import { el, mount, statusBadge, fmtDate, shortSha, isActive, toast, PIPELINE } from './util.js';
import { icon } from './icons.js';
import { navigate, errorBox } from './app.js';

const NS = 'http://www.w3.org/2000/svg';
function emptyArt() {
  const s = (t, a = {}) => { const n = document.createElementNS(NS, t); for (const [k, v] of Object.entries(a)) n.setAttribute(k, v); return n; };
  const svg = s('svg', { class: 'art', viewBox: '0 0 120 80', 'aria-hidden': 'true' });
  svg.append(s('rect', { x: 6, y: 8, width: 44, height: 22, rx: 6, fill: '#fff', stroke: '#0a0a0a', 'stroke-width': 2 }), s('rect', { x: 70, y: 8, width: 44, height: 22, rx: 6, fill: '#84cc16', stroke: '#0a0a0a', 'stroke-width': 2 }),
    s('rect', { x: 38, y: 52, width: 44, height: 22, rx: 6, fill: '#fff', stroke: '#0a0a0a', 'stroke-width': 2 }), s('path', { d: 'M50 19 H70 M28 30 C28 42 50 42 56 52 M92 30 C92 42 70 42 64 52', fill: 'none', stroke: '#0a0a0a', 'stroke-width': 2, 'stroke-dasharray': '4 4' }));
  return svg;
}
function miniPipe(status) {
  const idx = PIPELINE.indexOf(status); const failed = status === 'FAILED'; const parts = [];
  PIPELINE.forEach((p, i) => { const done = status === 'READY' || (idx >= 0 && i < idx); parts.push(el('i', { class: done ? 'done' : (i === idx && !failed ? 'active' : (failed && i === Math.max(1, idx) ? 'failed' : '')) })); if (i < PIPELINE.length - 1) parts.push(el('b', { class: done ? 'done' : '' })); });
  return el('div', { class: 'mini-pipe', 'aria-hidden': 'true' }, parts);
}

export async function dashboardView() {
  const listBox = el('div'); const errBox = el('div', { role: 'alert' });
  const url = el('input', { id: 'repo-url', type: 'url', placeholder: 'https://github.com/owner/repository', required: true, maxlength: 300, autocomplete: 'off', 'aria-label': 'Repository URL' });
  const btn = el('button', { class: 'btn primary', type: 'submit' }, 'Analyze', icon('arrow'));
  const form = el('form', { novalidate: 'true' }, el('div', { class: 'cmdbar' }, icon('github'), url, btn), errBox);
  form.addEventListener('submit', async (e) => {
    e.preventDefault(); errBox.replaceChildren(); btn.disabled = true; btn.firstChild.textContent = 'Checking…';
    try { const a = await post('/api/v1/analyses', { url: url.value }); if (a.reused) toast('This commit was already analyzed — opening it.'); navigate('/a/' + a.analysis_id); }
    catch (x) { errBox.replaceChildren(el('div', { class: 'banner bad' }, icon('alert'), el('div', {}, x instanceof ApiError ? x.message : 'Something went wrong.', x.requestId ? el('span', { class: 'small', text: ` (request ${x.requestId})` }) : null))); btn.disabled = false; btn.firstChild.textContent = 'Analyze'; url.focus(); }
  });
  let timer = null, dead = false;
  async function load() {
    try {
      const d = await get('/api/v1/analyses?limit=50'); if (dead) return;
      mount(listBox, d.items.length ? el('div', { class: 'repo-grid' }, d.items.map((a) => el('a', { class: 'repo-card', href: '#/a/' + a.analysis_id },
        el('div', { class: 'row spread' }, statusBadge(a.status), a.summary.partial ? el('span', { class: 'badge warn', text: 'partial' }) : null),
        el('div', { class: 'name mono', text: a.repository.full_name }), el('div', { class: 'meta', text: `commit ${shortSha(a.commit_sha)} · ${fmtDate(a.created_at)}` }),
        a.error ? el('div', { class: 'small', style: '', text: a.error.message }) : (a.summary.graph ? el('div', { class: 'small muted', text: `${a.summary.graph.route_count || 0} routes · ${(a.summary.graph.nodes_by_type || {}).model || 0} models · ${a.summary.inventory ? a.summary.inventory.python_analyzed : 0} files` }) : null), miniPipe(a.status))))
        : el('div', { class: 'empty card flat' }, emptyArt(), el('h3', { text: 'No analyses yet' }), el('p', { class: 'small', text: 'Paste a public repository URL above to map your first codebase.' })));
      if (d.items.some((a) => isActive(a.status))) timer = setTimeout(load, 3500);
    } catch (e) { if (!dead) mount(listBox, errorBox(e, load)); }
  }
  mount(listBox, el('div', { class: 'repo-grid' }, [1, 2, 3].map(() => el('div', { class: 'skeleton', style: '' })))); load();
  const node = el('div', { class: 'page' },
    el('section', { class: 'hero' }, el('div', { class: 'eyebrow', text: 'Static analysis · pinned to a commit' }), el('h1', {}, 'Understand a codebase in ', el('span', { text: 'minutes' }), '.'),
      el('p', { text: 'Paste a public GitHub repository. Raven maps every file, route and model into a navigable flowchart, writes an onboarding guide, and answers questions with cited code.' }), form,
      el('div', { class: 'hero-meta' }, el('span', {}, icon('lock'), ' Never executes your code'), el('span', {}, icon('check'), ' Every edge cites evidence'), el('span', {}, icon('github'), ' Public repositories only'))),
    el('div', { class: 'row spread', style: '' }, el('h2', { text: 'Your analyses' })), el('div', { style: '' }), listBox);
  return { node, cleanup: () => { dead = true; clearTimeout(timer); } };
}
