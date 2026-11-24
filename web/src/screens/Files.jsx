import { useEffect, useRef, useState } from 'react';
import { get } from '@legacy/api.js';
import { el } from '@legacy/util.js';
import { fmtBytes, shortSha } from '@legacy/util.js';
import { highlightLine } from '@legacy/highlight.js';
import { go } from '../router.js';
import { Badge, reasonText, ResolutionBadge, ErrorBox, Skeleton, useAsync } from '../components/ui.jsx';

const parseLine = (v) => { const m = /^(\d+)(?:-(\d+))?$/.exec(String(v || '')); return m ? [+m[1], +(m[2] || m[1])] : [0, 0]; };

function Code({ file, line }) {
  const ref = useRef(null);
  useEffect(() => {
    const host = ref.current; host.replaceChildren(); const [hs, he] = parseLine(line);
    if (file.content == null) { host.append(el('p', { class: 'empty', text: file.status === 'excluded' ? `Not stored: ${reasonText(file.excluded_reason)}.` : 'Source text is not stored for this file.' })); return; }
    const state = { inDoc: null }; const py = file.path.endsWith('.py'); const frag = document.createDocumentFragment();
    file.content.split('\n').forEach((t, i) => { const n = i + 1; frag.append(el('div', { class: 'ln' + (hs && n >= hs && n <= he ? ' hl' : ''), id: 'L' + n }, el('span', { text: String(n), 'aria-hidden': 'true' }), el('span', {}, py ? highlightLine(t, state) : t))); });
    host.append(frag); if (hs) setTimeout(() => document.getElementById('L' + hs)?.scrollIntoView({ block: 'center' }), 30);
  }, [file, line]);
  return <div className="code" ref={ref} role="region" aria-label={`Source of ${file.path}`} tabIndex={0} />;
}

function Viewer({ id, fileId, line }) {
  const q = useAsync(() => get(`/api/v1/analyses/${id}/files/${fileId}`), [id, fileId]);
  const f = q.data;
  if (q.loading) return <Skeleton h={300} />;
  if (q.error) return <ErrorBox error={q.error} retry={q.reload} />;
  const jump = (s, e) => { document.querySelectorAll('.ln.hl').forEach((n) => n.classList.remove('hl')); for (let n = s; n <= (e || s); n++) document.getElementById('L' + n)?.classList.add('hl'); document.getElementById('L' + s)?.scrollIntoView({ block: 'center' }); };
  const rel = (title, items) => (items.length ? <div><h3>{title}</h3><div className="rel">{items.slice(0, 40).map((r, i) => <button key={i} type="button" onClick={() => r.path && !r.unresolved && go(`/a/${id}/files`, { path: r.path })}><span className="mono">{r.name}</span><span className="tag"><ResolutionBadge r={r.resolution} /></span></button>)}</div></div> : null);
  return (
    <div className="stack-lg">
      <section className="card stack">
        <div className="row spread"><h2 className="mono">{f.path}</h2><div className="row">{f.symbols.some((s) => s.type === 'route') ? <button className="btn sm" type="button" onClick={() => go(`/a/${id}/atlas`, { mode: 'trace' })}>Trace routes</button> : null}<a className="btn sm" href={f.source_url} target="_blank" rel="noopener noreferrer">GitHub ↗</a></div></div>
        <p className="small muted">{f.line_count} lines · {fmtBytes(f.size_bytes)} · pinned to commit {shortSha(f.commit_sha)}</p>
        <div className="row">{f.redacted ? <Badge kind="warn">secret-like text redacted</Badge> : null}{f.contains_secret_like ? <Badge kind="warn">excluded from AI context</Badge> : null}{f.status === 'parse_error' ? <Badge kind="bad">could not be parsed</Badge> : null}</div>
        {f.parse_warning ? <p className="small">{f.parse_warning}</p> : null}
        {f.explanation ? <p>{f.explanation}</p> : null}
      </section>
      {f.symbols.length ? <section><h3>Symbols</h3><div className="chips">{f.symbols.slice(0, 60).map((s) => <button key={s.id} className="chip" type="button" title={s.type} onClick={() => jump(s.start_line, s.end_line)}>{s.type === 'worker' ? s.name : `${s.name}:${s.start_line}`}</button>)}</div></section> : null}
      <Code file={f} line={line} />
      {rel('Imports', f.relationships.imports)}{rel('Imported by', f.relationships.imported_by)}{rel('Tests', f.relationships.tested_by)}{rel('Configuration', f.relationships.configured_by)}
    </div>
  );
}

export default function Files({ a, query }) {
  const id = a.analysis_id; const [q, setQ] = useState(''); const [kind, setKind] = useState(query.kind === 'skipped' ? 'skipped' : 'python'); const [open, setOpen] = useState(null); const [line, setLine] = useState(query.line || '');
  const list = useAsync(() => { const p = new URLSearchParams({ limit: kind ? '300' : '500' }); if (q.trim()) p.set('q', q.trim()); if (kind === 'skipped') p.set('status', 'excluded,skipped_limit'); else if (kind) p.set('kind', kind); return get(`/api/v1/analyses/${id}/files?${p}`); }, [id, q, kind]);
  useEffect(() => {
    if (!query.path) return; let dead = false;
    get(`/api/v1/analyses/${id}/files?q=${encodeURIComponent(query.path)}&limit=50`).then((d) => { const hit = d.items.find((f) => f.path === query.path) || d.items[0]; if (hit && !dead) { setOpen(hit); setLine(query.line || ''); } });
    return () => { dead = true; };
  }, [id, query.path, query.line]);
  const d = list.data;
  return (
    <div className="stack-lg">
      <div><div className="eyebrow">Source</div><h2>Files at the pinned commit</h2><p className="small muted">Only Python and setup files are stored; secret-like values are redacted before storage.</p></div>
      <div className="files">
        <div className="tree">
          <div className="tree-head"><input type="search" placeholder="Filter files…" aria-label="Filter files by path" maxLength={100} value={q} onChange={(e) => setQ(e.target.value)} />
            <select aria-label="File kind" value={kind} onChange={(e) => setKind(e.target.value)}><option value="python">Python</option><option value="support">Setup & docs</option><option value="skipped">Skipped / excluded</option><option value="">All</option></select></div>
          <div className="tree-body">{list.loading ? <p className="small muted" style={{ padding: '.8rem' }}>Loading…</p> : list.error ? <ErrorBox error={list.error} retry={list.reload} /> : !d.items.length ? <p className="empty small">No files match.</p> : (
            <ul className="list-reset">{d.items.map((f) => { const i = f.path.lastIndexOf('/'); return <li key={f.id}><button type="button" aria-current={open?.id === f.id ? 'true' : undefined} onClick={() => { setOpen(f); setLine(''); }}><span className="dir">{i >= 0 ? f.path.slice(0, i + 1) : ''}</span>{f.path.slice(i + 1)}{f.status === 'parse_error' ? ' ⚠' : ''}{f.excluded_reason ? <span className="tag"> {reasonText(f.excluded_reason)}</span> : null}</button></li>; })}</ul>)}
            {d && d.total > d.items.length ? <p className="small muted" style={{ padding: '.6rem .8rem' }}>Showing {d.items.length} of {d.total}.</p> : null}</div>
        </div>
        {open ? <Viewer key={open.id + line} id={id} fileId={open.id} line={line} /> : <div className="card empty"><h3>Pick a file</h3><p className="small">See its source, relationships and what the analysis found.</p></div>}
      </div>
    </div>
  );
}
