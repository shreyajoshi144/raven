import { useState } from 'react';
import { api, get, post } from '@legacy/api.js';
import { go } from '../router.js';
import { Badge, Card, Eyebrow, ErrorBox, Skeleton, Empty, useAsync } from '../components/ui.jsx';

const TABS = [['overview', 'Overview'], ['monitoring', 'Monitoring'], ['users', 'Users'], ['analyses', 'Analyses'], ['failures', 'Failed jobs'], ['spend', 'LLM spend'], ['audit', 'Audit log']];
const usd = (v) => (v == null ? '—' : `$${v.toFixed(v < 1 ? 4 : 2)}`);
const num = (v) => (v ?? 0).toLocaleString();
const when = (iso) => new Date(iso).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
const stateKind = (s) => (s === 'READY' ? 'ok' : s === 'FAILED' ? 'bad' : s === 'CANCELLED' ? 'neutral' : 'info');
const Load = ({ q, children }) => (q.loading ? <Skeleton /> : q.error ? <ErrorBox error={q.error} retry={q.reload} /> : children(q.data));
const Stat = ({ label, value, sub, kind }) => <Card className={'stat ' + (kind || '')}><div className="stat-l">{label}</div><div className="stat-v">{value}</div>{sub ? <div className="stat-s">{sub}</div> : null}</Card>;

function Overview() {
  const o = useAsync(() => get('/api/v1/admin/overview'), []);
  return <Load q={o}>{(d) => {
    const a = d.analyses_24h, l = d.llm_24h;
    return (<div className="stack-lg">
      <div className="stat-grid">
        <Stat label="Users" value={num(d.users.total)} sub={`${d.users.new_24h} new today · ${d.users.disabled} disabled`} />
        <Stat label="Analyses (24h)" value={num(Object.values(a).reduce((x, y) => x + y, 0))} sub={`${a.READY || 0} ready · ${a.FAILED || 0} failed`} />
        <Stat label="Failed jobs (all time)" value={num(d.failed_total)} kind={d.failed_total ? 'warn' : ''} />
        <Stat label="Questions (24h)" value={num(l.questions)} sub={`${num(l.retrieval_only_answers)} answered without the model`} />
        <Stat label="Tokens (24h)" value={num(l.input_tokens + l.output_tokens)} sub={`${num(l.input_tokens)} in · ${num(l.output_tokens)} out`} />
        <Stat label="Spend (24h / 30d)" value={`${usd(l.spend_usd)} / ${usd(d.llm_30d.spend_usd)}`} sub={d.pricing_configured ? 'from configured list prices' : 'set LLM_PRICE_INPUT/OUTPUT_PER_MTOK to price tokens'} />
        <Stat label="Answer cache hit rate (24h)" value={d.cache.answers_24h.hit_rate == null ? '—' : `${Math.round(d.cache.answers_24h.hit_rate * 100)}%`} sub={`${d.cache.answers_24h.served_from_cache} of ${d.cache.answers_24h.ai_answers} AI answers · ${d.cache.answers_all_time.entries} cached`} />
        <Stat label="Saved by cache (all time)" value={`${num(d.cache.answers_all_time.tokens_saved)} tokens`} sub={`${usd(d.cache.answers_all_time.spend_saved_usd)} · ${d.cache.answers_all_time.hits} model calls avoided · ${d.cache.question_embeddings.reused} embeddings reused`} />
        <Stat label="Avg AI latency (24h)" value={l.avg_latency_ms ? `${(l.avg_latency_ms / 1000).toFixed(1)} s` : '—'} />
      </div></div>);
  }}</Load>;
}

const Spark = ({ data, color = 'var(--accent)', label, fmt = (v) => v }) => {
  const W = 300, H = 64, max = Math.max(1, ...data.map((d) => d ?? 0)), step = W / Math.max(1, data.length - 1);
  const pts = data.map((d, i) => [i * step, H - 4 - ((d ?? 0) / max) * (H - 10)]);
  const line = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`).join(' ');
  return (<svg className="spark" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${label}, peak ${fmt(max)}`} preserveAspectRatio="none">
    <path d={`${line} L${W} ${H} L0 ${H}Z`} fill={color} opacity=".12" /><path d={line} fill="none" stroke={color} strokeWidth="2" vectorEffect="non-scaling-stroke" /></svg>);
};
const Chart = ({ title, value, sub, ...p }) => <Card className="stack chart"><div className="stat-l">{title}</div><div className="stat-v">{value}</div><Spark {...p} label={title} />{sub ? <div className="stat-s">{sub}</div> : null}</Card>;
const dot = (ok) => <Badge kind={ok ? 'ok' : 'bad'}>{ok ? 'healthy' : 'down'}</Badge>;
const ms = (v) => (v == null ? '—' : v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${Math.round(v)} ms`);

function Monitoring() {
  const q = useAsync(() => get('/api/v1/admin/monitoring'), []);
  return <Load q={q}>{(d) => { const h = d.http, j = d.jobs, w = d.queue, l = d.llm; return (<div className="stack-lg">
    <div className="row"><span>Database {dot(d.services.database)}</span><span>Orchestrator (n8n) {dot(d.services.orchestrator)}</span>
      <span>Queue {dot(w.oldest_pending_seconds < 300 && !w.expired_leases)}</span><button className="btn sm" type="button" onClick={q.reload}>Refresh</button></div>
    <div className="stat-grid">
      <Chart title="Requests per minute" value={num(h.requests)} sub={`last ${h.window_minutes} min · ${h.scope}`} data={h.series.map((x) => x.n)} />
      <Chart title="Server errors (5xx)" value={`${(h.error_rate * 100).toFixed(2)}%`} sub={`${h.errors_5xx} errors · ${h.errors_4xx} client errors`} data={h.series.map((x) => x.e5)} color="var(--bad)" />
      <Chart title="Latency p95" value={ms(h.p95_ms)} sub={`p50 ${ms(h.p50_ms)} · p99 ${ms(h.p99_ms)}`} data={h.series.map((x) => x.p95_ms)} color="var(--warn)" fmt={ms} />
      <Chart title="Analyses per day (14 d)" value={`${j.success_rate == null ? '—' : Math.round(j.success_rate * 100) + '%'} ok`} sub={`${j.in_flight} in flight · p95 duration ${j.p95_seconds ?? '—'} s`} data={j.days.map((x) => x.created)} color="var(--ok)" />
    </div>
    <div className="stat-grid">
      <Stat label="Queue" value={Object.entries(w.by_status).map(([k, v]) => `${v} ${k}`).join(' · ') || 'empty'} sub={`oldest pending ${w.oldest_pending_seconds}s · ${w.expired_leases} expired leases`} kind={w.expired_leases ? 'warn' : ''} />
      <Stat label="AI answers (24h)" value={num(l.answers_24h)} sub={`${l.ai} model · ${l.retrieval_only} retrieval-only · ${l.failed} failed`} kind={l.fallback_rate > 0.5 ? 'warn' : ''} />
      <Stat label="AI latency p50 / p95" value={`${ms(l.latency_p50_ms)} / ${ms(l.latency_p95_ms)}`} sub={l.fallback_rate == null ? 'no answers yet' : `${Math.round(l.fallback_rate * 100)}% fell back to retrieval only`} />
    </div>
    <Card className="stack"><h2>Slowest routes</h2>{h.slowest_routes.length ? <table className="tbl"><thead><tr><th>Route</th><th>Requests</th><th>Avg</th><th>Max</th><th>5xx</th></tr></thead><tbody>{h.slowest_routes.map((r) => <tr key={r.route}><td className="mono small">{r.route}</td><td className="mono">{r.n}</td><td className="mono">{ms(r.avg_ms)}</td><td className="mono">{ms(r.max_ms)}</td><td className="mono">{r.errors_5xx}</td></tr>)}</tbody></table> : <p className="muted">No traffic recorded since this process started.</p>}</Card>
    <p className="small muted">HTTP figures come from this API process and reset on restart; jobs, queue and AI figures are read from the database. Prometheus: <span className="mono">GET /internal/v1/metrics</span> with the service secret.</p></div>); }}</Load>; }

function Users() {
  const [q, setQ] = useState(''); const [term, setTerm] = useState(''); const [err, setErr] = useState(null); const [edit, setEdit] = useState(null);
  const u = useAsync(() => get(`/api/v1/admin/users?q=${encodeURIComponent(term)}`), [term]);
  const act = async (fn) => { setErr(null); try { await fn(); u.reload(); } catch (e) { setErr(e); } };
  const disable = (x) => { const reason = window.prompt(`Disable ${x.email}? They are signed out everywhere. Reason (optional):`, ''); if (reason !== null) act(() => post(`/api/v1/admin/users/${x.id}/disable`, { reason })); };
  const saveQuota = (x) => act(async () => { const n = (v) => (v === '' || v == null ? null : Math.max(0, parseInt(v, 10) || 0)); await api(`/api/v1/admin/users/${x.id}/quotas`, { method: 'PUT', body: { quota_analyses_day: n(edit.a), quota_questions_day: n(edit.q), quota_tokens_day: n(edit.t) } }); setEdit(null); });
  return (<div className="stack">
    <form className="row" onSubmit={(e) => { e.preventDefault(); setTerm(q); }}><input type="search" placeholder="Search by email…" aria-label="Search users" value={q} maxLength={100} onChange={(e) => setQ(e.target.value)} style={{ maxWidth: 320 }} /><button className="btn sm" type="submit">Search</button></form>
    {err ? <ErrorBox error={err} /> : null}
    <Load q={u}>{(d) => (!d.users.length ? <Empty title="No users match" /> : (
      <div className="tablewrap card"><table className="tbl"><thead><tr><th>User</th><th>Status</th><th>Analyses today</th><th>Questions today</th><th>Tokens today</th><th>Spend today</th><th /></tr></thead><tbody>
        {d.users.map((x) => (<tr key={x.id}>
          <td><div>{x.email}</div><div className="small muted">joined {when(x.created_at)} · {x.analyses_total} analyses</div></td>
          <td>{x.disabled ? <Badge kind="bad" title={x.disabled_reason || ''}>disabled</Badge> : <Badge kind="ok">active</Badge>} {x.role === 'admin' ? <Badge kind="info">admin</Badge> : null}</td>
          <td className="mono">{x.today.analyses} / {x.limits.analyses}</td><td className="mono">{x.today.questions} / {x.limits.questions}</td><td className="mono">{num(x.today.tokens)} / {num(x.limits.tokens)}</td><td className="mono">{usd(x.today.spend_usd)}</td>
          <td>{edit?.id === x.id ? (<div className="row"><input aria-label="Analyses per day" placeholder="analyses" value={edit.a} onChange={(e) => setEdit({ ...edit, a: e.target.value })} size={6} /><input aria-label="Questions per day" placeholder="questions" value={edit.q} onChange={(e) => setEdit({ ...edit, q: e.target.value })} size={6} /><input aria-label="Tokens per day" placeholder="tokens" value={edit.t} onChange={(e) => setEdit({ ...edit, t: e.target.value })} size={8} /><button className="btn sm primary" type="button" onClick={() => saveQuota(x)}>Save</button><button className="btn sm" type="button" onClick={() => setEdit(null)}>Cancel</button></div>)
            : (<div className="row"><button className="btn sm" type="button" onClick={() => setEdit({ id: x.id, a: x.overrides.quota_analyses_day ?? '', q: x.overrides.quota_questions_day ?? '', t: x.overrides.quota_tokens_day ?? '' })}>Quotas</button>
              {x.disabled ? <button className="btn sm" type="button" onClick={() => act(() => post(`/api/v1/admin/users/${x.id}/enable`))}>Enable</button> : x.role !== 'admin' ? <button className="btn sm danger" type="button" onClick={() => disable(x)}>Disable</button> : null}</div>)}</td>
        </tr>))}</tbody></table></div>))}</Load>
    <p className="small muted">Blank quota fields use the platform defaults. Limits reset at 00:00 UTC.</p></div>);
}

const JobTable = ({ rows, cols }) => (!rows.length ? <Empty title="Nothing here" /> : (
  <div className="tablewrap card"><table className="tbl"><thead><tr><th>Repository</th><th>Owner</th><th>State</th>{cols ? <th>Error</th> : null}<th>When</th></tr></thead><tbody>
    {rows.map((j) => (<tr key={j.id}><td><a href={`#/a/${j.id}`} onClick={(e) => { e.preventDefault(); go(`/a/${j.id}`); }}>{j.repository}</a><div className="small muted mono">{j.commit_sha}</div></td><td>{j.owner}</td>
      <td><Badge kind={stateKind(j.state)}>{j.state.toLowerCase()}</Badge></td>{cols ? <td><div className="mono small">{j.error_code}</div><div className="small muted">{j.failed_state ? `failed in ${j.failed_state.toLowerCase()} · ` : ''}{j.retryable ? 'retryable' : 'not retryable'}</div></td> : null}<td className="small">{when(j.created_at)}</td></tr>))}</tbody></table></div>));

function Analyses() { const [s, setS] = useState(''); const q = useAsync(() => get(`/api/v1/admin/analyses?state=${s}`), [s]);
  return <div className="stack"><select aria-label="Filter by state" value={s} onChange={(e) => setS(e.target.value)} style={{ maxWidth: 220 }}><option value="">All states</option>{['QUEUED', 'READY', 'FAILED', 'CANCELLED', 'RETRYING'].map((x) => <option key={x} value={x}>{x.toLowerCase()}</option>)}</select><Load q={q}>{(d) => <JobTable rows={d.analyses} />}</Load></div>; }

function Failures() { const q = useAsync(() => get('/api/v1/admin/failures'), []);
  return <Load q={q}>{(d) => (<div className="stack"><div className="row">{Object.entries(d.by_code).map(([k, v]) => <Badge key={k} kind="bad">{k} · {v}</Badge>)}</div><JobTable rows={d.failures} cols /></div>)}</Load>; }

function Spend() { const q = useAsync(() => get('/api/v1/admin/spend?days=14'), []);
  return <Load q={q}>{(d) => { const max = Math.max(1, ...d.days.map((x) => x.input_tokens + x.output_tokens)); return (<div className="stack-lg">
    <Card className="stack"><h2>Tokens per day</h2>{d.days.length ? <div className="bars" role="img" aria-label="Tokens per day, last 14 days">{d.days.map((x) => <div key={x.day} className="bar-col" title={`${x.day}: ${num(x.input_tokens + x.output_tokens)} tokens · ${usd(x.spend_usd)}`}><i style={{ height: `${Math.max(3, ((x.input_tokens + x.output_tokens) / max) * 100)}%` }} /><span>{x.day.slice(5)}</span></div>)}</div> : <p className="muted">No AI usage yet.</p>}</Card>
    <Card className="stack"><h2>Top users (14 days)</h2>{d.top_users.length ? <table className="tbl"><thead><tr><th>User</th><th>Questions</th><th>Tokens</th><th>Spend</th></tr></thead><tbody>{d.top_users.map((x) => <tr key={x.email}><td>{x.email}</td><td className="mono">{x.questions}</td><td className="mono">{num(x.input_tokens + x.output_tokens)}</td><td className="mono">{usd(x.spend_usd)}</td></tr>)}</tbody></table> : <p className="muted">No AI usage yet.</p>}</Card></div>); }}</Load>; }

function Audit() { const q = useAsync(() => get('/api/v1/admin/audit'), []);
  return <Load q={q}>{(d) => (!d.events.length ? <Empty title="No admin actions yet" /> : <div className="tablewrap card"><table className="tbl"><thead><tr><th>When</th><th>Admin</th><th>Action</th><th>Target</th><th>Detail</th></tr></thead><tbody>{d.events.map((e) => <tr key={e.id}><td className="small">{when(e.at)}</td><td>{e.admin}</td><td className="mono">{e.action}</td><td>{e.target}</td><td className="small mono">{Object.entries(e.detail || {}).filter(([, v]) => v != null && v !== '').map(([k, v]) => `${k}=${v}`).join(' ')}</td></tr>)}</tbody></table></div>)}</Load>; }

export default function Admin({ tab = 'overview' }) {
  const View = { overview: Overview, monitoring: Monitoring, users: Users, analyses: Analyses, failures: Failures, spend: Spend, audit: Audit }[tab] || Overview;
  return (<div className="page stack-lg">
    <div><Eyebrow>Administration</Eyebrow><h1>Control room</h1></div>
    <nav className="tabs" aria-label="Admin sections">{TABS.map(([k, l]) => <a key={k} href={`#/admin/${k}`} aria-current={tab === k ? 'page' : undefined}>{l}</a>)}</nav>
    <View />
  </div>);
}
