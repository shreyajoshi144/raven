import { get } from './api.js';
import { el, mount, badge } from './util.js';
import { icon } from './icons.js';
import { errorBox } from './app.js';
import { SEVERITIES, CONFIDENCES, CATEGORIES, KINDS, label, severityKind, confidenceKind, readinessQuery, sourceTarget, sourceLabel } from './insights.js';

// Engineering-readiness report (GET /analyses/{id}/readiness). Filters are the API's own query parameters.
export async function healthView(a, query, ctx) {
  const id = a.analysis_id; let dead = false, seq = 0;
  const filters = { severity: query.severity || '', min_confidence: query.min_confidence || '', category: query.category || '', kind: query.kind || '' };
  const select = (key, aria, first, values) => { const s = el('select', { 'aria-label': aria, name: key, on: { change: () => { filters[key] = s.value; load(); } } }, el('option', { value: '', text: first }), values.map((v) => el('option', { value: v, text: label(v) })));
    s.value = filters[key]; return s; };
  const sels = [select('severity', 'Severity', 'Any severity', SEVERITIES), select('min_confidence', 'Minimum confidence', 'Any confidence', CONFIDENCES),
    select('category', 'Category', 'All categories', CATEGORIES), select('kind', 'Finding kind', 'All kinds', KINDS)];
  sels[1].querySelectorAll('option').forEach((o) => { if (o.value) o.textContent = o.value === 'low' ? 'low or better (all)' : `${o.value}${o.value === 'high' ? ' only' : ' or better'}`; });
  const reset = () => { for (const s of sels) { s.value = ''; filters[s.name] = ''; } load(); };
  const summary = el('div'); const list = el('div', { class: 'stack', 'aria-live': 'polite' });
  const open = (ev) => ctx.goto('files', sourceTarget(ev));

  function finding(f) {
    const more = (f.evidence_total || 0) - f.evidence.length;
    return el('article', { class: 'card finding', dataset: { rule: f.rule } },
      el('div', { class: 'row' }, badge(f.severity, severityKind(f.severity), 'Severity: impact if the concern is real'), badge(`${f.confidence} confidence`, confidenceKind(f.confidence), 'How sure the analyzer is that the pattern is what it says (independent of severity)'),
        badge(label(f.category), 'neutral'), badge(label(f.kind), f.kind === 'potential_risk' ? 'warn' : 'neutral'), el('span', { class: 'small muted mono', text: f.rule })),
      el('h3', { text: f.title }), el('p', { class: 'small', text: f.detail }), el('p', { class: 'small muted', text: f.claim }),
      f.basis ? el('p', { class: 'small' }, el('strong', { text: 'Searched: ' }), f.basis) : null,
      el('dl', { class: 'kv small' }, el('dt', { text: 'Recommendation' }), el('dd', { text: f.recommendation }), el('dt', { text: 'How to verify' }), el('dd', { text: f.verify })),
      f.evidence.length ? el('div', {}, el('div', { class: 'small muted', text: 'Evidence' }), el('div', { class: 'chips' }, f.evidence.map((ev) => el('button', { class: 'chip', type: 'button', title: 'Open in the source viewer', on: { click: () => open(ev) } }, sourceLabel(ev), ev.note ? ` · ${ev.note}` : ''))),
        more > 0 ? el('p', { class: 'small muted', text: `+${more} more location${more > 1 ? 's' : ''} not listed.` }) : null) : null);
  }
  function renderSummary(d) {
    const s = d.summary || {}; const bySev = s.by_severity || {}; const sc = s.scope || {};
    mount(summary, el('div', { class: 'stack' },
      el('div', { class: 'banner' }, icon('lock'), el('div', {}, d.disclaimer)),
      d.partial_analysis ? el('div', { class: 'banner warn' }, icon('alert'), el('div', {}, el('strong', { text: 'Partial analysis: ' }), 'some files were not analyzed, so the report is incomplete.')) : null,
      el('div', { class: 'bento' },
        el('section', { class: 'card w8' }, el('h2', { text: 'Findings by severity' }), el('div', { class: 'stats' }, SEVERITIES.map((k) => el('button', { class: 'stat statbtn', type: 'button', 'aria-pressed': filters.severity === k ? 'true' : 'false', title: `Show only ${k}`,
          on: { click: () => { filters.severity = filters.severity === k ? '' : k; sels[0].value = filters.severity; load(); } } }, el('b', { text: String(bySev[k] || 0) }), el('span', { text: k })))),
          el('p', { class: 'small muted', text: `${s.total || 0} findings across ${sc.application_files ?? '?'} application files, ${sc.test_files ?? '?'} test files, ${sc.frontend_files ?? 0} frontend files and ${sc.routes ?? 0} routes.` })),
        el('section', { class: 'card w4' }, el('h2', { text: 'Not assessed' }), el('ul', { class: 'small muted' }, (d.not_assessed || []).map((x) => el('li', { text: x })))))));
  }
  async function load() {
    const my = ++seq; mount(list, el('div', { class: 'skeleton', style: 'height:120px' }));
    for (const s of sels) s.disabled = true;
    try {
      const qs = readinessQuery(filters); const d = await get(`/api/v1/analyses/${id}/readiness${qs ? '?' + qs : ''}`); if (dead || my !== seq) return;
      if (!d.available) { mount(summary); mount(list, el('div', { class: 'card empty' }, icon('alert'), el('h3', { text: 'No readiness report for this analysis' }), el('p', { class: 'small', text: d.reason }))); return; }
      renderSummary(d);
      mount(list, el('p', { class: 'small muted', text: d.filtered ? `${d.findings.length} of ${d.summary.total} findings match the filters.` : `${d.findings.length} findings, most severe first.` }),
        d.findings.length ? d.findings.map(finding) : el('div', { class: 'card empty' }, icon('check'), el('h3', { text: d.filtered ? 'No findings match these filters' : 'No findings' }),
          d.filtered ? el('button', { class: 'btn sm', type: 'button', on: { click: reset } }, 'Clear filters') : el('p', { class: 'small', text: 'The static checks found nothing to report. That is not proof of absence; see “Not assessed”.' })));
    } catch (e) { if (!dead && my === seq) { mount(summary); mount(list, errorBox(e, load)); } }
    finally { if (my === seq) for (const s of sels) s.disabled = false; }
  }
  await load();
  return { node: el('div', { class: 'stack-lg' }, el('div', {}, el('div', { class: 'eyebrow', text: 'Health' }), el('h2', { text: 'Engineering readiness' }),
    el('p', { class: 'small muted', text: 'Evidence-backed leads from static analysis at the pinned commit. Severity is the impact if a concern is real; confidence is how sure the pattern match is.' })),
    summary, el('div', { class: 'toolbar filterbar', role: 'group', 'aria-label': 'Filter findings' }, icon('search'), sels, el('button', { class: 'btn sm', type: 'button', on: { click: reset } }, 'Reset')), list), cleanup: () => { dead = true; } };
}
