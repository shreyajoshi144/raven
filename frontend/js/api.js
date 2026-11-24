export class ApiError extends Error {
  constructor(status, body) {
    const e = (body && body.error) || {};
    super(e.message || `Request failed (${status})`);
    this.status = status; this.code = e.code || 'ERROR'; this.requestId = e.request_id || null; this.retryable = !!e.retryable;
  }
}
function csrf() {
  const m = document.cookie.split('; ').find((c) => c.startsWith('raven_csrf='));
  return m ? decodeURIComponent(m.split('=')[1]) : '';
}
export async function api(path, { method = 'GET', body, signal } = {}) {
  const headers = { Accept: 'application/json' };
  if (method !== 'GET') { headers['Content-Type'] = 'application/json'; headers['X-CSRF-Token'] = csrf(); }
  let res;
  try {
    res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), credentials: 'same-origin', signal });
  } catch (err) {
    if (err.name === 'AbortError') throw err;
    throw new ApiError(0, { error: { code: 'NETWORK', message: 'Could not reach the Raven server. Check your connection and try again.', retryable: true } });
  }
  if (res.status === 204) return null;
  const ctype = res.headers.get('content-type') || '';
  const data = ctype.includes('json') ? await res.json().catch(() => null) : await res.text();
  if (!res.ok) {
    const err = new ApiError(res.status, typeof data === 'object' ? data : null);
    if (res.status === 401 && !path.includes('/auth/')) window.dispatchEvent(new CustomEvent('raven:unauthenticated'));
    throw err;
  }
  return data;
}
export const get = (p, o) => api(p, o);
export const post = (p, body) => api(p, { method: 'POST', body: body ?? {} });
export const del = (p) => api(p, { method: 'DELETE' });
