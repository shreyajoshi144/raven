import { useState } from 'react';
import { get, post, ApiError } from '@legacy/api.js';
import { fmtDate, shortSha, PIPELINE, isActive } from '@legacy/util.js';
import { go } from '../router.js';
import { Card, StatusBadge, ErrorBox, Skeleton, useAsync } from '../components/ui.jsx';

function MiniPipe({ status }) {
  const idx = PIPELINE.indexOf(status);
  return <div className="minipipe" aria-hidden="true">{PIPELINE.map((s, i) => <i key={s} className={status === 'READY' || i < idx ? 'done' : i === idx ? 'active' : status === 'FAILED' && i === Math.max(idx, 1) ? 'failed' : ''} />)}</div>;
}

export default function Dashboard() {
  const [url, setUrl] = useState(''); const [err, setErr] = useState(null); const [busy, setBusy] = useState(false);
  const list = useAsync(() => get('/api/v1/analyses?limit=50'), []);
  const submit = async (e) => {
    e.preventDefault(); setBusy(true); setErr(null);
    try { const a = await post('/api/v1/analyses', { url: url.trim() }); go(`/a/${a.analysis_id}`); } catch (x) { setErr(x instanceof ApiError ? x : new ApiError(0, null)); setBusy(false); }
  };
  const items = list.data?.items || [];
  return (
    <div className="page stack-lg">
      <section className="hero">
        <div className="eyebrow">Codebase intelligence · Python / FastAPI</div>
        <h1>Point it at a repo. <span>Get the map, with receipts.</span></h1>
        <p>An architecture map, engineering-readiness findings, change impact and cited Q&A, pinned to one commit and built by static analysis.</p>
        <form className="cmdbar" onSubmit={submit} noValidate>
          <span className="prompt" aria-hidden="true">$ raven analyze</span>
          <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://github.com/owner/repository" aria-label="Public GitHub repository URL" maxLength={300} required />
          <button className="btn primary" type="submit" disabled={busy}>Analyze</button>
        </form>
        {err ? <ErrorBox error={err} /> : null}
      </section>
      <section className="stack">
        <h2>Your analyses</h2>
        {list.loading ? <Skeleton h={140} /> : list.error ? <ErrorBox error={list.error} retry={list.reload} /> : !items.length ? <Card className="empty"><h3>Nothing analysed yet</h3><p className="small">Paste a public repository above to start.</p></Card> : (
          <div className="repo-grid">
            {items.map((a) => (
              <a key={a.analysis_id} className="repo-card" href={`#/a/${a.analysis_id}`}>
                <div className="row spread"><StatusBadge status={a.status} />{a.summary.partial ? <span className="small muted">partial</span> : null}</div>
                <div className="name">{a.repository.full_name}</div>
                <div className="meta mono">{shortSha(a.commit_sha)} · {fmtDate(a.created_at)}</div>
                <div className="meta">{a.summary.graph ? `${a.summary.graph.route_count ?? 0} routes · ${a.summary.graph.edge_count ?? 0} connections` : isActive(a.status) ? 'in progress…' : ''}</div>
                <MiniPipe status={a.status} />
              </a>
            ))}
          </div>)}
      </section>
    </div>
  );
}
