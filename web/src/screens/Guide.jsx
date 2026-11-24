import { useEffect, useRef, useState } from 'react';
import { get, post, ApiError } from '@legacy/api.js';
import { fmtDate, shortSha } from '@legacy/util.js';
import { renderMarkdown } from '@legacy/markdown.js';
import { renderAllIn } from '@legacy/mermaid.js';
import { go } from '../router.js';
import { Badge, ErrorBox, Skeleton, Spinner, useAsync } from '../components/ui.jsx';

export default function Guide({ a }) {
  const id = a.analysis_id; const q = useAsync(() => get(`/api/v1/analyses/${id}/docs`), [id]); const d = q.data; const doc = d?.document;
  const body = useRef(null); const [toc, setToc] = useState([]); const [msg, setMsg] = useState(null);
  const pending = d && (d.regenerating || (!doc && a.status !== 'FAILED') || doc?.status === 'PENDING');
  useEffect(() => { if (!pending) return undefined; const t = setTimeout(q.reload, 3000); return () => clearTimeout(t); }, [pending, q.reload, d]);
  useEffect(() => {
    const host = body.current; if (!host || !doc?.markdown) return;
    const node = renderMarkdown(doc.markdown, { repo: a.repository.full_name, sha: a.commit_sha, openSource: (path, line, end) => go(`/a/${id}/files`, { path, line: line ? (end && end !== line ? `${line}-${end}` : line) : '' }) });
    const hs = [...node.querySelectorAll('h2')]; hs.forEach((h, i) => { h.id = 'sec-' + i; });
    setToc(hs.map((h) => ({ id: h.id, text: h.textContent.replace(/^\d+\.\s*/, '') })));
    host.replaceChildren(node); renderAllIn(node);
  }, [doc, a, id]);
  const regenerate = async () => { try { await post(`/api/v1/analyses/${id}/docs/generate`); q.reload(); } catch (e) { setMsg(e instanceof ApiError ? e.message : 'Failed'); } };
  if (q.loading && !d) return <Skeleton h={300} />;
  if (q.error) return <ErrorBox error={q.error} retry={q.reload} />;
  return (
    <div className="stack-lg">
      <div className="row spread"><div><div className="eyebrow">Onboarding guide</div><h2>Everything a new developer should read first</h2>
        {doc ? <div className="row small muted"><Badge kind={doc.status === 'READY' ? 'ok' : 'warn'}>{doc.status === 'READY' ? 'complete' : 'partial'}</Badge><Badge kind={doc.ai_status === 'ok' ? 'ok' : 'neutral'}>AI: {doc.ai_status}</Badge>v{doc.version} · commit {shortSha(doc.commit_sha)} · {fmtDate(doc.updated_at)}</div> : null}</div>
        <div className="row">{doc ? <a className="btn" href={`/api/v1/analyses/${id}/docs/download`} download>Download .md</a> : null}{a.status === 'READY' ? <button className="btn" type="button" disabled={d.regenerating} onClick={regenerate}>{d.regenerating ? 'Regenerating…' : 'Regenerate'}</button> : null}</div></div>
      {msg ? <div className="banner bad">{msg}</div> : null}
      {!doc ? <div className="banner">{pending ? <Spinner label="The onboarding guide is being generated…" /> : 'No guide exists for this analysis.'}</div> : null}
      {doc?.status === 'PARTIAL' ? <div className="banner warn"><div><strong>Partial guide. </strong>{(doc.gaps || []).join(' · ') || 'Some content is unavailable.'}</div></div> : null}
      {doc?.ai_status === 'unavailable' ? <div className="banner">AI-written explanations are not included. Everything below is derived directly from static analysis.</div> : null}
      {d?.regenerating ? <div className="banner"><Spinner label="A new version is being generated; showing the previous one." /></div> : null}
      {doc?.markdown ? <div className="docs"><nav className="toc" aria-label="On this page"><h3>On this page</h3>{toc.map((t) => <a key={t.id} href={`#${t.id}`} onClick={(e) => { e.preventDefault(); document.getElementById(t.id)?.scrollIntoView({ behavior: 'smooth' }); }}>{t.text}</a>)}</nav><div ref={body} /></div> : null}
    </div>
  );
}
