import { get } from './api.js';
import { el, mount, spinner, badge, resolutionBadge, sourceLabel, fmtBytes, debounce, shortSha } from './util.js';
import { icon } from './icons.js';
import { highlightLine } from './highlight.js';
import { createFlow } from './flow.js';
import { errorBox } from './app.js';

export async function filesView(a, query, ctx) {
  const id = a.analysis_id; let dead = false, currentId = null, lastPath = '', neighFlow = null;
  const q = el('input', { type: 'search', id: 'file-q', placeholder: 'Filter files…', 'aria-label': 'Filter files by path', maxlength: 100 });
  const kind = el('select', { 'aria-label': 'File kind', on: { change: loadList } }, [['python', 'Python'], ['support', 'Setup & docs'], ['', 'All (incl. excluded)']].map(([v, l]) => el('option', { value: v, text: l })));
  const list = el('div', { class: 'tree-body' }); const viewer = el('div', { class: 'stack-lg', 'aria-live': 'polite' });
  async function loadList() {
    const p = new URLSearchParams({ limit: '300' }); if (q.value.trim()) p.set('q', q.value.trim()); if (kind.value) p.set('kind', kind.value); else p.set('limit', '500');
    mount(list, spinner());
    try { const d = await get(`/api/v1/analyses/${id}/files?${p}`); if (dead) return;
      mount(list, d.items.length ? el('ul', { class: 'list-reset', 'aria-label': 'Files' }, d.items.map((f) => { const i = f.path.lastIndexOf('/'); return el('li', {}, el('button', { type: 'button', 'aria-current': f.path === lastPath ? 'true' : null, title: f.status === 'excluded' ? `Excluded: ${f.excluded_reason}` : '', on: { click: () => open(f.id, null, f.path) } },
        icon(f.status === 'excluded' ? 'lock' : 'files'), el('span', {}, i >= 0 ? el('span', { class: 'dir', text: f.path.slice(0, i + 1) }) : null, f.path.slice(i + 1), f.status === 'parse_error' ? ' ⚠' : ''))); })) : el('p', { class: 'empty small', text: 'No files match.' }));
      if (d.total > d.items.length) list.appendChild(el('p', { class: 'small muted', style: '', text: `Showing ${d.items.length} of ${d.total}.` }));
    } catch (e) { mount(list, errorBox(e, loadList)); }
  }
  const parseLine = (v) => { if (!v) return [0, 0]; const m = /^(\d+)(?:-(\d+))?$/.exec(String(v)); return m ? [+m[1], +(m[2] || m[1])] : [0, 0]; };
  function jump(s, e) { for (const n of viewer.querySelectorAll('.ln.hl')) n.classList.remove('hl'); for (let n = s; n <= (e || s); n++) document.getElementById('L' + n)?.classList.add('hl'); document.getElementById('L' + s)?.scrollIntoView({ block: 'center' }); }
  async function open(fileId, line, path) {
    currentId = fileId; if (path) lastPath = path; mount(viewer, el('div', { class: 'skeleton', style: '' }));
    for (const b of list.querySelectorAll('button')) b.removeAttribute('aria-current');
    try {
      const f = await get(`/api/v1/analyses/${id}/files/${fileId}`); if (dead) return; lastPath = f.path;
      for (const b of list.querySelectorAll('button')) if (b.textContent.replace(' ⚠', '') === f.path) b.setAttribute('aria-current', 'true');
      const [hs, he] = parseLine(line); const code = el('div', { class: 'code', role: 'region', 'aria-label': `Source of ${f.path}`, tabindex: '0' });
      if (f.content != null) { const state = { inDoc: null }; f.content.split('\n').forEach((t, i) => { const n = i + 1; code.appendChild(el('div', { class: 'ln' + (hs && n >= hs && n <= he ? ' hl' : ''), id: 'L' + n }, el('span', { text: String(n), 'aria-hidden': 'true' }), el('span', {}, f.path.endsWith('.py') ? highlightLine(t, state) : t))); }); }
      else code.appendChild(el('p', { class: 'empty', text: f.status === 'excluded' ? `Not stored — excluded (${(f.excluded_reason || '').replaceAll('_', ' ')}).` : 'Source text is not stored for this file.' }));
      const rel = f.relationships;
      const relList = (title, items) => items.length ? el('div', {}, el('h3', { text: title }), el('div', { class: 'rel' }, items.slice(0, 40).map((r) => el('button', { type: 'button', on: { click: () => (r.path && !r.unresolved ? ctx.goto('files', { path: r.path }) : null) } }, icon(r.unresolved ? 'alert' : 'module'), el('span', { class: 'mono', text: r.name }), el('span', { class: 'tag' }, resolutionBadge(r.resolution)))))) : null;
      const neigh = el('div', { class: 'neigh' });
      mount(viewer,
        el('section', { class: 'card' }, el('div', { class: 'row spread' }, el('h2', { class: 'mono', text: f.path }), el('div', { class: 'row' }, f.symbols.some((s) => s.type === 'route') ? el('button', { class: 'btn sm', type: 'button', on: { click: () => ctx.goto('graph', { mode: 'trace' }) } }, icon('trace'), 'Trace routes') : null, el('a', { class: 'btn sm', href: f.source_url, rel: 'noopener noreferrer', target: '_blank' }, icon('github'), 'GitHub'))),
          el('p', { class: 'small muted', text: `${f.line_count} lines · ${fmtBytes(f.size_bytes)} · pinned to commit ${shortSha(f.commit_sha)}` }),
          el('div', { class: 'row' }, f.redacted ? badge('secret-like text redacted', 'warn') : null, f.contains_secret_like ? badge('excluded from AI context', 'warn') : null, f.status === 'parse_error' ? badge('could not be parsed', 'bad') : null),
          f.parse_warning ? el('p', { class: 'small', text: f.parse_warning }) : null, f.explanation ? el('div', {}, sourceLabel(f.explanation_source), el('p', { text: f.explanation })) : null),
        f.module_node_id ? el('section', {}, el('div', { class: 'row spread' }, el('h3', { text: 'Where this file sits' }), el('button', { class: 'linklike small', type: 'button', on: { click: () => ctx.goto('graph', { select: f.path }) } }, 'Open in atlas')), neigh) : null,
        f.symbols.length ? el('section', {}, el('h3', { text: 'Symbols' }), el('div', { class: 'chips' }, f.symbols.slice(0, 60).map((s) => el('button', { class: 'chip', type: 'button', title: s.type, on: { click: () => jump(s.start_line, s.end_line) }, text: s.type === 'worker' ? s.name : `${s.name}:${s.start_line}` })))) : null,
        code, relList('Imports', rel.imports), relList('Imported by', rel.imported_by), relList('Tests', rel.tested_by), relList('Configuration', rel.configured_by));
      if (f.module_node_id) { try { const d = await get(`/api/v1/analyses/${id}/graph/flow?focus=${encodeURIComponent(f.path)}&limit=10&include_tests=true`); if (!dead && neigh.isConnected) { const fl = createFlow(neigh, { id: 'neigh', minimap: false, label: `Connections of ${f.path}` }); fl.setData(d); const me = d.nodes.find((n) => n.path === f.path); if (me) fl.select(me.id); } } catch { neigh.replaceChildren(el('p', { class: 'empty small', text: 'Connection preview unavailable.' })); } }
      if (hs) setTimeout(() => document.getElementById('L' + hs)?.scrollIntoView({ block: 'center' }), 40);
    } catch (e) { mount(viewer, errorBox(e, () => open(fileId, line))); }
  }
  q.addEventListener('input', debounce(loadList, 300)); await loadList();
  mount(viewer, el('div', { class: 'card empty' }, icon('files'), el('h3', { text: 'Pick a file' }), el('p', { class: 'small', text: 'See its source, a map of its connections, and what the analysis found. Press Ctrl/⌘ K to jump to any file.' })));
  if (query.path) { try { const d = await get(`/api/v1/analyses/${id}/files?q=${encodeURIComponent(query.path)}&limit=50`); const hit = d.items.find((f) => f.path === query.path) || d.items[0]; if (hit) await open(hit.id, query.line, hit.path); else mount(viewer, el('div', { class: 'banner warn' }, icon('alert'), `No stored file matches ${query.path}.`)); } catch (e) { mount(viewer, errorBox(e)); } }
  return { node: el('div', { class: 'stack-lg' }, el('div', {}, el('div', { class: 'eyebrow', text: 'Source' }), el('h2', { text: 'Files at the pinned commit' }), el('p', { class: 'small muted', text: 'Only Python and setup files are stored; secret-like values are redacted before storage.' })),
    el('div', { class: 'files' }, el('div', { class: 'tree' }, el('div', { class: 'tree-head' }, q, kind), list), viewer)), cleanup: () => { dead = true; } };
}
