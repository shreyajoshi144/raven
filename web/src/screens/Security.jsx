import { useState } from 'react';
import { get, post } from '@legacy/api.js';
import { Card, Eyebrow, ErrorBox, Badge } from '../components/ui.jsx';

export default function Security({ user, setUser }) {
  const [setup, setSetup] = useState(null); const [codes, setCodes] = useState(null); const [code, setCode] = useState(''); const [pw, setPw] = useState('');
  const [error, setError] = useState(null); const [busy, setBusy] = useState(false);
  const refresh = async () => setUser((await get('/api/v1/me')).user);
  const act = (fn) => async (e) => { e?.preventDefault(); setBusy(true); setError(null); try { await fn(); } catch (x) { setError(x); } finally { setBusy(false); } };
  const start = act(async () => setSetup(await post('/api/v1/auth/2fa/setup')));
  const enable = act(async () => { setCodes((await post('/api/v1/auth/2fa/enable', { code })).recovery_codes); setSetup(null); setCode(''); await refresh(); });
  const disable = act(async () => { await post('/api/v1/auth/2fa/disable', { password: pw, code }); setPw(''); setCode(''); setCodes(null); await refresh(); });
  return (
    <div className="page stack-lg">
      <div><Eyebrow>Account</Eyebrow><h1>Security</h1></div>
      <Card className="stack">
        <div className="row spread"><h2>Account</h2>{user.email_verified ? <Badge kind="ok">email verified</Badge> : <Badge kind="warn">email not verified</Badge>}</div>
        <p className="small muted mono">{user.email}</p>
      </Card>
      <Card className="stack">
        <div className="row spread"><h2>Two-factor authentication</h2>{user.totp_enabled ? <Badge kind="ok">on</Badge> : <Badge>off</Badge>}</div>
        <p className="small muted">Use an authenticator app (1Password, Authy, Google Authenticator…). You will enter a 6-digit code after your password.</p>
        {error ? <ErrorBox error={error} /> : null}
        {codes ? (
          <div className="banner warn"><div><strong>Save these recovery codes now.</strong> Each works once if you lose your device, and they are not shown again.
            <pre className="codes">{codes.join('\n')}</pre><button className="btn sm" type="button" onClick={() => navigator.clipboard?.writeText(codes.join('\n'))}>Copy</button> <button className="btn sm" type="button" onClick={() => setCodes(null)}>I saved them</button></div></div>
        ) : null}
        {!user.totp_enabled && !setup ? <div><button className="btn primary" type="button" onClick={start} disabled={busy}>Set up two-factor</button></div> : null}
        {setup ? (
          <form className="stack" onSubmit={enable}>
            <p className="small">Add this key to your authenticator app (choose “enter a setup key”, time-based):</p>
            <pre className="codes" data-testid="totp-secret">{setup.secret}</pre>
            <p className="small muted">Or open <a href={setup.uri}>the otpauth link</a> on a device with an authenticator.</p>
            <div className="field"><label htmlFor="c">Code from the app</label><input id="c" value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" autoComplete="one-time-code" maxLength={10} required /></div>
            <div><button className="btn primary" type="submit" disabled={busy}>Turn on</button></div>
          </form>
        ) : null}
        {user.totp_enabled ? (
          <form className="stack" onSubmit={disable}>
            <div className="field"><label htmlFor="p">Password</label><input id="p" type="password" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="current-password" required /></div>
            <div className="field"><label htmlFor="c2">Current code or recovery code</label><input id="c2" value={code} onChange={(e) => setCode(e.target.value)} autoComplete="one-time-code" required /></div>
            <div><button className="btn" type="submit" disabled={busy}>Turn off</button></div>
          </form>
        ) : null}
      </Card>
    </div>
  );
}
