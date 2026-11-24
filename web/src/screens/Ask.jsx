import { useEffect, useRef, useState } from 'react';
import { get, post, del, ApiError } from '@legacy/api.js';
import { go } from '../router.js';
import { Badge, ErrorBox, Meter } from '../components/ui.jsx';
import { answerParts, confidenceKind, CONFIDENCE_HELP } from '@legacy/insights.js';

const SUGGESTIONS = ['What are the main entry points of this application?', 'Which routes require authentication?', 'Where are the database models defined?', 'Which environment variables does the app read?'];
const loc = (c) => `${c.path}:${c.start_line}${c.end_line !== c.start_line ? '-' + c.end_line : ''}`;

function Message({ m, open }) {
  if (m.role === 'user') return <div className="msg user"><div className="bd">{m.content}</div></div>;
  if (m.status === 'failed') return <div className="msg bot"><div className="bubble"><div className="banner bad">{m.content || 'This question could not be answered.'}</div></div></div>;
  const p = answerParts(m);
  const WHY = { LLM_QUOTA_EXHAUSTED: 'The AI provider account is out of quota or credit (not retried).', LLM_RATE_LIMITED: 'The AI provider is rate-limiting requests; retried, then gave up.', LLM_AUTH_FAILED: 'The AI provider rejected the configured API key (not retried).', LLM_TIMEOUT: 'The AI provider timed out.', LLM_PROVIDER_UNAVAILABLE: 'The AI provider is temporarily unavailable.', LLM_BUDGET_EXCEEDED: 'This question exceeded the token/call budget.', LLM_NOT_CONFIGURED: 'No AI provider is configured.' };
  return (
    <div className="msg bot"><div className="bubble">
      <div className="row">{p.ai ? <Badge kind="info" title={`Generated from retrieved code; citations are validated against the analyzed files${m.model ? ` · model ${m.model}` : ''}${m.prompt_version ? ` · prompt ${m.prompt_version}` : ''}`}>AI answer</Badge> : <Badge kind="warn">retrieval only, no AI answer</Badge>}{m.cache_hit ? <Badge kind="ok" title="An identical question about this exact commit was answered before. No model call was made.">instant · cached</Badge> : null}
        {p.insufficient ? <Badge kind="warn">insufficient evidence</Badge> : <Badge kind="ok">evidence found</Badge>}
        {m.commit_sha ? <span className="tag mono" title={`Answer grounded in repository commit ${m.commit_sha}`}>commit {m.commit_sha.slice(0, 7)}</span> : null}
        {p.confidence ? <span className={`conf ${confidenceKind(p.confidence)}`} title={`${CONFIDENCE_HELP[p.confidence]} A rule over the evidence, not a probability.`}><Meter level={p.confidence} />{p.confidence} confidence</span> : null}</div>
      {!p.ai && m.error_code ? <div className="banner warn small" role="status"><strong>Showing source locations only. </strong>{WHY[m.error_code] || m.error_code}</div> : null}
      <div className="answer-part">
        {p.ai ? <div className="small muted part-label">{p.citations.length ? 'Supported by the cited source' : 'Answer (no supporting citation)'}</div> : null}
        <div className="bd">{p.supported}</div>
        {p.citations.length ? <div><div className="small muted">Sources</div>{p.citations.map((c, i) => <button key={i} className="cite" type="button" onClick={() => open(c)}><span className="n">{i + 1}</span><span><span className="mono">{loc(c)}</span>{c.excerpt ? <div className="excerpt">{c.excerpt}</div> : null}</span></button>)}</div> : null}
      </div>
      {p.inferred.length ? <div className="answer-part inferred" role="note"><div className="small part-label"><strong>Inferred, not shown directly by the cited code</strong></div><ul className="small">{p.inferred.map((x, i) => <li key={i}>{x}</li>)}</ul></div> : null}
      {p.limitations.length ? <ul className="small muted">{p.limitations.map((l, i) => <li key={i}>{l}</li>)}</ul> : null}
    </div></div>
  );
}

export default function Ask({ a }) {
  const id = a.analysis_id; const [items, setItems] = useState(null); const [text, setText] = useState(''); const [busy, setBusy] = useState(false); const [err, setErr] = useState(null); const [pending, setPending] = useState(null); const end = useRef(null);
  const history = async () => { try { setItems((await get(`/api/v1/analyses/${id}/chat?limit=100`)).items); } catch (e) { setErr(e); } };
  useEffect(() => { history(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { end.current?.scrollIntoView({ block: 'nearest' }); }, [items, pending]);
  const open = (c) => go(`/a/${id}/files`, { path: c.path, line: c.end_line !== c.start_line ? `${c.start_line}-${c.end_line}` : c.start_line });
  const send = async (e) => {
    e.preventDefault(); const t = text.trim(); if (!t || busy) return; setBusy(true); setErr(null); setPending(t);
    try { await post(`/api/v1/analyses/${id}/chat`, { message: t }); setText(''); } catch (x) { setErr(x); }
    finally { setPending(null); setBusy(false); await history(); }
  };
  const clear = async () => { if (!confirm('Clear this conversation?')) return; try { await del(`/api/v1/analyses/${id}/chat`); } catch (x) { setErr(x); } history(); };
  return (
    <div className="stack-lg">
      <div><div className="eyebrow">Ask</div><h2>Questions, answered with citations</h2></div>
      <div className="chat-shell">
        <div className="stack">
          <div className="chat" role="log" aria-live="polite" aria-label="Conversation">
            {items === null ? <div className="skeleton" style={{ height: 80 }} /> : !items.length && !pending ? <div className="card flat empty"><p className="small">Ask anything. Answers cite the exact files and lines they come from; if the evidence is not there, Raven says so.</p></div> : items.map((m) => <Message key={m.id} m={m} open={open} />)}
            {pending ? <><div className="msg user"><div className="bd">{pending}</div></div><div className="msg bot"><div className="bubble"><span className="typing" role="status" aria-label="Searching the code and drafting an answer"><i /><i /><i /></span></div></div></> : null}
            <div ref={end} />
          </div>
          {err ? <ErrorBox error={err instanceof ApiError ? err : new ApiError(0, null)} /> : null}
          <form className="composer" onSubmit={send} noValidate><label htmlFor="q" className="small">Ask a question</label>
            <textarea id="q" rows={2} maxLength={2000} value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) send(e); }} placeholder="Ask about this codebase, e.g. “What does get_current_user do?”" />
            <div className="row spread"><span className="small muted">{text.length} / 2000</span><div className="row"><button className="btn sm" type="button" onClick={clear}>Clear</button><button className="btn primary" type="submit" disabled={busy}>Ask →</button></div></div></form>
        </div>
        <aside className="stack"><div className="card flat"><h3>Try asking</h3><div className="suggest">{SUGGESTIONS.map((s) => <button key={s} type="button" onClick={() => setText(s)}>{s}</button>)}</div></div>
          <div className="card flat small muted">Answers are built only from retrieved code at the analyzed commit and must cite file and line ranges. Static analysis cannot show runtime behavior.</div></aside>
      </div>
    </div>
  );
}
