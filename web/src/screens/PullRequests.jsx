import { useEffect, useState } from 'react';
import { get, post, ApiError } from '@legacy/api.js';
import { go } from '../router.js';
import { Badge, Card, ErrorBox, Skeleton, Spinner, useAsync } from '../components/ui.jsx';

const LEVEL = {
  review_closely: { kind: 'bad', icon: '!', label: 'Review closely' },
  review_normally: { kind: 'warn', icon: '?', label: 'Worth a careful read' },
  quick_look: { kind: 'ok', icon: '✓', label: 'Looks routine' },
};
const RISK_TO_LEVEL = { high: 'review_closely', medium: 'review_normally', low: 'quick_look' };
const GROUPS = [['Check first', ['high', 'critical'], 'These commonly break other code.'], ['Worth a look', ['medium'], 'Probably fine, but a reviewer should confirm.'], ['Minor', ['low'], 'Small observations.']];
const CHANGE = { added: 'new', modified: 'changed', deleted: 'deleted' };
const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;

function Steps({ d }) {
  const st = (s) => (s === 'READY' ? 'done' : s === 'FAILED' ? 'bad' : 'active');
  return (
    <Card className="stack">
      <h2>Reading this pull request</h2>
      <p className="small muted">Raven studies the code before the change and after it, then compares the two. This takes about a minute for a small project.</p>
      <ol className="pr-steps">
        <li className={st(d.base.state)}><b>1</b><span>Reading the code before the change <em className="mono">{d.base_sha.slice(0, 7)}</em></span></li>
        <li className={st(d.head.state)}><b>2</b><span>Reading the code after the change <em className="mono">{d.head_sha.slice(0, 7)}</em></span></li>
        <li className={d.base.state === 'READY' && d.head.state === 'READY' ? 'active' : ''}><b>3</b><span>Comparing them and writing the review</span></li>
      </ol>
      <Spinner label="Working… this page updates by itself." />
    </Card>
  );
}

function Finding({ f, d }) {
  const link = (e) => { const aid = e.commit_sha === d.head_sha ? d.head.analysis_id : d.base.analysis_id; return `/a/${aid}/files`; };
  return (
    <li className="finding">
      <div className="row"><strong>{f.title}</strong><Badge kind={f.resolution === 'verified_static' ? 'ok' : 'warn'} title={f.resolution === 'verified_static' ? 'Proven by reading the code' : 'A best guess from names and patterns, not proven'}>{f.resolution === 'verified_static' ? 'proven from the code' : 'best guess'}</Badge></div>
      {f.why ? <p className="small"><b>Why it matters:</b> {f.why}</p> : null}
      {f.detail ? <p className="small muted">{f.detail}</p> : null}
      <div className="row">{f.evidence.map((e, j) => <button key={j} className="linklike mono small" type="button" onClick={() => go(link(e), { path: e.path, line: e.start_line })}>{e.path}:{e.start_line}{e.commit_sha === d.head_sha ? '' : ' (before)'}</button>)}</div>
    </li>
  );
}

function Review({ id }) {
  const q = useAsync(() => get(`/api/v1/pr-reviews/${id}`), [id]);
  const d = q.data; const [showLow, setShowLow] = useState(false);
  useEffect(() => { if (d?.status !== 'PENDING') return undefined; const t = setTimeout(q.reload, 4000); return () => clearTimeout(t); }, [d, q.reload]);
  if (q.loading && !d) return <Skeleton h={240} />;
  if (q.error) return <ErrorBox error={q.error} retry={q.reload} />;
  if (d.status === 'FAILED') return <div className="banner bad" role="alert">Raven could not read one of the two versions of this pull request, so there is no review. Open your analyses to see why, or try again.</div>;
  if (d.status === 'PENDING') return <Steps d={d} />;
  const r = d.review; const v = r.verdict || { level: RISK_TO_LEVEL[r.risk] || 'quick_look', reasons: [], summary: '' }; const L = LEVEL[v.level];
  const impact = r.predicted_impact;
  return (
    <div className="stack-lg">
      <Card className={'verdict ' + L.kind}>
        <div className="verdict-top">
          <span className="verdict-icon" aria-hidden="true">{L.icon}</span>
          <div className="stack"><div className="eyebrow">Review priority</div><h2>{L.label}</h2>{v.summary ? <p>{v.summary}</p> : null}</div>
          <a className="btn sm" href={d.url} target="_blank" rel="noopener noreferrer">Open on GitHub ↗</a>
        </div>
        {v.reasons.length ? <div className="stack"><h3>Why</h3><ul>{v.reasons.map((x) => <li key={x.kind}>{x.text}</li>)}</ul></div> : null}
        <p className="small muted verdict-note"><b>How to use this:</b> Raven reads the structure of the code (routes, imports, tests, what depends on what). It does not run the code or judge the logic, so another reviewer or an AI assistant may see things Raven cannot, and Raven may flag things a human would accept. Treat it as a map of where to look first, not a pass or fail.</p>
      </Card>

      <Card className="stack">
        <h2>What this pull request does</h2>
        <p><b>{d.repository}#{d.number}</b> — {d.title}</p>
        <p>{r.what_it_does || `${r.summary.files_added} added, ${r.summary.files_modified} changed, ${r.summary.files_deleted} deleted.`}</p>
        {(r.areas_changed || []).length ? (
          <div className="pr-areas">{r.areas_changed.map((a) => (
            <details key={a.area} className={'pr-area area-' + a.area}><summary><b>{a.label}</b><span>{[a.added && `${a.added} new`, a.modified && `${a.modified} changed`, a.deleted && `${a.deleted} deleted`].filter(Boolean).join(' · ')}</span></summary>
              <p className="small muted">{a.blurb}</p>
              <ul className="list-reset small">{a.files.map((f) => <li key={f.path}><span className={'chg chg-' + f.change}>{CHANGE[f.change]}</span> <span className="mono">{f.path}</span></li>)}</ul></details>))}</div>) : null}
      </Card>

      <Card className="stack">
        <h2>Things to check</h2>
        {!r.findings.length ? <p><Badge kind="ok">nothing found</Badge> Raven found no structural problems between these two versions.</p> : GROUPS.map(([title, sevs, hint]) => {
          const fs = r.findings.filter((f) => sevs.includes(f.severity)); if (!fs.length) return null; const low = title === 'Minor';
          return (<section key={title} className="stack"><div className="row spread"><h3>{title} <span className="muted">({fs.length})</span></h3>{low ? <button className="btn sm" type="button" onClick={() => setShowLow(!showLow)}>{showLow ? 'Hide' : 'Show'}</button> : <span className="small muted">{hint}</span>}</div>
            {!low || showLow ? <ul className="list-reset stack">{fs.map((f, i) => <Finding key={i} f={f} d={d} />)}</ul> : null}</section>);
        })}
      </Card>

      <Card className="stack">
        <h2>What else this could affect</h2>
        <p className="small muted">Code that was not changed but depends on something that was.</p>
        <div className="stat-grid compact">
          <div className="stat"><div className="stat-v">{impact.affected_modules.length}</div><div className="stat-l">files that depend on changed code</div></div>
          <div className="stat"><div className="stat-v">{impact.routes.length}</div><div className="stat-l">endpoints involved</div></div>
          <div className="stat"><div className="stat-v">{impact.tests.length}</div><div className="stat-l">tests worth re-running</div></div>
        </div>
        {impact.tests.length ? <details><summary className="small">Tests worth re-running</summary><ul className="small mono list-reset">{impact.tests.slice(0, 20).map((t) => <li key={t.path}>{t.path}</li>)}</ul></details> : null}
      </Card>

      <Card className="stack">
        <div className="row spread"><h2>Share it</h2><a className="btn sm" href={`/api/v1/pr-reviews/${id}/markdown`} target="_blank" rel="noopener noreferrer">Copy as review comments</a></div>
        <p className="small muted">Raven never posts to GitHub. Open the comments, copy them, and paste into your review.</p>
        <details><summary className="small">What Raven cannot see</summary><ul className="small muted">{r.limitations.map((l, i) => <li key={i}>{l}</li>)}</ul></details>
      </Card>
    </div>
  );
}

export default function PullRequests({ id }) {
  const [url, setUrl] = useState(''); const [busy, setBusy] = useState(false); const [err, setErr] = useState(null);
  const list = useAsync(() => get('/api/v1/pr-reviews'), [id]);
  const submit = async (e) => { e.preventDefault(); setBusy(true); setErr(null); try { const r = await post('/api/v1/pr-reviews', { url: url.trim() }); go(`/pr/${r.id}`); } catch (x) { setErr(x instanceof ApiError ? x : new ApiError(0, null)); } setBusy(false); };
  return (
    <div className="page stack-lg">
      <div><div className="eyebrow">Pull requests</div><h1>Understand a pull request</h1>
        <p className="muted">Paste the link of a pull request on a public GitHub repository. Raven tells you what it changes, which parts of the project it touches, and where a reviewer should look first.</p></div>
      <form className="row" onSubmit={submit}><input type="url" required placeholder="https://github.com/owner/repo/pull/123" aria-label="Pull request URL" value={url} onChange={(e) => setUrl(e.target.value)} style={{ flex: '1 1 320px' }} /><button className="btn primary" disabled={busy}>{busy ? 'Starting…' : 'Review this pull request'}</button></form>
      {err ? <ErrorBox error={err} /> : null}
      {id ? <Review key={id} id={id} /> : (<>
        <ol className="how-cards">
          <li><b>1</b><h3>Paste the link</h3><p className="small muted">Any pull request from the same repository on public GitHub.</p></li>
          <li><b>2</b><h3>Raven compares before and after</h3><p className="small muted">It reads both versions of the code and finds what changed and what depends on it.</p></li>
          <li><b>3</b><h3>You get a plain summary</h3><p className="small muted">A review priority, the parts of the project affected, and a short list of things to check.</p></li>
        </ol>
        <Card className="stack"><h3>Your reviews</h3>{list.loading ? <Skeleton h={80} /> : list.error ? <ErrorBox error={list.error} retry={list.reload} /> : !list.data.items.length ? <p className="empty small">No reviews yet. Paste a pull request link above to start.</p> : (
          <ul className="list-reset stack">{list.data.items.map((r) => { const lv = LEVEL[(r.verdict_level) || RISK_TO_LEVEL[r.risk]]; return <li key={r.id} className="row spread"><button className="linklike" type="button" onClick={() => go(`/pr/${r.id}`)}>{r.repository}#{r.number} — {r.title}</button>
            <Badge kind={r.status === 'READY' ? (lv?.kind || 'ok') : r.status === 'FAILED' ? 'bad' : 'neutral'}>{r.status === 'READY' ? (lv?.label || 'ready') : r.status === 'FAILED' ? 'could not read' : 'reading…'}</Badge></li>; })}</ul>)}</Card></>)}
    </div>
  );
}
