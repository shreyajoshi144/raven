import { useState } from 'react';
import { get } from '@legacy/api.js';
import { go } from '../router.js';
import { Badge, Card, ErrorBox, Skeleton, useAsync } from '../components/ui.jsx';

const SEV = { high: 'bad', medium: 'warn', low: 'neutral', info: 'neutral' };
const Ev = ({ id, e }) => <button className="linklike mono small" type="button" onClick={() => go(`/a/${id}/files`, { path: e.path, line: e.start_line })}>{e.path}:{e.start_line}<span className="muted"> @{(e.commit_sha || '').slice(0, 7)}</span></button>;
const Delta = ({ v }) => (v ? <span className={v > 0 ? 'bad-text' : 'ok-text'}> {v > 0 ? '+' : ''}{v}</span> : null);

export default function Architecture({ a }) {
  const id = a.analysis_id; const [base, setBase] = useState('');
  const hist = useAsync(() => get(`/api/v1/analyses/${id}/architecture/history`), [id]);
  const drift = useAsync(() => get(`/api/v1/analyses/${id}/architecture/drift${base ? `?base=${base}` : ''}`), [id, base]);
  const pts = hist.data?.points || []; const d = drift.data;
  return (
    <div className="stack-lg">
      <div><div className="eyebrow">Architecture</div><h2>How the structure changed between commits</h2>
        <p className="small muted">Derived from static analysis of each analyzed commit. Layer rules are a directory-name heuristic and are marked inferred.</p></div>
      <Card className="stack"><h3>Evolution</h3>
        {hist.loading ? <Skeleton h={90} /> : hist.error ? <ErrorBox error={hist.error} retry={hist.reload} /> : (
          <div className="tablewrap"><table className="tbl small"><thead><tr><th>Commit</th><th>Modules</th><th>Imports</th><th>Ext. deps</th><th>Cycles</th><th>Boundary</th><th>Complexity</th><th>Routes</th></tr></thead>
            <tbody>{pts.map((p) => <tr key={p.analysis_id} aria-current={p.current ? 'true' : undefined}><td className="mono"><a href={`#/a/${p.analysis_id}/architecture`}>{p.commit_sha.slice(0, 7)}</a>{p.current ? ' · this' : ''}</td>
              {['modules', 'internal_imports', 'external_dependencies', 'cycles', 'boundary_violations', 'total_complexity', 'routes'].map((k) => <td key={k}>{p.metrics[k]}<Delta v={p.delta?.[k]} /></td>)}</tr>)}</tbody></table></div>)}
        {pts.length < 2 && !hist.loading ? <p className="small muted">Only one analyzed commit so far. Analyze a newer commit of this repository to build history.</p> : null}</Card>
      <Card className="stack"><div className="row spread"><h3>Drift</h3>
        {pts.length > 1 ? <label className="small">Compare with <select value={base} onChange={(e) => setBase(e.target.value)}><option value="">previous analysis</option>{pts.filter((p) => !p.current).map((p) => <option key={p.analysis_id} value={p.analysis_id}>{p.commit_sha.slice(0, 7)}</option>)}</select></label> : null}</div>
        {drift.loading ? <Skeleton h={160} /> : drift.error ? <ErrorBox error={drift.error} retry={drift.reload} /> : !d.available ? <p className="empty small">{d.reason}</p> : (<>
          <p className="small"><span className="mono">{d.base.commit_sha.slice(0, 7)}</span> → <span className="mono">{d.head.commit_sha.slice(0, 7)}</span> · {d.findings.length} finding(s)</p>
          {!d.findings.length ? <p className="small"><Badge kind="ok">no drift</Badge> No dependency, cycle, boundary, coupling, complexity or API change was detected.</p> : (
            <ul className="list-reset stack">{d.findings.map((f, i) => <li key={i} className="card stack"><div className="row"><Badge kind={SEV[f.severity]}>{f.severity}</Badge><Badge kind={f.resolution === 'verified_static' ? 'ok' : 'warn'}>{f.resolution === 'verified_static' ? 'verified' : 'inferred'}</Badge><strong>{f.title}</strong></div>
              {f.detail ? <p className="small muted">{f.detail}</p> : null}<div className="row">{f.evidence.map((e, j) => <Ev key={j} id={id} e={e} />)}</div></li>)}</ul>)}
          <h3>Predicted impact</h3><p className="small muted">Static importers of the changed code at the base commit. An estimate, not a guarantee; no test was run.</p>
          <div className="bento">
            <Card className="w4 stack"><h4>Affected modules ({d.predicted_impact.affected_modules.length})</h4><ul className="list-reset small">{d.predicted_impact.affected_modules.map((m) => <li key={m.path}><span className="mono">{m.path}</span> <span className="muted">distance {m.distance}</span></li>)}</ul></Card>
            <Card className="w4 stack"><h4>Routes ({d.predicted_impact.routes.length})</h4><ul className="list-reset small">{d.predicted_impact.routes.map((r) => <li key={r.name}><span className="mono">{r.name}</span> {r.status === 'removed' ? <Badge kind="bad">removed</Badge> : null}</li>)}</ul></Card>
            <Card className="w4 stack"><h4>Tests ({d.predicted_impact.tests.length})</h4><ul className="list-reset small">{d.predicted_impact.tests.map((t) => <li key={t.path} className="mono">{t.path}</li>)}</ul></Card>
          </div>
          {d.predicted_impact.breaking_symbol_users.length ? <Card className="stack"><h4>Possible breaking changes</h4><ul className="list-reset small">{d.predicted_impact.breaking_symbol_users.map((u, i) => <li key={i}><span className="mono">{u.symbol}</span> changed or removed in <span className="mono">{u.defined_in}</span>, referenced by <span className="mono">{u.used_by}</span></li>)}</ul></Card> : null}
          <ul className="small muted">{d.limitations.map((l, i) => <li key={i}>{l}</li>)}</ul></>)}</Card>
    </div>
  );
}
