import { useCallback, useEffect, useState } from 'react';
import { get, post, del, ApiError } from '@legacy/api.js';
import { isActive, shortSha, fmtDuration, fmtDate, PIPELINE } from '@legacy/util.js';
import { go } from '../router.js';
import { StatusBadge, Badge, ErrorBox, Skeleton, Spinner } from '../components/ui.jsx';
import Overview from './Overview.jsx';
import MapView from './MapView.jsx';
import FileGraph from './FileGraph.jsx';
import Files from './Files.jsx';
import Guide from './Guide.jsx';
import Health from './Health.jsx';
import Impact from './Impact.jsx';
import Architecture from './Architecture.jsx';
import Ask from './Ask.jsx';

const TABS = [['overview', '01', 'Overview'], ['map', '02', 'Map'], ['files', '03', 'Files'], ['guide', '04', 'Guide'], ['health', '05', 'Health'], ['impact', '06', 'Impact'], ['architecture', '07', 'Architecture'], ['ask', '08', 'Ask']];
const SCREENS = { map: MapView, graph: FileGraph, files: Files, guide: Guide, health: Health, impact: Impact, architecture: Architecture, ask: Ask };
const STEP = { QUEUED: 'Queued', FETCHING: 'Fetch', PARSING: 'Parse', BUILDING_GRAPH: 'Graph', GENERATING_DOCS: 'Guide', READY: 'Ready' };

function Pipeline({ a }) {
  const idx = PIPELINE.indexOf(a.status);
  return (
    <ol className="pipeline" aria-label="Analysis progress">
      {PIPELINE.map((s, i) => { const done = a.status === 'READY' || i < idx; const active = i === idx && a.status !== 'READY';
        return <li key={s} className={done ? 'done' : active ? 'active' : ''} aria-current={active ? 'step' : undefined}><i />{STEP[s]}</li>; })}
    </ol>
  );
}

export default function Workspace({ id, tab, query }) {
  const [a, setA] = useState(null); const [err, setErr] = useState(null);
  const load = useCallback(async () => { try { setA(await get(`/api/v1/analyses/${id}`)); setErr(null); } catch (e) { setErr(e); } }, [id]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (!a || !isActive(a.status)) return undefined; const t = setTimeout(load, 2500); return () => clearTimeout(t); }, [a, load]);
  const act = (fn, msg) => async () => { try { await fn(); load(); } catch (e) { setErr(e); } };
  if (err && !a) return <div className="page"><ErrorBox error={err} retry={load} /></div>;
  if (!a) return <div className="page"><Skeleton h={220} /></div>;
  const g = a.summary.graph; const Screen = SCREENS[tab === 'atlas' ? 'map' : tab]; const ready = a.graph_complete;
  return (
    <>
      <div className="ws-head">
        <div className="inner">
          <div className="crumbs"><a href="#/">Analyses</a> / {a.repository.full_name}</div>
          <div className="row spread">
            <div><h1>{a.repository.full_name}</h1></div>
            <div className="row">
              {isActive(a.status) ? <button className="btn sm" type="button" onClick={act(() => post(`/api/v1/analyses/${id}/cancel`))}>Cancel</button> : null}
              {a.retry_eligible ? <button className="btn sm primary" type="button" onClick={act(() => post(`/api/v1/analyses/${id}/retry`))}>Retry</button> : null}
              <button className="btn sm danger" type="button" onClick={async () => { if (confirm('Delete this analysis and all of its stored data? This cannot be undone.')) { try { await del(`/api/v1/analyses/${id}`); go('/'); } catch (e) { setErr(e); } } }}>Delete</button>
            </div>
          </div>
          <div className="ticker">
            <StatusBadge status={a.status} />
            <span className="mono">⎇ {a.default_branch} @ <a href={`${a.repository.url}/commit/${a.commit_sha}`} target="_blank" rel="noopener noreferrer">{shortSha(a.commit_sha)}</a></span>
            {g ? <span className="mono muted">{a.summary.inventory?.python_analyzed ?? 0} py · {g.route_count ?? 0} routes · {g.edge_count ?? 0} edges</span> : null}
            {a.summary.partial ? <Badge kind="warn">partial analysis</Badge> : null}
          </div>
          {isActive(a.status) ? <div aria-live="polite"><Pipeline a={a} /><p className="small muted">{a.stage ? `${a.stage}… ` : ''}Elapsed {fmtDuration(a.elapsed_seconds)}.{a.status === 'RETRYING' ? ` Temporary error; retry ${a.retry_after ? 'around ' + fmtDate(a.retry_after) : 'scheduled'}.` : ''}</p></div> : null}
          {a.status === 'FAILED' ? <div className="banner bad" role="alert"><div><strong>Analysis failed. </strong>{a.error?.message} {a.retry_eligible ? 'Usually temporary; you can retry.' : ''}{a.error ? <span className="small"> (code {a.error.code})</span> : null}</div></div> : null}
          {a.status === 'CANCELLED' ? <div className="banner">This analysis was cancelled.</div> : null}
          {a.summary.partial ? <div className="banner warn"><div><strong>Partial analysis: </strong>{a.summary.partial_reasons.join('; ')}</div></div> : null}
          <nav className="tabs" aria-label="Analysis sections">
            {TABS.map(([k, n, label]) => { const on = k === 'overview' || ready;
              return <a key={k} href={on ? `#/a/${id}${k === 'overview' ? '' : '/' + k}` : undefined} aria-current={k === tab ? 'page' : undefined} aria-disabled={on ? undefined : 'true'} title={on ? undefined : 'Available once the code graph is built'}><b>{n}</b>{label}</a>; })}
          </nav>
        </div>
      </div>
      <div className="page">
        {tab === 'overview' || !Screen ? <Overview a={a} /> : !ready ? <div className="card empty"><Spinner label="Waiting for the code graph…" /></div> : <Screen key={`${id}:${tab}`} a={a} query={query} />}
      </div>
    </>
  );
}
