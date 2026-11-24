import { useCallback, useEffect, useRef, useState } from 'react';
import { get } from '@legacy/api.js';
import { createFlow } from '@legacy/flow.js';
import { ROLE_LABEL } from '@legacy/icons.js';
import { go } from '../router.js';
import { Badge, ResolutionBadge, ErrorBox } from '../components/ui.jsx';

const ROLES = ['frontend', 'entry', 'router', 'service', 'model', 'worker', 'config', 'module', 'external'];
const lines = (s, e) => (s ? (e && e !== s ? `${s}-${e}` : String(s)) : '');

export default function FileGraph({ a, query }) {
  const id = a.analysis_id;
  const hostRef = useRef(null); const flowRef = useRef(null); const pending = useRef(query.select || null);
  const [mode, setMode] = useState(query.mode === 'trace' ? 'trace' : 'files');
  const [focus, setFocus] = useState(query.focus || ''); const [tests, setTests] = useState(false); const [ext, setExt] = useState(true);
  const [hidden, setHidden] = useState([]); const [data, setData] = useState(null); const [routes, setRoutes] = useState(null); const [traceId, setTraceId] = useState(query.node || '');
  const [sel, setSel] = useState(null); const [q, setQ] = useState(''); const [err, setErr] = useState(null);
  const wrapRef = useRef(null); const [zoom, setZoom] = useState(100); const [layersOpen, setLayersOpen] = useState(false);
  const onView = (t) => { const w = wrapRef.current; if (!w) return; w.style.setProperty('--gs', `${24 * t.k}px`); w.style.setProperty('--gx', `${t.x}px`); w.style.setProperty('--gy', `${t.y}px`); setZoom(Math.round(t.k * 100)); };
  const openSource = (n) => n?.path && go(`/a/${id}/files`, { path: n.path, line: lines(n.start_line, n.end_line) });

  useEffect(() => {  // one engine instance for the lifetime of the screen
    const f = createFlow(hostRef.current, { id: 'graph', onSelect: (n) => setSel(n ? { n } : null), onEdge: (e, s, t) => setSel({ e, s, t }), onOpen: openSource, transitive: true, onView, initialView: 'overview', tile: true });
    flowRef.current = f; return () => { f.destroy(); flowRef.current = null; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const loadFiles = useCallback(async () => {
    setErr(null);
    try { const p = new URLSearchParams({ limit: focus ? '120' : '70', include_tests: tests, include_external: ext }); if (focus) p.set('focus', focus); setData(await get(`/api/v1/analyses/${id}/graph/flow?${p}`)); } catch (e) { setErr(e); }
  }, [id, focus, tests, ext]);
  const loadRoutes = useCallback(async () => {
    try { const r = (await get(`/api/v1/analyses/${id}/graph?types=route&limit=500`)).nodes; setRoutes(r); setTraceId((t) => (r.some((x) => x.id === t) ? t : r[0]?.id || '')); } catch (e) { setErr(e); }
  }, [id]);
  useEffect(() => { if (mode === 'files') loadFiles(); else if (!routes) loadRoutes(); }, [mode, loadFiles, loadRoutes, routes]);
  useEffect(() => {
    if (mode !== 'trace' || !traceId) return;
    get(`/api/v1/analyses/${id}/graph/trace?node_id=${traceId}&depth=3`).then(setData, setErr);
  }, [mode, traceId, id]);

  const view = data && { ...data, nodes: data.nodes.filter((n) => mode === 'trace' || !hidden.includes(n.role)) };
  if (view) { const ids = new Set(view.nodes.map((n) => n.id)); view.edges = data.edges.filter((e) => ids.has(e.source) && ids.has(e.target)); }
  useEffect(() => {
    const f = flowRef.current; if (!f || !view) return;
    f.setData(view); f.transitive = true; setSel(null);
    if (mode === 'trace' && data.root) f.select(data.root, false);
    if (pending.current) { const hit = view.nodes.find((n) => n.path === pending.current); if (hit) f.select(hit.id, true); pending.current = null; }
  }, [data, hidden, mode]); // eslint-disable-line react-hooks/exhaustive-deps

  const f = flowRef.current;
  const rel = (n, dir) => (f ? f.edges.filter((e) => (dir === 'out' ? e.source : e.target) === n.id).map((e) => ({ e, o: f.nodes.get(dir === 'out' ? e.target : e.source) })).filter((x) => x.o) : []);
  const present = new Set((data?.nodes || []).map((n) => n.role));
  const traceFile = (n) => { setMode('trace'); const r = (routes || []).find((x) => x.path === n.path); if (r) setTraceId(r.id); };

  return (
    <div className={'stage' + (zoom >= 90 && (view?.edges.length || 0) <= 60 ? ' labels' : '')} ref={wrapRef}>
      <div className="flow-host" ref={hostRef} />
      <div className="float-bar" role="toolbar" aria-label="Canvas tools">
        <div className="seg" role="group" aria-label="View mode">{[['files', 'File flow'], ['trace', 'Route trace']].map(([k, l]) => <button key={k} type="button" aria-pressed={mode === k} onClick={() => setMode(k)}>{l}</button>)}</div>
        <input className="grow" type="search" placeholder="Find a file or symbol…" aria-label="Find a file or symbol" maxLength={100} value={q}
          onChange={(e) => { setQ(e.target.value); const first = f?.search(e.target.value); if (first && e.target.value.trim()) f.centerOn?.(first, 0.9); }}
          onKeyDown={(e) => { if (e.key === 'Enter') { const first = f?.search(q); if (first) f.select(first, true); } }} />
        {mode === 'files' ? <button className="btn sm" type="button" aria-expanded={layersOpen} onClick={() => setLayersOpen((o) => !o)}>Layers{hidden.length || focus || tests || !ext ? ' •' : ''}</button>
          : <select aria-label="Route to trace" value={traceId} onChange={(e) => setTraceId(e.target.value)}>{(routes || []).map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}</select>}
      </div>
      {mode === 'files' && layersOpen ? <div className="float-panel layers" role="group" aria-label="Layers">
        <div className="row spread"><h3>Layers</h3><button className="btn sm icon" type="button" aria-label="Close layers" onClick={() => setLayersOpen(false)}>×</button></div>
        <label className="small" htmlFor="focus-folder">Folder</label>
        <select id="focus-folder" aria-label="Focus on a folder" value={focus} onChange={(e) => setFocus(e.target.value)}><option value="">All folders</option>{(data?.folders || []).map((x) => <option key={x} value={x}>{x || '/'}</option>)}</select>
        <div className="row"><label className="toggle"><input type="checkbox" checked={tests} onChange={(e) => setTests(e.target.checked)} />Tests</label>
          <label className="toggle"><input type="checkbox" checked={ext} onChange={(e) => setExt(e.target.checked)} />Packages</label></div>
        <div className="role-chips" role="group" aria-label="Show or hide file roles">
          {ROLES.filter((r) => present.has(r) || hidden.includes(r)).map((r) => <button key={r} type="button" className="rchip" aria-pressed={!hidden.includes(r)} onClick={() => setHidden((h) => (h.includes(r) ? h.filter((x) => x !== r) : [...h, r]))}><i style={{ background: `var(--r-${r})` }} />{ROLE_LABEL[r] || r}</button>)}</div>
      </div> : null}
      <span className="count-pill small mono" aria-live="polite">{data ? (mode === 'files' ? `${view.nodes.filter((n) => n.kind === 'file').length} of ${data.total_files} files · ${view.edges.length} connections` : `${view.nodes.length} nodes · ${view.edges.length} connections`) : ''}</span>
      {err ? <div className="float-err"><ErrorBox error={err} retry={mode === 'files' ? loadFiles : loadRoutes} /></div> : null}
      <div className="zoom-dock" role="group" aria-label="Zoom controls">
        <button type="button" aria-label="Zoom out" title="Zoom out" onClick={() => f?.zoom(0.8)}>−</button>
        <output aria-live="off" title="Current zoom">{zoom}%</output>
        <button type="button" aria-label="Zoom in" title="Zoom in" onClick={() => f?.zoom(1.25)}>+</button>
        <i aria-hidden="true" />
        <button type="button" className="txt" title="Fit whole graph on screen" onClick={() => f?.fit()}>Fit</button>
        <button type="button" className="txt" title="Reset to 100%" onClick={() => f?.reset()}>Reset</button>
      </div>
      <div className="legend" aria-label="Legend"><span><i className="line" />verified</span><span><i className="line dash" />inferred</span><span><i className="line dot" />unresolved</span></div>
      <aside className={'float-panel ' + (sel ? 'detail' : 'hint')} aria-live="polite">
        {sel ? <button className="btn sm icon close" type="button" aria-label="Close details" onClick={() => f?.select(null)}>×</button> : null}
          {!sel ? <div className="stack"><div className="eyebrow">{mode === 'files' ? 'File flow' : 'Route trace'}</div><h2>{mode === 'files' ? 'Follow the connections' : 'Follow a request'}</h2>
            <p className="small muted">{mode === 'files' ? 'Each card is a file; arrows point to what it depends on. Select a card to light up its upstream and downstream; click a line to see the code that creates it.' : 'Pick a route to see its handler, dependencies, models and the functions it calls.'}</p>
            <p className="small muted"><b>Scroll</b> to move around · <b>⌘/Ctrl + scroll</b> or pinch to zoom · drag to pan</p>
            <p className="small muted"><span className="kbd">Tab</span> focus · <span className="kbd">←→</span> follow links · <span className="kbd">Esc</span> clear</p></div>
          : sel.e ? <div className="stack"><div className="row"><Badge kind="info">connection</Badge><ResolutionBadge r={sel.e.resolution} /></div>
              <h2><span className="mono">{sel.s.label}</span> → <span className="mono">{sel.t.label}</span></h2>
              <div className="row">{Object.entries(sel.e.kinds || { [sel.e.relation]: 1 }).map(([k, v]) => <Badge key={k}>{k.replaceAll('_', ' ')}{v > 1 ? ` ×${v}` : ''}</Badge>)}</div>
              {(sel.e.labels || (sel.e.label ? [sel.e.label] : [])).length ? <ul className="small">{(sel.e.labels || [sel.e.label]).map((l) => <li key={l}>{l}</li>)}</ul> : null}
              <h3>Evidence in the source</h3>
              {sel.e.evidence?.length ? <ul className="list-reset stack small">{sel.e.evidence.map((x, i) => <li key={i}><button className="linklike mono" type="button" onClick={() => go(`/a/${id}/files`, { path: x.path, line: lines(x.start_line, x.end_line) })}>{x.path}:{x.start_line}</button></li>)}</ul> : <p className="small muted">No line evidence recorded.</p>}
              <button className="btn sm" type="button" onClick={() => f.select(f.sel)}>Back to node</button></div>
          : <div className="stack"><div className="row"><Badge kind="info">{sel.n.kind === 'file' || sel.n.kind === 'external' ? ROLE_LABEL[sel.n.role] || sel.n.kind : sel.n.kind}</Badge>{sel.n.unresolved ? <Badge kind="bad">unresolved</Badge> : null}</div>
              <h2 className="mono">{sel.n.label}</h2>{sel.n.path ? <div className="small muted mono">{sel.n.path}{sel.n.start_line ? `:${sel.n.start_line}` : ''}</div> : null}
              {sel.n.counts && Object.keys(sel.n.counts).length ? <div className="row">{Object.entries(sel.n.counts).map(([k, v]) => <Badge key={k}>{v} {k}</Badge>)}</div> : null}
              {sel.n.summary ? <p className="small">{sel.n.summary}</p> : null}
              {sel.n.facts?.length ? <ul className="small">{sel.n.facts.map((x, i) => <li key={i}>{x.replaceAll('`', '')}</li>)}</ul> : null}
              <div className="row">{sel.n.path ? <button className="btn sm primary" type="button" onClick={() => openSource(sel.n)}>Open source</button> : null}
                {sel.n.kind === 'file' && sel.n.counts?.routes ? <button className="btn sm" type="button" onClick={() => traceFile(sel.n)}>Trace routes</button> : null}
                {sel.n.kind === 'file' ? <button className="btn sm" type="button" onClick={() => { setMode('files'); setFocus(sel.n.dir); }}>Focus folder</button> : null}</div>
              {[['Depends on', 'out'], ['Used by', 'in']].map(([t, d]) => { const l = rel(sel.n, d); return <div key={d}><h3>{t} ({l.length})</h3><div className="rel">{l.map(({ e, o }, i) => <button key={i} type="button" onClick={() => f.select(o.id, true)}><span className="mono">{o.label}</span><span className="tag"><ResolutionBadge r={e.resolution} /></span></button>)}</div></div>; })}</div>}
      </aside>
    </div>
  );
}
