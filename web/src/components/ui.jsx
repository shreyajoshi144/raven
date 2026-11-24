import { ApiError } from '@legacy/api.js';
import { STATUS_META, isActive } from '@legacy/util.js';

export const Badge = ({ kind = 'neutral', title, children }) => <span className={`badge ${kind}`} title={title}>{children}</span>;
export const Spinner = ({ label = 'Loading…' }) => <span className="muted" role="status"><span className="spinner" aria-hidden="true" /> {label}</span>;
export const Skeleton = ({ h = 120 }) => <div className="skeleton" style={{ height: h }} />;

export function StatusBadge({ status }) {
  const [text, kind] = STATUS_META[status] || [status, 'neutral'];
  return <span className={`badge ${kind}${isActive(status) ? ' live' : ''}`}><span className="dot" />{text}</span>;
}
export const ResolutionBadge = ({ r }) => {
  const m = { verified_static: ['verified', 'ok', 'Directly supported by source syntax'], inferred: ['inferred', 'warn', 'Heuristic, not proven'], unresolved: ['unresolved', 'bad', 'A reference exists but its target could not be determined statically'] }[r] || [r, 'neutral', ''];
  return <Badge kind={m[1]} title={m[2]}>{m[0]}</Badge>;
};
export function ErrorBox({ error, retry }) {
  const msg = error instanceof ApiError ? error.message : 'Something went wrong.';
  return (
    <div className="banner bad" role="alert">
      <div><strong>Error: </strong>{msg}{error && error.requestId ? <span className="small"> (request {error.requestId})</span> : null}
        {retry ? <div><button className="btn sm" type="button" onClick={retry}>Try again</button></div> : null}</div>
    </div>
  );
}
export const Empty = ({ title, children }) => <div className="card empty"><h3>{title}</h3>{children ? <p className="small">{children}</p> : null}</div>;
export const Card = ({ className = '', children, ...p }) => <section className={`card ${className}`} {...p}>{children}</section>;
export const Eyebrow = ({ children }) => <div className="eyebrow">{children}</div>;
export const Meter = ({ level }) => {  // segmented 3-step confidence/strength meter
  const n = { high: 3, medium: 2, low: 1 }[level] || 0;
  return <span className="meter" aria-hidden="true">{[1, 2, 3].map((i) => <i key={i} className={i <= n ? 'on' : ''} />)}</span>;
};

import { useCallback, useEffect, useRef, useState } from 'react';
/** Loads data with loading/error state; `reload()` refetches. Ignores results from superseded loads. */
export function useAsync(fn, deps) {
  const [state, set] = useState({ loading: true, data: null, error: null });
  const seq = useRef(0);
  const run = useCallback(() => {
    const my = ++seq.current; set((s) => ({ ...s, loading: true, error: null }));
    fn().then((data) => { if (my === seq.current) set({ loading: false, data, error: null }); }, (error) => { if (my === seq.current) set({ loading: false, data: null, error }); });
  }, deps); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { run(); return () => { seq.current++; }; }, [run]);
  return { ...state, reload: run };
}

export const REASONS = {  // exact, human-readable reasons a file was not analysed
  too_large: 'larger than the per-file size limit', binary: 'binary or non-text content', generated: 'generated / vendored code',
  web_file_limit: 'frontend file-count limit reached', web_total_size_limit: 'frontend total-size limit reached',
  python_file_limit: 'Python file-count limit reached', total_size_limit: 'aggregate source-size limit reached',
  ignored_dir: 'ignored directory (node_modules, build output, caches)', not_source: 'not a source or setup file', secret_file: 'secret-bearing file kept out of storage',
};
export const reasonText = (k) => REASONS[k] || String(k || 'unknown').replaceAll('_', ' ');
