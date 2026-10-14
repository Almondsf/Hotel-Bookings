import { useState, type FormEvent } from 'react';
import { Link, Navigate } from 'react-router-dom';

import { useAuth } from '../auth/AuthContext';
import { ErrorAlert, Field } from '../components/ui';

export function Login() {
  const { user, login, completeMfa } = useAuth();
  const [ticket, setTicket] = useState<string | null>(null);
  const [code, setCode] = useState('');
  const [useRecovery, setUseRecovery] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to="/dashboard" replace />;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (ticket) await completeMfa(ticket, code, useRecovery);
      else setTicket(await login(email, password));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-screen">
      <form className="card auth-card stack" onSubmit={submit}>
        <div>
          <h1>Staff sign in</h1>
          <p className="muted" style={{ margin: 0 }}>Hotel property management</p>
        </div>
        <ErrorAlert error={error} />
        {ticket ? (
          <>
            <Field label={useRecovery ? 'Recovery code' : 'Code from your authenticator app'}>
              <input autoFocus required autoComplete="one-time-code" inputMode={useRecovery ? 'text' : 'numeric'}
                     value={code} onChange={(e) => setCode(e.target.value)} />
            </Field>
            <button className="primary" disabled={busy}>{busy ? 'Checking…' : 'Verify'}</button>
            <button type="button" onClick={() => { setUseRecovery(!useRecovery); setCode(''); }}>
              {useRecovery ? 'Use authenticator code' : 'Lost your phone? Use a recovery code'}</button>
          </>
        ) : <>
        <Field label="Email">
          <input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label="Password">
          <input type="password" autoComplete="current-password" required value={password}
                 onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <button className="primary" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
        <Link to="/forgot-password" className="muted">Forgot your password?</Link>
        </>}
      </form>
    </div>
  );
}
