import { useState } from 'react';
import { get } from '@legacy/api.js';
import { go } from '../router.js';
import { Badge, Card, ErrorBox, Skeleton, Meter, useAsync } from '../components/ui.jsx';
import { SEVERITIES, CONFIDENCES, CATEGORIES, KINDS, label, severityKind, readinessQuery, sourceTarget, sourceLabel } from '@legacy/insights.js';

const Sel = ({ name, aria, first, values, value, set }) => <select aria-label={aria} name={name} value={value} onChange={(e) => set(name, e.target.value)}><option value="">{first}</option>{values.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>;

export default function Health({ a }) {
  const id = a.analysis_id; const [f, setF] = useState({ severity: '', min_confidence: '', category: '', kind: '' });
  const set = (k, v) => setF((x) => ({ ...x, [k]: v }));
  const q = useAsync(() => { const s = readinessQuery(f); return get(`/api/v1/analyses/${id}/readiness${s ? '?' + s : ''}`); }, [id, f]);
  const d = q.data; const bySev = d?.summary?.by_severity || {}; const sc = d?.summary?.scope || {};
  return (
    <div className="stack-lg">
      <div><div className="eyebrow">Health</div><h2>Engineering readiness</h2><p className="small muted">Evidence-backed leads from static analysis. Severity is the impact if a concern is real; confidence is how sure the pattern match is.</p></div>
      {d?.available ? <>
        <div className="banner"><div>{d.disclaimer}</div></div>
        {d.partial_analysis ? <div className="banner warn"><div><strong>Partial analysis: </strong>some files were not analyzed, so the report is incomplete.</div></div> : null}
        <div className="bento">
          <Card className="w8 stack"><h2>Findings by severity</h2>
            <div className="sevrow">{SEVERITIES.map((k) => <button key={k} type="button" className={`sev ${severityKind(k)}`} aria-pressed={f.severity === k} onClick={() => set('severity', f.severity === k ? '' : k)}><b>{bySev[k] || 0}</b><span>{k}</span></button>)}</div>
            <p className="small muted">{d.summary.total} findings across {sc.application_files ?? '?'} application, {sc.test_files ?? '?'} test and {sc.frontend_files ?? 0} frontend files, {sc.routes ?? 0} routes.</p></Card>
          <Card className="w4 stack"><h2>Not assessed</h2><ul className="small muted">{(d.not_assessed || []).map((x) => <li key={x}>{x}</li>)}</ul></Card>
        </div></> : null}
      <div className="toolbar filterbar" role="group" aria-label="Filter findings">
        <Sel name="severity" aria="Severity" first="Any severity" values={SEVERITIES.map((x) => [x, x])} value={f.severity} set={set} />
        <Sel name="min_confidence" aria="Minimum confidence" first="Any confidence" values={CONFIDENCES.map((c) => [c, c === 'high' ? 'high only' : c === 'low' ? 'low or better (all)' : `${c} or better`])} value={f.min_confidence} set={set} />
        <Sel name="category" aria="Category" first="All categories" values={CATEGORIES.map((x) => [x, label(x)])} value={f.category} set={set} />
        <Sel name="kind" aria="Finding kind" first="All kinds" values={KINDS.map((x) => [x, label(x)])} value={f.kind} set={set} />
        <button className="btn sm" type="button" onClick={() => setF({ severity: '', min_confidence: '', category: '', kind: '' })}>Reset</button>
      </div>
      {q.loading && !d ? <Skeleton h={160} /> : q.error ? <ErrorBox error={q.error} retry={q.reload} /> : !d.available ? <Card className="empty"><h3>No readiness report for this analysis</h3><p className="small">{d.reason}</p></Card> : (
        <div className="stack" aria-live="polite">
          <p className="small muted">{d.filtered ? `${d.findings.length} of ${d.summary.total} findings match the filters.` : `${d.findings.length} findings, most severe first.`}</p>
          {!d.findings.length ? <Card className="empty"><h3>{d.filtered ? 'No findings match these filters' : 'No findings'}</h3>{!d.filtered ? <p className="small">The static checks found nothing to report. That is not proof of absence; see “Not assessed”.</p> : null}</Card> : d.findings.map((x) => (
            <article key={x.id} className="card finding" data-rule={x.rule}>
              <div className="row"><Badge kind={severityKind(x.severity)}>{x.severity}</Badge><span className="conf" title="How sure the analyzer is that the pattern is what it says"><Meter level={x.confidence} />{x.confidence} confidence</span><Badge>{label(x.category)}</Badge><Badge kind={x.kind === 'potential_risk' ? 'warn' : 'neutral'}>{label(x.kind)}</Badge><span className="small muted mono">{x.rule}</span></div>
              <h3>{x.title}</h3><p className="small">{x.detail}</p><p className="small muted">{x.claim}</p>
              {x.basis ? <p className="small"><strong>Searched: </strong>{x.basis}</p> : null}
              <dl className="kv small"><dt>Recommendation</dt><dd>{x.recommendation}</dd><dt>How to verify</dt><dd>{x.verify}</dd></dl>
              {x.evidence.length ? <div><div className="small muted">Evidence</div><div className="chips">{x.evidence.map((ev, i) => <button key={i} className="chip" type="button" title="Open in the source viewer" onClick={() => go(`/a/${id}/files`, sourceTarget(ev))}>{sourceLabel(ev)}{ev.note ? ` · ${ev.note}` : ''}</button>)}</div>
                {x.evidence_total > x.evidence.length ? <p className="small muted">+{x.evidence_total - x.evidence.length} more location{x.evidence_total - x.evidence.length > 1 ? 's' : ''} not listed.</p> : null}</div> : null}
            </article>))}
        </div>)}
    </div>
  );
}
