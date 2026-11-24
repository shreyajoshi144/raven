import { useEffect, useRef } from 'react';
import { get } from '@legacy/api.js';
import { createFlow } from '@legacy/flow.js';
import { fmtDate, shortSha, isActive } from '@legacy/util.js';
import { go } from '../router.js';
import { Card, Badge, Spinner, reasonText } from '../components/ui.jsx';

function Glance({ id }) {
  const ref = useRef(null);
  useEffect(() => {
    let dead = false; let f = null;
    get(`/api/v1/analyses/${id}/graph/flow?limit=14&include_external=false`).then((d) => { if (!dead && ref.current) { f = createFlow(ref.current, { id: 'glance', tile: true, minimap: false, label: 'Architecture preview' }); f.setData(d); } }, () => {});
    return () => { dead = true; if (f) f.destroy(); };
  }, [id]);
  return <div className="neigh" ref={ref} />;
}

export default function Overview({ a }) {
  const g = a.summary.graph; const inv = a.summary.inventory; const id = a.analysis_id;
  if (!g) return <Card className="empty">{isActive(a.status) ? <Spinner label="Analysis in progress. Results appear as stages complete." /> : 'No results.'}</Card>;
  const er = g.edges_by_resolution || {}; const nt = g.nodes_by_type || {}; const tot = Math.max(1, (er.verified_static || 0) + (er.inferred || 0) + (er.unresolved || 0));
  const stats = [[inv?.python_analyzed ?? 0, 'Python files'], [g.route_count || 0, 'Routes'], [nt.model || 0, 'Data models'], [nt.external_dependency || 0, 'Packages'], [g.edge_count || 0, 'Connections'], [a.summary.parse?.failed ?? 0, 'Parse failures']];
  const eps = (a.summary.entry_points || []).slice(0, 6);
  return (
    <div className="bento">
      <Card className="w12"><div className="stats">{stats.map(([n, l]) => <div className="stat" key={l}><b>{n}</b><span>{l}</span></div>)}</div></Card>
      <Card className="w8 stack"><div className="row spread"><h2>Architecture at a glance</h2><a className="btn sm" href={`#/a/${id}/map`}>Open the map →</a></div>{a.graph_complete ? <Glance id={id} /> : null}</Card>
      <Card className="w4 stack"><h2>How far to trust the map</h2>
        <div className="trustbar" role="img" aria-label={`${er.verified_static || 0} verified, ${er.inferred || 0} inferred, ${er.unresolved || 0} unresolved connections`}>
          <i className="v" style={{ width: `${100 * (er.verified_static || 0) / tot}%` }} /><i className="i" style={{ width: `${100 * (er.inferred || 0) / tot}%` }} /><i className="u" style={{ width: `${100 * (er.unresolved || 0) / tot}%` }} /></div>
        <dl className="kv"><dt><Badge kind="ok">verified</Badge></dt><dd>{er.verified_static || 0} proven by syntax</dd><dt><Badge kind="warn">inferred</Badge></dt><dd>{er.inferred || 0} heuristic</dd><dt><Badge kind="bad">unresolved</Badge></dt><dd>{er.unresolved || 0} target unknown</dd></dl>
        <p className="small muted">No numeric confidence is shown: there is no calibrated way to produce one.</p>
        {(g.detected_frameworks || []).length ? <p className="small muted">Detected: {g.detected_frameworks.join(', ')}</p> : null}</Card>
      {inv ? <Card className="w4 stack"><h2>Coverage</h2><p className="small">{inv.files_considered} files inspected at <span className="mono">{shortSha(a.commit_sha)}</span>.</p>
        {a.summary.partial ? <div className="banner warn small"><strong>Incomplete: </strong>{(a.summary.partial_reasons || []).join('; ') || 'some files were not analysed'}</div> : <p className="small"><Badge kind="ok">complete</Badge> every eligible file was analysed.</p>}
        {Object.keys(inv.excluded_by_reason || {}).length ? <><p className="small muted">Not analysed, by reason:</p><ul className="list-reset small">{Object.entries(inv.excluded_by_reason).map(([k, v]) => <li key={k}><b>{v}</b> · {reasonText(k)}</li>)}</ul><a className="btn sm" href={`#/a/${id}/files?kind=skipped`}>List skipped files →</a></> : null}
        {inv.redacted_files ? <p className="small"><Badge kind="warn">redacted</Badge> {inv.redacted_files} file(s) had secret-like text redacted before storage.</p> : null}</Card> : null}
      {eps.length ? <Card className="w4 stack"><h2>Entry points</h2><ul className="list-reset small stack">{eps.map((e) => <li key={e.path + e.line}><button className="linklike mono" type="button" onClick={() => go(`/a/${id}/files`, { path: e.path, line: e.line })}>{e.path}:{e.line}</button><div className="muted">{e.reason.replaceAll('`', '')}</div></li>)}</ul></Card> : null}
      {a.summary.stage_seconds && Object.keys(a.summary.stage_seconds).length ? <Card className="w4 stack"><h2>Where the time went</h2><dl className="kv">{Object.entries(a.summary.stage_seconds).map(([k, v]) => <><dt key={k}>{k.replaceAll('_', ' ')}</dt><dd>{v}s</dd></>)}</dl><p className="small muted">fetch = GitHub download + filtering; health = readiness rules; orchestration = queueing and DB overhead.</p></Card> : null}
      {a.transitions ? <Card className="w4 stack"><h2>Timeline</h2><ol className="timeline">{a.transitions.map((t, i) => <li key={i} className={t.to === 'FAILED' ? 'bad' : t.to === 'RETRYING' ? 'warn' : ''}><strong>{t.to}</strong><span className="muted"> · {t.actor}{t.error_code ? ' · ' + t.error_code : ''}</span><div className="muted">{fmtDate(t.at)}</div></li>)}</ol></Card> : null}
    </div>
  );
}
