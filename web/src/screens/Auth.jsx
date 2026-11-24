import { useEffect, useRef, useState } from 'react';
import { post, ApiError } from '@legacy/api.js';
import { ErrorBox, Spinner } from '../components/ui.jsx';


function Frame({ title, children, foot }) {
  return (
    <div className="auth sky">
      <div className="hero-img" aria-hidden="true" />
      <a className="brand auth-brand on-img" href="#/" aria-label="Raven home"><span className="mark" aria-hidden="true" />Raven</a>
      <div className="auth-card stack">
        <h1>{title}</h1>
        {children}{foot ? <p className="small muted">{foot}</p> : null}
      </div>
    </div>
  );
}

function useSubmit(fn) {
  const [busy, setBusy] = useState(false); const [error, setError] = useState(null);
  const run = async (e) => { e?.preventDefault(); setBusy(true); setError(null); try { await fn(); } catch (x) { setError(x); } finally { setBusy(false); } };
  return { busy, error, run };
}
const Field = ({ id, label, hint, ...p }) => <div className="field"><label htmlFor={id}>{label}</label><input id={id} {...p} />{hint ? <p className="hint">{hint}</p> : null}</div>;
const Err = ({ error }) => (error ? <ErrorBox error={error} /> : null);

export function Login({ onAuthed }) {
  const [email, setEmail] = useState(''); const [pw, setPw] = useState(''); const [mfa, setMfa] = useState(null); const [code, setCode] = useState(''); const [notice, setNotice] = useState(null);
  const first = useSubmit(async () => {
    const r = await post('/api/v1/auth/login', { email, password: pw });
    if (r.mfa_required) setMfa(r.mfa_token); else onAuthed(r.user);
  });
  const second = useSubmit(async () => onAuthed((await post('/api/v1/auth/login/2fa', { mfa_token: mfa, code })).user));
  const resend = async () => { await post('/api/v1/auth/resend-verification', { email }); setNotice('If that account needs verification, a new link is on its way.'); };
  if (mfa) {
    return (
      <Frame eyebrow="Two-factor" title="Enter your code" foot="Lost your device? Use one of your recovery codes instead.">
        <form className="stack" onSubmit={second.run} noValidate>
          <Field id="code" label="6-digit code or recovery code" value={code} onChange={(e) => setCode(e.target.value)} autoComplete="one-time-code" inputMode="numeric" maxLength={20} autoFocus required />
          <Err error={second.error} />
          <button className="btn primary" type="submit" disabled={second.busy}>Verify</button>
        </form>
      </Frame>
    );
  }
  return (
    <Frame eyebrow="Welcome back" title="Sign in" foot={<>No account yet? <a href="#/register">Create one</a></>}>
      <form className="stack" onSubmit={first.run} noValidate>
        <Field id="email" label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" maxLength={320} autoFocus required />
        <Field id="pw" label="Password" type="password" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="current-password" maxLength={200} required />
        <Err error={first.error} />
        {first.error instanceof ApiError && first.error.code === 'EMAIL_NOT_VERIFIED' ? <button className="linklike" type="button" onClick={resend}>Send a new verification link</button> : null}
        {notice ? <div className="banner ok">{notice}</div> : null}
        <button className="btn primary" type="submit" disabled={first.busy}>Sign in</button>
        <a className="small" href="#/forgot-password">Forgot your password?</a>
      </form>
    </Frame>
  );
}

export function Register({ onAuthed }) {
  const [email, setEmail] = useState(''); const [pw, setPw] = useState(''); const [sent, setSent] = useState(false);
  const s = useSubmit(async () => { const r = await post('/api/v1/auth/register', { email, password: pw }); if (r.verification_required) setSent(true); else onAuthed(r.user); });
  if (sent) return <Frame eyebrow="Almost there" title="Check your inbox" foot={<a href="#/login">Back to sign in</a>}><div className="banner ok">We sent a verification link to <strong>{email}</strong>. It works once and expires soon.</div></Frame>;
  return (
    <Frame eyebrow="Get started" title="Create account" foot={<>Already registered? <a href="#/login">Sign in</a></>}>
      <form className="stack" onSubmit={s.run} noValidate>
        <Field id="email" label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" maxLength={320} autoFocus required />
        <Field id="pw" label="Password" type="password" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="new-password" maxLength={200} hint="At least 10 characters." required />
        <Err error={s.error} /><button className="btn primary" type="submit" disabled={s.busy}>Create account</button>
      </form>
    </Frame>
  );
}

export function VerifyEmail({ token }) {
  const [state, setState] = useState('working'); const done = useRef(false);
  useEffect(() => { if (done.current) return; done.current = true; post('/api/v1/auth/verify-email', { token: token || '' }).then(() => setState('ok'), () => setState('bad')); }, [token]);
  return (
    <Frame eyebrow="Email" title={state === 'ok' ? 'Email verified' : state === 'bad' ? 'Link not valid' : 'Verifying…'} foot={<a href="#/login">Go to sign in</a>}>
      {state === 'working' ? <Spinner label="Checking your link…" /> : state === 'ok' ? <div className="banner ok">Your address is confirmed. You can sign in now.</div> : <div className="banner bad" role="alert">This link is invalid, already used, or expired. Request a new one from the sign-in page.</div>}
    </Frame>
  );
}

export function ForgotPassword() {
  const [email, setEmail] = useState(''); const [sent, setSent] = useState(false);
  const s = useSubmit(async () => { await post('/api/v1/auth/forgot-password', { email }); setSent(true); });
  return (
    <Frame eyebrow="Account recovery" title="Reset your password" foot={<a href="#/login">Back to sign in</a>}>
      {sent ? <div className="banner ok">If an account exists for that address, a reset link is on its way. It works once and expires soon.</div> : (
        <form className="stack" onSubmit={s.run} noValidate>
          <Field id="email" label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" autoFocus required />
          <Err error={s.error} /><button className="btn primary" type="submit" disabled={s.busy}>Send reset link</button>
        </form>)}
    </Frame>
  );
}

export function ResetPassword({ token }) {
  const [pw, setPw] = useState(''); const [ok, setOk] = useState(false);
  const s = useSubmit(async () => { await post('/api/v1/auth/reset-password', { token: token || '', password: pw }); setOk(true); });
  return (
    <Frame eyebrow="Account recovery" title="Choose a new password" foot={<a href="#/login">Back to sign in</a>}>
      {ok ? <div className="banner ok">Password changed. All other sessions were signed out.</div> : (
        <form className="stack" onSubmit={s.run} noValidate>
          <Field id="pw" label="New password" type="password" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="new-password" hint="At least 10 characters." autoFocus required />
          <Err error={s.error} /><button className="btn primary" type="submit" disabled={s.busy}>Set password</button>
        </form>)}
    </Frame>
  );
}
