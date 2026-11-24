import { get, post, ApiError } from './api.js';
import { el, mount, toast } from './util.js';
import { icon } from './icons.js';
import { openPalette } from './palette.js';
import { loginView, registerView } from './view_auth.js';
import { dashboardView } from './view_dashboard.js';
import { analysisView } from './view_analysis.js';
import { statusView } from './view_status.js';

export const session = { user: null, analysis: null };
let cleanup = null;
const main = document.getElementById('main');

function parseHash() {
  const raw = location.hash.replace(/^#/, '') || '/';
  const [pathPart, qs = ''] = raw.split('?');
  return { parts: pathPart.split('/').filter(Boolean), query: Object.fromEntries(new URLSearchParams(qs)) };
}
export function navigate(path) { location.hash = '#' + path; }

function renderNav() {
  const nav = document.getElementById('topnav');
  mount(nav);
  const { parts } = parseHash();
  if (session.user) {
    nav.append(
      el('button', { class: 'search-trigger', type: 'button', 'aria-label': 'Open command palette', on: { click: palette } }, el('span', { class: 'row', style: '' }, icon('search'), ' Search or jump to…'), el('span', { class: 'kbd', text: navigator.platform.includes('Mac') ? '⌘K' : 'Ctrl K' })),
      el('a', { class: 'navlink', href: '#/', 'aria-current': parts.length === 0 || parts[0] === 'a' ? 'page' : null }, 'Analyses'),
      el('a', { class: 'navlink', href: '#/status', 'aria-current': parts[0] === 'status' ? 'page' : null }, 'System'),
      el('span', { class: 'avatar', title: session.user.email, 'aria-label': 'Signed in as ' + session.user.email }, session.user.email[0]),
      el('button', { class: 'btn sm', type: 'button', on: { click: logout } }, 'Sign out'));
  } else {
    nav.append(el('a', { class: 'navlink', href: '#/login' }, 'Sign in'), el('a', { class: 'btn sm primary', href: '#/register' }, 'Create account'));
  }
}
async function logout() { try { await post('/api/v1/auth/logout'); } catch { /* ignore */ } session.user = null; session.analysis = null; renderNav(); navigate('/login'); }

function palette() {
  if (!session.user) return;
  const a = session.analysis;
  const commands = [
    { label: 'All analyses', icon: 'overview', run: () => navigate('/') }, { label: 'System status', icon: 'bolt', run: () => navigate('/status') },
    ...(a ? [['Overview', ''], ['Code graph', '/graph'], ['Files', '/files'], ['Documentation', '/docs'], ['Engineering readiness', '/health'], ['Change impact', '/impact'], ['Ask the codebase', '/chat']].map(([l, p]) => ({ label: `${a.repository.full_name} · ${l}`, icon: { '': 'overview', '/graph': 'graph', '/files': 'files', '/docs': 'docs', '/health': 'test', '/impact': 'branch', '/chat': 'chat' }[p], run: () => navigate(`/a/${a.analysis_id}${p}`) })) : []),
    { label: 'Sign out', icon: 'x', run: logout }];
  openPalette({ commands, search: a && a.graph_complete ? async (q) => {
    const d = await get(`/api/v1/analyses/${a.analysis_id}/files?q=${encodeURIComponent(q)}&kind=python&limit=8`);
    return d.items.map((f) => ({ label: f.path, icon: 'files', hint: 'file', run: () => navigate(`/a/${a.analysis_id}/files?path=${encodeURIComponent(f.path)}`) }));
  } : null });
}
document.addEventListener('keydown', (e) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); palette(); } });

async function route() {
  if (cleanup) { try { cleanup(); } catch { /* ignore */ } cleanup = null; }
  const { parts, query } = parseHash();
  const authPage = parts[0] === 'login' || parts[0] === 'register';
  if (!session.user && !authPage) { navigate('/login'); return; }
  if (session.user && authPage) { navigate('/'); return; }
  if (parts[0] !== 'a') session.analysis = null;
  renderNav();
  mount(main, el('div', { class: 'page' }, el('div', { class: 'skeleton', style: '' }), ));
  let result;
  try {
    if (parts[0] === 'login') result = loginView(onAuthed);
    else if (parts[0] === 'register') result = registerView(onAuthed);
    else if (parts[0] === 'status') result = await statusView();
    else if (parts[0] === 'a' && parts[1]) result = await analysisView(parts[1], parts[2] || 'overview', query);
    else result = await dashboardView();
  } catch (e) { result = { node: el('div', { class: 'page' }, errorBox(e)) }; }
  mount(main, result.node);
  cleanup = result.cleanup || null;
  if (result.after) result.after();
  const h1 = main.querySelector('h1');
  if (h1) { h1.setAttribute('tabindex', '-1'); h1.focus({ preventScroll: true }); }
  document.title = (h1 ? h1.textContent + ' — ' : '') + 'Raven';
}

export function errorBox(e, retry) {
  const msg = e instanceof ApiError ? e.message : 'Something went wrong.';
  return el('div', { class: 'banner bad', role: 'alert' }, icon('alert'), el('div', {}, el('strong', { text: 'Error: ' }), msg, e && e.requestId ? el('span', { class: 'small', text: ` (request ${e.requestId})` }) : null,
    retry ? el('div', {}, el('button', { class: 'btn sm', type: 'button', on: { click: retry } }, 'Try again')) : null));
}
function onAuthed(user) { session.user = user; renderNav(); navigate('/'); }
window.addEventListener('hashchange', route);
window.addEventListener('raven:unauthenticated', () => { if (session.user) { session.user = null; toast('Your session has ended. Please sign in again.', 'bad'); navigate('/login'); } });
(async function boot() { try { session.user = (await get('/api/v1/me')).user; } catch { session.user = null; } renderNav(); route(); })();
