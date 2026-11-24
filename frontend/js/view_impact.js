import { get, post } from './api.js';
import { el, mount, badge, resolutionBadge, fmtDate, shortSha, spinner } from './util.js';
import { icon } from './icons.js';
import { createFlow } from './flow.js';
import { errorBox } from './app.js';
import { atLeast, sourceTarget, sourceLabel } from './insights.js';

// Change impact (POST/GET /analyses/{id}/impact): a GitHub compare mapped onto the analyzed commit's graph.
export async function impactView(a, query, ctx) {
  const id = a.analysis_id; const ready = a.status === 'READY'; let dead = false, report = null, flow = null;
  const base = el('input', { type: 'text', id: 'impact-base', name: 'base', maxlength: 200, placeholder: 'Parent commit (default) — or a branch, tag or SHA', autocomplete: 'off', disabled: !ready });
  const run = el('button', { class: 'btn primary', type: 'submit', disabled: !ready }, icon('branch'), 'Analyze change');
  const formErr = el('div', { role: 'alert' }); const hist = el('div'); const out = el('div', { class: 'stack-lg', 'aria-live': 'polite' });
  const minRes = el('select', { 'aria-label': 'Minimum link confidence', on: { change: () => report && render(report) } },
    [['', 'All links'], ['inferred', 'Verified + inferred'], ['verified_static', 'Verified only']].map(([v, l]) => el('option', { value: v, text: l })));
  const open = (t) => ctx.goto('files', sourceTarget(t));
  const fileBtn = (path, line, enabled = true) => enabled ? el('button', { class: 'linklike mono', type: 'button', on: { click: () => open({ path, line }) }, text: line ? `${path}:${line}` : path }) : el('span', { class: 'mono', text: path });

  const form = el('form', { class: 'card stack', novalidate: 'true' }, el('label', { for: 'impact-base', text: 'Compare against' }),
    el('div', { class: 'row impact-form' }, base, run),
    el('p', { class: 'hint', text: ready ? `Compares the base with the analyzed commit ${shortSha(a.commit_sha)} using GitHub, then maps the changed files onto this analysis's graph.` : 'Change impact is available once the analysis is ready.' }), formErr);
  form.addEventListener('submit', async (e) => {
    e.preventDefault(); if (!ready || run.disabled) return; formErr.replaceChildren(); run.disabled = true; mount(out, el('div', { class: 'card' }, spinner('Comparing with GitHub and mapping the change…')));
    try { const d = await post(`/api/v1/analyses/${id}/impact`, base.value.trim() ? { base: base.value.trim() } : {}); if (dead) return; render(d); loadHistory(d.id); }
    catch (x) { if (dead) return; formErr.replaceChildren(errorBox(x)); if (report) render(report); else empty(); }
    finally { run.disabled = !ready; }
  });

  async function loadHistory(current) {
    try {
      const d = await get(`/api/v1/analyses/${id}/impact`); if (dead) return;
      mount(hist, d.items.length ? el('section', { class: 'card flat' }, el('h3', { text: 'Recent comparisons' }), el('ul', { class: 'list-reset rel impact-hist' }, d.items.map((r) => el('li', {}, el('button', { type: 'button', dataset: { rid: r.id }, 'aria-current': r.id === current ? 'true' : null, on: { click: () => show(r.id) } },
        icon('branch'), el('span', { class: 'mono', text: r.base_ref.length > 30 ? shortSha(r.base_ref) : r.base_ref }), el('span', { class: 'tag', text: `${r.summary.changed_files ?? 0} files · ${fmtDate(r.created_at)}` })))))) : null);
      return d.items;
    } catch (e) { if (!dead) mount(hist, errorBox(e, () => loadHistory(current))); return []; }
  }
  async function show(rid) {
    mount(out, el('div', { class: 'skeleton', style: 'height:160px' }));
    try { const d = await get(`/api/v1/analyses/${id}/impact/${rid}`); if (!dead) { render(d); hist.querySelectorAll('button[data-rid]').forEach((b) => (b.dataset.rid === rid ? b.setAttribute('aria-current', 'true') : b.removeAttribute('aria-current'))); } }
    catch (e) { if (!dead) mount(out, errorBox(e, () => show(rid))); }
  }

  const table = (title, cols, rows, empty) => el('section', { class: 'card stack', dataset: { section: title } }, el('div', { class: 'row spread' }, el('h2', { text: title }), el('span', { class: 'small muted', text: String(rows.length) })),
    rows.length ? el('div', { class: 'table-wrap' }, el('table', {}, el('thead', {}, el('tr', {}, cols.map((c) => el('th', { text: c })))), el('tbody', {}, rows))) : el('p', { class: 'small muted', text: empty }));
  function render(d) {
    report = d; if (flow && flow.destroy) flow.destroy(); flow = null; const s = d.summary || {}; const min = minRes.value;
    const changed = d.changed.map((c) => el('tr', {}, el('td', {}, fileBtn(c.path, null, c.in_graph && !c.removed), c.previous_path ? el('div', { class: 'small muted', text: `renamed from ${c.previous_path}` }) : null, c.note ? el('div', { class: 'small muted', text: c.note }) : null),
      el('td', {}, badge(c.status, c.removed ? 'bad' : 'neutral')), el('td', { text: c.kind }), el('td', { class: 'mono small', text: `+${c.additions ?? 0} −${c.deletions ?? 0}` })));
    const affected = atLeast(d.affected, min).map((x) => el('tr', {}, el('td', {}, fileBtn(x.path)), el('td', { text: String(x.distance) }), el('td', {}, fileBtn(x.via)), el('td', {}, resolutionBadge(x.resolution))));
    const routes = atLeast(d.routes, min).map((r) => el('tr', {}, el('td', { class: 'mono', text: `${r.method || '?'} ${r.path || '(unknown path)'}` }, r.path_status && r.path_status !== 'constant' ? el('div', {}, badge(`path ${r.path_status}`, 'warn')) : null),
      el('td', {}, fileBtn(r.file, r.line)), el('td', { class: 'small', text: r.reason }), el('td', {}, resolutionBadge(r.resolution))));
    const tests = atLeast(d.tests, min).map((t) => el('tr', {}, el('td', {}, fileBtn(t.path)), el('td', { class: 'small', text: t.reason }), el('td', {}, resolutionBadge(t.resolution))));
    const fe = atLeast(d.frontend, min).map((f) => el('tr', {}, el('td', {}, fileBtn(f.path)), el('td', { class: 'small', text: f.reason }, (f.evidence || []).length ? el('div', { class: 'chips' }, f.evidence.map((ev) => el('button', { class: 'chip', type: 'button', on: { click: () => open(ev) }, text: sourceLabel(ev) }))) : null), el('td', {}, resolutionBadge(f.resolution))));
    const graphHost = el('div', { class: 'neigh impact-graph' });
    mount(out,
      el('section', { class: 'card stack' }, el('div', { class: 'row spread' }, el('div', {}, el('h2', { class: 'mono', text: `${d.base_ref.length > 30 ? shortSha(d.base_ref) : d.base_ref} → ${shortSha(d.head_sha)}` }),
        el('div', { class: 'small muted', text: `${d.status || 'compared'}${d.ahead_by != null ? ` · ${d.ahead_by} commit${d.ahead_by === 1 ? '' : 's'} ahead` : ''}${d.created_at ? ' · ' + fmtDate(d.created_at) : ''}` })),
        el('a', { class: 'btn sm', href: d.compare_url, rel: 'noopener noreferrer', target: '_blank' }, icon('github'), 'View diff on GitHub')),
        d.truncated ? el('div', { class: 'banner warn' }, icon('alert'), 'GitHub returned its maximum of 300 files; the change list is truncated.') : null,
        el('div', { class: 'stats' }, [[s.changed_files, 'Changed files'], [s.affected_modules, 'Dependent modules'], [s.routes, 'Routes'], [s.relevant_tests, 'Relevant tests'], [s.frontend_touched, 'Frontend files'], [s.removed, 'Removed']]
          .map(([n, l]) => el('div', { class: 'stat' }, el('b', { text: String(n ?? 0) }), el('span', { text: l }))))),
      el('div', { class: 'toolbar filterbar', role: 'group', 'aria-label': 'Filter impact links' }, el('span', { class: 'small muted', text: 'Show links that are' }), minRes,
        el('span', { class: 'small muted' }, resolutionBadge('verified_static'), ' proven by syntax · ', resolutionBadge('inferred'), ' heuristic · ', resolutionBadge('unresolved'), ' target unknown')),
      table('Changed files', ['File', 'Status', 'Kind', 'Lines'], changed, 'No files changed in this range.'),
      table('Affected modules', ['Module', 'Hops', 'Via', 'Link'], affected, min ? 'No dependent modules at this confidence.' : 'No other module imports the changed code.'),
      table('Affected routes', ['Route', 'Handler', 'Why', 'Link'], routes, 'No FastAPI route handlers are in changed or dependent files.'),
      table('Potentially relevant tests', ['Test file', 'Why', 'Link'], tests, 'No statically linked tests were found. That does not mean the change is untested.'),
      d.frontend.length ? table('Frontend', ['File', 'Why', 'Link'], fe, 'No frontend links at this confidence.') : null,
      d.graph && d.graph.nodes.length ? el('section', { class: 'stack' }, el('h3', { text: 'Change neighbourhood' }), graphHost) : null,
      el('section', { class: 'card flat' }, el('h3', { text: 'Limitations' }), el('ul', { class: 'small muted' }, (d.limitations || []).map((l) => el('li', { text: l })))));
    if (d.graph && d.graph.nodes.length) { try { flow = createFlow(graphHost, { id: 'impact', minimap: false, label: 'Changed files, their dependents and related tests' }); flow.setData(d.graph); } catch { graphHost.replaceChildren(el('p', { class: 'empty small', text: 'Graph preview unavailable.' })); } }
  }

  const node = el('div', { class: 'stack-lg' }, el('div', {}, el('div', { class: 'eyebrow', text: 'Impact' }), el('h2', { text: 'What does a change touch?' }),
    el('p', { class: 'small muted', text: 'Static import, route and test links only. Tests are potentially relevant, not a guaranteed regression set, and nothing is run.' })),
    el('div', { class: 'impact-shell' }, el('div', { class: 'stack' }, form, hist), out));
  const empty = () => mount(out, el('div', { class: 'card empty' }, icon('branch'), el('h3', { text: 'No comparison yet' }), el('p', { class: 'small', text: ready ? 'Leave the field empty to compare with the parent commit.' : 'Wait for the analysis to finish.' })));
  empty();
  const items = await loadHistory(query.report);
  const first = query.report || (items && items[0] && items[0].id);
  if (first) await show(first);
  return { node, cleanup: () => { dead = true; if (flow && flow.destroy) flow.destroy(); } };
}
