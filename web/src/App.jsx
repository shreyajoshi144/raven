import { createContext, useContext, useEffect, useState } from 'react';
import { get, post } from '@legacy/api.js';
import { go, useRoute } from './router.js';
import { Login, Register, VerifyEmail, ForgotPassword, ResetPassword } from './screens/Auth.jsx';
import Dashboard from './screens/Dashboard.jsx';
import Workspace from './screens/Workspace.jsx';
import Security from './screens/Security.jsx';
import System from './screens/System.jsx';
import Admin from './screens/Admin.jsx';
import Landing from './screens/Landing.jsx';
import PullRequests from './screens/PullRequests.jsx';

const NEXT = 'raven:next';
const stash = (h) => { try { sessionStorage.setItem(NEXT, h); } catch { /* ignore */ } };
const takeNext = () => { try { const h = sessionStorage.getItem(NEXT); sessionStorage.removeItem(NEXT); return h && /^#\/a\//.test(h) ? h : null; } catch { return null; } };

const Session = createContext(null);
export const useSession = () => useContext(Session);
const PUBLIC = new Set(['login', 'register', 'verify-email', 'forgot-password', 'reset-password']);

function Shell({ user, setUser, route, children }) {
  const p0 = route.parts[0];
  const out = async () => { try { await post('/api/v1/auth/logout'); } catch { /* ignore */ } setUser(null); go('/login'); };
  return (
    <>
      <a className="skip" href="#main">Skip to content</a>
      <header className="topbar">
        <a className="brand" href="#/" aria-label="Raven home"><span className="mark" aria-hidden="true" />Raven</a>
        <nav aria-label="Primary">
          <a className="navlink" href="#/" aria-current={!p0 || p0 === 'a' ? 'page' : undefined}>Analyses</a>
          <a className="navlink" href="#/pr" aria-current={p0 === 'pr' ? 'page' : undefined}>Pull requests</a>
          <a className="navlink hide-sm" href="#/system" aria-current={p0 === 'system' ? 'page' : undefined}>System</a>
          {user.role === 'admin' ? <a className="navlink" href="#/admin" aria-current={p0 === 'admin' ? 'page' : undefined}>Admin</a> : null}
          <a className="navlink" href="#/security" aria-current={p0 === 'security' ? 'page' : undefined}>Security</a>
          <span className="avatar" title={user.email}>{user.email[0]}</span>
          <button className="btn sm" type="button" onClick={out}>Sign out</button>
        </nav>
      </header>
      <main id="main" tabIndex={-1}>{children}</main>
    </>
  );
}

export default function App() {
  const route = useRoute();
  const [user, setUser] = useState(undefined); // undefined = still checking
  useEffect(() => { get('/api/v1/me').then((d) => setUser(d.user), () => setUser(null)); }, []);
  useEffect(() => { const f = () => setUser(null); addEventListener('raven:unauthenticated', f); return () => removeEventListener('raven:unauthenticated', f); }, []);
  const p0 = route.parts[0] || '';
  useEffect(() => {
    if (user === undefined) return;
    if (!user && !PUBLIC.has(p0) && p0 !== '') { stash(location.hash); go('/login'); }
    if (user && (p0 === 'login' || p0 === 'register')) { const n = takeNext(); if (n) location.hash = n; else go('/'); }
  }, [user, p0]);
  if (user === undefined) return <div className="boot"><span className="spinner" /></div>;
  const authed = (u) => setUser(u); // the effect above routes to the stashed deep link or the dashboard
  let view;
  if (PUBLIC.has(p0)) {
    view = { login: <Login onAuthed={authed} />, register: <Register onAuthed={authed} />, 'verify-email': <VerifyEmail token={route.query.token} />,
      'forgot-password': <ForgotPassword />, 'reset-password': <ResetPassword token={route.query.token} /> }[p0];
    return user && !['verify-email', 'reset-password'].includes(p0) ? null : view;
  }
  if (!user) return p0 === '' ? <Landing /> : null;
  if (p0 === 'a' && route.parts[1]) view = <Workspace key={route.parts[1]} id={route.parts[1]} tab={route.parts[2] || 'overview'} query={route.query} />;
  else if (p0 === 'pr') view = <PullRequests id={route.parts[1]} />;
  else if (p0 === 'admin') view = user.role === 'admin' ? <Admin tab={route.parts[1] || 'overview'} /> : <Dashboard />;
  else if (p0 === 'system') view = <System />;
  else if (p0 === 'security') view = <Security user={user} setUser={setUser} />;
  else view = <Dashboard />;
  return <Session.Provider value={{ user, setUser }}><Shell user={user} setUser={setUser} route={route}>{view}</Shell></Session.Provider>;
}
