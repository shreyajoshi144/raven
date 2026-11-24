import { useEffect, useRef, useState } from 'react';
import { get, post } from '@legacy/api.js';
import { createFlow } from '@legacy/flow.js';
import { fmtDate, shortSha } from '@legacy/util.js';
import { go } from '../router.js';
import { Badge, ResolutionBadge, ErrorBox, Spinner, useAsync } from '../components/ui.jsx';
import { atLeast, sourceTarget, sourceLabel } from '@legacy/insights.js';

function Graph({ graph }) {
  const ref = useRef(null);
  useEffect(() => { const f = createFlow(ref.current, { id: 'impact', minimap: false, label: 'Changed files, their dependents and related tests' }); f.setData(graph); return () => f.destroy(); }, [graph]);
  return <div className="neigh impact-graph" ref={ref} />;
}
const Table = ({ title, cols, rows, empty }) => (
  <section className="card stack" data-section={title}><div className="row spread"><h2>{title}</h2><span className="small muted">{rows.length}</span></div>
    {rows.length ? <div className="table-wrap"><table><thead><tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr></thead><tbody>{rows}</tbody></table></div> : <p className="small muted">{empty}</p>}</section>
);

export default function Impact({ a, query }) {
  const id = a.analysis_id; const ready = a.status === 'READY';
  const [base, setBase] = useState(''); const [busy, setBusy] = useState(false); const [formErr, setFormErr] = useState(null); const [report, setReport] = useState(null); const [min, setMin] = useState(''); const [loadErr, setLoadErr] = useState(null);
  const hist = useAsync(() => get(`/api/v1/analyses/${id}/impact`), [id]);
  const show = async (rid) => { setLoadErr(null); try { setReport(await get(`/api/v1/analyses/${id}/impact/${rid}`)); } catch (e) { setLoadErr(e); } };
  useEffect(() => { const rid = query.report || hist.data?.items?.[0]?.id; if (rid && !report) show(rid); }, [hist.data]); // eslint-disable-line react-hooks/exhaustive-deps
  const submit = async (e) => {
    e.preventDefault(); if (!ready || busy) return; setBusy(true); setFormErr(null);
    try { const r = await post(`/api/v1/analyses/${id}/impact`, base.trim() ? { base: base.trim() } : {}); setReport(r); hist.reload(); } catch (x) { setFormErr(x); } finally { setBusy(false); }
  };
  const open = (t) => go(`/a/${id}/files`, sourceTarget(t));
  const File = ({ path, line, on = true }) => (on ? <button className="linklike mono" type="button" onClick={() => open({ path, line })}>{line ? `${path}:${line}` : path}</button> : <span className="mono">{path}</span>);
  const d = report;
  return (
    <div className="stack-lg">
      <div><div className="eyebrow">Impact</div><h2>What does a change touch?</h2><p className="small muted">Static import, route and test links only. Tests are potentially relevant, not a guaranteed regression set, and nothing is run.</p></div>
      <div className="impact-shell">
        <div className="stack">
          <form className="card stack" onSubmit={submit} noValidate><label htmlFor="impact-base">Compare against</label>
            <div className="row impact-form"><input id="impact-base" value={base} onChange={(e) => setBase(e.target.value)} maxLength={200} autoComplete="off" disabled={!ready} placeholder="Parent commit (default), or a branch, tag or SHA" /><button className="btn primary" type="submit" disabled={!ready || busy}>Analyze change</button></div>
            <p className="hint">{ready ? `Compares the base with the analyzed commit ${shortSha(a.commit_sha)} using GitHub, then maps the changed files onto this graph.` : 'Change impact is available once the analysis is ready.'}</p>
            {formErr ? <ErrorBox error={formErr} /> : null}</form>
          {hist.data?.items?.length ? <section className="card flat"><h3>Recent comparisons</h3><ul className="list-reset rel impact-hist">{hist.data.items.map((r) => <li key={r.id}><button type="button" aria-current={d?.id === r.id ? 'true' : undefined} onClick={() => show(r.id)}><span className="mono">{r.base_ref.length > 30 ? shortSha(r.base_ref) : r.base_ref}</span><span className="tag">{r.summary.changed_files ?? 0} files · {fmtDate(r.created_at)}</span></button></li>)}</ul></section> : null}
        </div>
        <div className="stack-lg" aria-live="polite">
          {busy ? <div className="card"><Spinner label="Comparing with GitHub and mapping the change…" /></div> : loadErr ? <ErrorBox error={loadErr} /> : !d ? <div className="card empty"><h3>No comparison yet</h3><p className="small">{ready ? 'Leave the field empty to compare with the parent commit.' : 'Wait for the analysis to finish.'}</p></div> : <>
            <section className="card stack"><div className="row spread"><div><h2 className="mono">{d.base_ref.length > 30 ? shortSha(d.base_ref) : d.base_ref} → {shortSha(d.head_sha)}</h2><div className="small muted">{d.status || 'compared'}{d.ahead_by != null ? ` · ${d.ahead_by} commit${d.ahead_by === 1 ? '' : 's'} ahead` : ''}{d.created_at ? ` · ${fmtDate(d.created_at)}` : ''}</div></div>
              <a className="btn sm" href={d.compare_url} target="_blank" rel="noopener noreferrer">View diff on GitHub ↗</a></div>
              {d.truncated ? <div className="banner warn">GitHub returned its maximum of 300 files; the change list is truncated.</div> : null}
              <div className="stats">{[[d.summary.changed_files, 'Changed files'], [d.summary.affected_modules, 'Dependent modules'], [d.summary.routes, 'Routes'], [d.summary.relevant_tests, 'Relevant tests'], [d.summary.frontend_touched, 'Frontend files'], [d.summary.removed, 'Removed']].map(([n, l]) => <div className="stat" key={l}><b>{n ?? 0}</b><span>{l}</span></div>)}</div></section>
            <div className="toolbar filterbar" role="group" aria-label="Filter impact links"><span className="small muted">Show links that are</span>
              <select aria-label="Minimum link confidence" value={min} onChange={(e) => setMin(e.target.value)}><option value="">All links</option><option value="inferred">Verified + inferred</option><option value="verified_static">Verified only</option></select>
              <span className="small muted"><ResolutionBadge r="verified_static" /> proven · <ResolutionBadge r="inferred" /> heuristic · <ResolutionBadge r="unresolved" /> unknown</span></div>
            <Table title="Changed files" cols={['File', 'Status', 'Kind', 'Lines']} empty="No files changed in this range." rows={d.changed.map((c) => <tr key={c.path}><td><File path={c.path} on={c.in_graph && !c.removed} />{c.previous_path ? <div className="small muted">renamed from {c.previous_path}</div> : null}{c.note ? <div className="small muted">{c.note}</div> : null}</td><td><Badge kind={c.removed ? 'bad' : 'neutral'}>{c.status}</Badge></td><td>{c.kind}</td><td className="mono small">+{c.additions ?? 0} −{c.deletions ?? 0}</td></tr>)} />
            <Table title="Affected modules" cols={['Module', 'Hops', 'Via', 'Link']} empty={min ? 'No dependent modules at this confidence.' : 'No other module imports the changed code.'} rows={atLeast(d.affected, min).map((x) => <tr key={x.path}><td><File path={x.path} /></td><td>{x.distance}</td><td><File path={x.via} /></td><td><ResolutionBadge r={x.resolution} /></td></tr>)} />
            <Table title="Affected routes" cols={['Route', 'Handler', 'Why', 'Link']} empty="No FastAPI route handlers are in changed or dependent files." rows={atLeast(d.routes, min).map((r, i) => <tr key={i}><td className="mono">{r.method || '?'} {r.path || '(unknown path)'}{r.path_status && r.path_status !== 'constant' ? <div><Badge kind="warn">path {r.path_status}</Badge></div> : null}</td><td><File path={r.file} line={r.line} /></td><td className="small">{r.reason}</td><td><ResolutionBadge r={r.resolution} /></td></tr>)} />
            <Table title="Potentially relevant tests" cols={['Test file', 'Why', 'Link']} empty="No statically linked tests were found. That does not mean the change is untested." rows={atLeast(d.tests, min).map((t) => <tr key={t.path}><td><File path={t.path} /></td><td className="small">{t.reason}</td><td><ResolutionBadge r={t.resolution} /></td></tr>)} />
            {d.frontend.length ? <Table title="Frontend" cols={['File', 'Why', 'Link']} empty="No frontend links at this confidence." rows={atLeast(d.frontend, min).map((x) => <tr key={x.path}><td><File path={x.path} /></td><td className="small">{x.reason}{(x.evidence || []).length ? <div className="chips">{x.evidence.map((ev, i) => <button key={i} className="chip" type="button" onClick={() => open(ev)}>{sourceLabel(ev)}</button>)}</div> : null}</td><td><ResolutionBadge r={x.resolution} /></td></tr>)} /> : null}
            {d.graph?.nodes.length ? <section className="stack"><h3>Change neighbourhood</h3><Graph graph={d.graph} /></section> : null}
            <section className="card flat"><h3>Limitations</h3><ul className="small muted">{(d.limitations || []).map((l) => <li key={l}>{l}</li>)}</ul></section></>}
        </div>
      </div>
    </div>
  );
}
