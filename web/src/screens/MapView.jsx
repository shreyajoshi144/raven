import { useEffect, useMemo, useState } from 'react';
import { get } from '@legacy/api.js';
import { go } from '../router.js';
import { Badge, ErrorBox, Skeleton, useAsync } from '../components/ui.jsx';

// Raven's map: three zoom levels instead of one tangled graph.  1) the architecture, 2) a part of it, 3) its files.
const W = 1180, CW = 250, CH = 152, GAP_X = 50, GAP_Y = 36, PAD = 24;
const ROLE = { frontend: 'page / component', entry: 'app entry point', router: 'endpoints', service: 'business logic', model: 'data model', worker: 'background job', config: 'settings', test: 'test', module: 'module' };
const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;
const lines = (l) => (l ? String(l) : '');

function useWide() {
  const [w, setW] = useState(() => (typeof matchMedia === 'undefined' ? true : matchMedia('(min-width: 980px)').matches));
  useEffect(() => { const m = matchMedia('(min-width: 980px)'); const f = () => setW(m.matches); m.addEventListener('change', f); return () => m.removeEventListener('change', f); }, []);
  return w;
}

function layout(areas) {
  const main = areas.filter((a) => !['tests', 'external', 'tools'].includes(a.id)), side = areas.filter((a) => ['tests', 'external', 'tools'].includes(a.id));
  const cols = {}; main.forEach((a) => { (cols[a.tier] ||= []).push(a); });
  const tiers = Object.keys(cols).map(Number).sort((x, y) => x - y); const pos = {};
  let rows = 0;
  tiers.forEach((t, c) => { cols[t].forEach((a, r) => { pos[a.id] = { x: PAD + c * (CW + GAP_X), y: PAD + r * (CH + GAP_Y) }; rows = Math.max(rows, r + 1); }); });
  const baseY = PAD + rows * (CH + GAP_Y) + 10;
  side.forEach((a, i) => { pos[a.id] = { x: PAD + i * (CW + GAP_X), y: baseY, small: true }; });
  const used = tiers.length || 1;
  return { pos, width: Math.max(W, PAD * 2 + used * (CW + GAP_X)), height: baseY + (side.length ? CH + PAD : 0) };
}

function Arch({ data, links, onPick }) {
  const { pos, width, height } = useMemo(() => layout(data.areas.map((a) => ({ ...a, tier: Number(a.tier) }))), [data.areas]);
  const [hover, setHover] = useState(null);
  const arrows = useMemo(() => Object.entries(links).map(([k, n]) => { const [s, t] = k.split('>'); return { s, t, n }; })
    .filter((l) => pos[l.s] && pos[l.t] && !pos[l.s].small && !pos[l.t].small), [links, pos]);
  const path = (s, t) => {
    const a = pos[s], b = pos[t]; const fwd = a.x < b.x, same = a.x === b.x;
    if (same) { const down = a.y < b.y; const x = a.x + CW, y1 = a.y + (down ? CH : 0), y2 = b.y + (down ? 0 : CH); return `M${x - 40} ${y1} C${x + 60} ${y1} ${x + 60} ${y2} ${x - 40} ${y2}`; }
    const x1 = fwd ? a.x + CW : a.x, x2 = fwd ? b.x : b.x + CW, y1 = a.y + CH / 2, y2 = b.y + CH / 2, dx = Math.max(40, Math.abs(x2 - x1) / 2);
    return `M${x1} ${y1} C${x1 + (fwd ? dx : -dx)} ${y1} ${x2 - (fwd ? dx : -dx)} ${y2} ${x2} ${y2}`;
  };
  const mid = (s, t) => { const a = pos[s], b = pos[t]; return { x: (a.x + b.x + CW) / 2, y: (a.y + b.y) / 2 + CH / 2 - 10 }; };
  const lit = (l) => !hover || l.s === hover || l.t === hover;
  const shown = (l) => pos[l.s].x !== pos[l.t].x || (hover && (l.s === hover || l.t === hover)); // links inside one column only appear on hover, to keep the first view calm
  return (
    <div className="arch" style={{ aspectRatio: `${width} / ${height}` }}>
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" aria-hidden="true">
        <defs><marker id="m-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0 1 L9 5 L0 9z" fill="context-stroke" /></marker></defs>
        {arrows.filter(shown).map((l) => (<g key={l.s + l.t} className={'arch-edge' + (lit(l) ? '' : ' dim') + (hover && lit(l) ? ' hot' : '')}>
          <path d={path(l.s, l.t)} strokeWidth={Math.min(5, 1.4 + Math.log10(l.n + 1) * 1.6)} markerEnd="url(#m-arrow)" />
          {hover && lit(l) ? <g transform={`translate(${mid(l.s, l.t).x} ${mid(l.s, l.t).y})`}><rect x="-34" y="-12" width="68" height="22" rx="11" /><text textAnchor="middle" y="4">{l.n} links</text></g> : null}
        </g>))}
      </svg>
      {data.areas.map((a) => { const p = pos[a.id]; return (
        <button key={a.id} type="button" className={'arch-card area-' + a.id} style={{ left: `${(p.x / width) * 100}%`, top: `${(p.y / height) * 100}%`, width: `${(CW / width) * 100}%`, height: `${(CH / height) * 100}%` }}
          onMouseEnter={() => setHover(a.id)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(a.id)} onBlur={() => setHover(null)} onClick={() => onPick(a.id)}>
          <span className="ac-title">{a.label}</span>
          <span className="ac-blurb">{a.blurb}</span>
          <span className="ac-meta">{a.id === 'external' ? plural(a.files, 'package') : plural(a.files, 'file')}{a.routes ? ` · ${plural(a.routes, 'route')}` : ''}{a.models ? ` · ${plural(a.models, 'model')}` : ''}</span>
          <span className="ac-go" aria-hidden="true">Look inside →</span>
        </button>); })}
    </div>
  );
}

function Crumbs({ nav, data, set }) {
  const area = data.areas.find((a) => a.id === nav.area); const group = data.groups.find((g) => g.id === nav.group);
  return (
    <nav className="map-crumbs" aria-label="Map location">
      <button type="button" onClick={() => set({})} aria-current={!nav.area ? 'page' : undefined}>Whole project</button>
      {area ? <><i>›</i><button type="button" onClick={() => set({ area: nav.area })} aria-current={!group ? 'page' : undefined}>{area.label}</button></> : null}
      {group ? <><i>›</i><button type="button" aria-current="page">{group.label}</button></> : null}
    </nav>
  );
}

export default function MapView({ a }) {
  const id = a.analysis_id;
  const q = useAsync(() => get(`/api/v1/analyses/${id}/map`), [id]);
  const [nav, setNavRaw] = useState({}); const wide = useWide();
  const setNav = (n) => { setNavRaw(n); window.scrollTo?.({ top: 0 }); };
  const d = q.data;
  const idx = useMemo(() => {
    if (!d) return null;
    const files = new Map(d.files.map((f) => [f.id, f])); const out = new Map(), inn = new Map(), areaL = {}, groupL = {};
    d.links.forEach((l) => {
      const s = files.get(l.s), t = files.get(l.t); if (!s || !t) return; const n = Object.values(l.kinds).reduce((x, y) => x + y, 0);
      (out.get(s.id) || out.set(s.id, []).get(s.id)).push({ f: t, kinds: l.kinds, n }); (inn.get(t.id) || inn.set(t.id, []).get(t.id)).push({ f: s, kinds: l.kinds, n });
      if (s.area !== t.area && s.area !== 'tests' && t.area !== 'tests') areaL[`${s.area}>${t.area}`] = (areaL[`${s.area}>${t.area}`] || 0) + 1;
      if (s.group !== t.group) groupL[`${s.group}>${t.group}`] = (groupL[`${s.group}>${t.group}`] || 0) + 1;
    });
    return { files, out, inn, areaL, groupL };
  }, [d]);
  if (q.loading) return <Skeleton h={420} />;
  if (q.error) return <ErrorBox error={q.error} retry={q.reload} />;
  const area = d.areas.find((x) => x.id === nav.area); const group = d.groups.find((g) => g.id === nav.group);
  const sel = nav.file ? idx.files.get(nav.file) : null;
  return (
    <div className="map stack">
      <div className="map-head">
        <div><div className="eyebrow">Raven map</div><h2>{!area ? 'The architecture of this project' : !group ? area.label : group.label}</h2>
          <p className="small muted">{!area ? 'Each block is a part of the project. Arrows show which parts depend on which. Click a block to look inside; nothing else to zoom or drag.'
            : !group ? area.blurb : `${plural(group.files, 'file')} in this group. Click a file to see what it connects to.`}</p></div>
        <a className="btn sm" href={`#/a/${id}/graph`} title="The detailed graph of every file, for experts">Detailed file graph</a>
      </div>
      <Crumbs nav={nav} data={d} set={setNav} />
      {!area ? (wide ? <Arch data={d} links={idx.areaL} onPick={(x) => setNav({ area: x })} /> : (
        <ul className="map-grid list-reset">{d.areas.map((x) => <li key={x.id}><button type="button" className={'arch-card static area-' + x.id} onClick={() => setNav({ area: x.id })}><span className="ac-title">{x.label}</span><span className="ac-blurb">{x.blurb}</span><span className="ac-meta">{plural(x.files, 'file')}</span></button></li>)}</ul>))
        : area.id === 'external' ? <Externals d={d} idx={idx} open={(fid) => { const f = idx.files.get(fid); if (f) setNav({ area: f.area, group: f.group, file: f.id }); }} />
        : !group ? <Groups d={d} area={area} idx={idx} pick={(g) => { const gg = d.groups.find((x) => x.id === g); const only = gg.files === 1 ? d.files.find((f) => f.group === g) : null; setNav({ area: area.id, group: g, file: only?.id }); }} />
        : <Files d={d} group={group} idx={idx} sel={sel} id={id} select={(fid) => setNav({ ...nav, file: fid })} jump={(f) => setNav({ area: f.area, group: f.group, file: f.id })} />}
      {!area ? <p className="small muted map-foot">{d.totals.files} files · {d.totals.routes} routes · {d.totals.links} connections between files. Counts come from static analysis of commit {a.commit_sha.slice(0, 7)}.</p> : null}
    </div>
  );
}

function Groups({ d, area, idx, pick }) {
  const gs = d.groups.filter((g) => g.area === area.id).sort((x, y) => y.files - x.files);
  const names = new Map(d.groups.map((g) => [g.id, g]));
  const conn = (g) => { const o = {}, i = {}; Object.entries(idx.groupL).forEach(([k, n]) => { const [s, t] = k.split('>'); if (s === g.id) o[t] = n; if (t === g.id) i[s] = n; }); return { o, i }; };
  const top = (m) => Object.entries(m).sort((x, y) => y[1] - x[1]).slice(0, 3).map(([k]) => names.get(k)?.label).filter(Boolean);
  return (
    <ul className="map-grid list-reset">{gs.map((g) => { const c = conn(g); const uses = top(c.o), usedBy = top(c.i); return (
      <li key={g.id}><button type="button" className={'group-card area-' + area.id} onClick={() => pick(g.id)}>
        <span className="ac-title">{g.label}</span>
        <span className="ac-meta">{plural(g.files, 'file')}{g.routes ? ` · ${plural(g.routes, 'route')}` : ''}{g.models ? ` · ${plural(g.models, 'model')}` : ''}</span>
        <span className="gc-files">{g.top.join(', ')}{g.files > g.top.length ? ` +${g.files - g.top.length} more` : ''}</span>
        {uses.length ? <span className="gc-rel"><b>Uses</b> {uses.join(', ')}</span> : null}{usedBy.length ? <span className="gc-rel"><b>Used by</b> {usedBy.join(', ')}</span> : null}
        <span className="ac-go" aria-hidden="true">See files →</span></button></li>); })}</ul>
  );
}

function Externals({ d, idx, open }) {
  return (
    <ul className="map-grid list-reset">{d.externals.map((e) => (
      <li key={e.name} className="group-card area-external static"><span className="ac-title mono">{e.name}</span><span className="ac-meta">{e.category ? `${e.category} · ` : ''}used by {plural(e.used_by, 'file')}</span>
        <span className="gc-files">{e.files.slice(0, 4).map((fid) => <button key={fid} type="button" className="linklike mono small" onClick={() => open(fid)}>{idx.files.get(fid)?.name}</button>)}</span></li>))}</ul>
  );
}

function Rel({ title, list, jump, empty }) {
  const rows = [...list].sort((x, y) => y.n - x.n);
  return (
    <div className="stack"><h3>{title} ({rows.length})</h3>
      {rows.length ? <ul className="list-reset rel-list">{rows.slice(0, 12).map(({ f, kinds }) => (
        <li key={f.id}><button type="button" onClick={() => jump(f)}><span className="mono">{f.name}</span><span className="muted small">{f.path.split('/').slice(0, -1).join('/')}</span></button>
          <span className="small muted">{Object.keys(kinds).map((k) => k.replaceAll('_', ' ')).join(', ')}</span></li>))}{rows.length > 12 ? <li className="small muted">+{rows.length - 12} more</li> : null}</ul> : <p className="small muted">{empty}</p>}</div>
  );
}

function Files({ d, group, idx, sel, id, select, jump }) {
  const fs = d.files.filter((f) => f.group === group.id).sort((x, y) => (idx.inn.get(y.id)?.length || 0) - (idx.inn.get(x.id)?.length || 0) || x.path.localeCompare(y.path));
  return (
    <div className={'map-files' + (sel ? ' has-sel' : '')}>
      <ul className="map-grid list-reset">{fs.map((f) => { const o = idx.out.get(f.id)?.length || 0, i = idx.inn.get(f.id)?.length || 0; return (
        <li key={f.id}><button type="button" className={'file-card area-' + f.area + (sel?.id === f.id ? ' on' : '')} aria-pressed={sel?.id === f.id} onClick={() => select(f.id)}>
          <span className="fc-name mono">{f.name}</span><span className="fc-role">{ROLE[f.role] || f.role}</span>
          <span className="ac-meta">{f.routes ? `${plural(f.routes, 'route')} · ` : ''}{f.models ? `${plural(f.models, 'model')} · ` : ''}{plural(f.functions, 'function')}</span>
          <span className="fc-links"><span title="Files this one depends on">uses {o}</span><span title="Files that depend on this one">used by {i}</span></span></button></li>); })}</ul>
      {sel ? (
        <aside className="map-detail card stack" aria-live="polite">
          <button className="btn sm icon close" type="button" aria-label="Close details" onClick={() => select(null)}>×</button>
          <div><Badge kind="info">{ROLE[sel.role] || sel.role}</Badge></div><h2 className="mono">{sel.name}</h2><div className="small muted mono">{sel.path}</div>
          {sel.route_names.length ? <div className="stack"><h3>Endpoints</h3><ul className="small mono list-reset">{sel.route_names.map((r) => <li key={r}>{r}</li>)}</ul></div> : null}
          {sel.tests ? <p className="small"><Badge kind="ok">covered</Badge> {plural(sel.tests, 'test file')} exercise this file.</p> : sel.role !== 'test' ? <p className="small muted">No test file is linked to this file.</p> : null}
          <div className="row"><button className="btn sm primary" type="button" onClick={() => go(`/a/${id}/files`, { path: sel.path, line: lines(sel.line) })}>Open the code</button></div>
          <Rel title="Depends on" list={idx.out.get(sel.id) || []} jump={jump} empty="Does not import other project files." />
          <Rel title="Used by" list={idx.inn.get(sel.id) || []} jump={jump} empty="No other project file uses this." />
        </aside>) : <p className="small muted map-hint">Click a file to see what it depends on and what depends on it.</p>}
    </div>
  );
}
