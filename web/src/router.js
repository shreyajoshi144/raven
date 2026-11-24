import { useEffect, useState } from 'react';

export function parseHash(hash) {
  const raw = hash.replace(/^#/, '') || '/';
  const [path, qs = ''] = raw.split('?');
  return { parts: path.split('/').filter(Boolean), query: Object.fromEntries(new URLSearchParams(qs)) };
}
export const go = (path, query) => { location.hash = '#' + path + (query && Object.keys(query).length ? '?' + new URLSearchParams(query) : ''); };
export function useRoute() {
  const [r, setR] = useState(() => parseHash(location.hash));
  useEffect(() => { const f = () => setR(parseHash(location.hash)); addEventListener('hashchange', f); return () => removeEventListener('hashchange', f); }, []);
  return r;
}
