import { useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import { post } from '../api/client';
import { ErrorAlert, Field, fieldError } from '../components/ui';

/** Target of invite and password-reset emails: /set-password?uid=…&token=… */
export function SetPassword() {
  const [params] = useSearchParams();
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (password !== confirm) {
      setError(new Error('The passwords do not match.'));
      return;
    }
    try {
      await post('auth/password-reset/confirm/', {
        uid: params.get('uid'), token: params.get('token'), new_password: password,
      });
      setDone(true);
    } catch (e) {
      setError(e);
    }
  }

  return (
    <div className="auth-screen">
      <form className="card auth-card stack" onSubmit={submit}>
        <h1>Set your password</h1>
        {done ? (
          <>
            <div className="alert success">Your password is set.</div>
            <Link to="/login">Sign in</Link>
          </>
        ) : (
          <>
            <ErrorAlert error={error} />
            <Field label="New password" hint="At least 8 characters; avoid common words." error={fieldError(error, 'new_password')}>
              <input type="password" autoComplete="new-password" required value={password}
                     onChange={(e) => setPassword(e.target.value)} />
            </Field>
            <Field label="Confirm password">
              <input type="password" autoComplete="new-password" required value={confirm}
                     onChange={(e) => setConfirm(e.target.value)} />
            </Field>
            <button className="primary">Save password</button>
          </>
        )}
      </form>
    </div>
  );
}

export function ForgotPassword() {
  const [email, setEmail] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState<unknown>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    try {
      const data = await post<{ detail: string }>('auth/password-reset/', { email });
      setMessage(data.detail);
    } catch (e) {
      setError(e);
    }
  }

  return (
    <div className="auth-screen">
      <form className="card auth-card stack" onSubmit={submit}>
        <h1>Reset password</h1>
        {message ? <div className="alert success">{message}</div> : (
          <>
            <ErrorAlert error={error} />
            <Field label="Work email">
              <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
            </Field>
            <button className="primary">Send reset link</button>
          </>
        )}
        <Link to="/login" className="muted">Back to sign in</Link>
      </form>
    </div>
  );
}
