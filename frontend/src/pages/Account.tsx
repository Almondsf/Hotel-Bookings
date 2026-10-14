import { useMutation } from '@tanstack/react-query';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { post } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { ErrorAlert, Field, fieldError, PageHeader } from '../components/ui';

/** Personal security settings: password and two-factor sign-in. */
export function Account() {
  const { user, refreshUser } = useAuth();
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [code, setCode] = useState('');
  const [codes, setCodes] = useState<string[] | null>(null);
  const start = useMutation({
    mutationFn: () => post<{ secret: string; otpauth_uri: string }>('auth/mfa/setup/'),
    onSuccess: setSetup,
  });
  const enable = useMutation({
    mutationFn: () => post<{ recovery_codes: string[] }>('auth/mfa/enable/', { code }),
    onSuccess: async (data) => { setCodes(data.recovery_codes); setSetup(null); await refreshUser(); },
  });

  return (
    <div className="stack" style={{ maxWidth: 640 }}>
      <PageHeader title="My account" subtitle={`${user?.first_name} ${user?.last_name} · ${user?.email}`} />
      <div className="card stack">
        <h2 style={{ margin: 0 }}>Two-factor sign-in</h2>
        {user?.mfa_required && !user.mfa_enabled && (
          <div className="alert error">Your role requires two-factor sign-in. Please set it up now.</div>
        )}
        <ErrorAlert error={start.error} />
        {codes && (
          <div className="alert success">
            <strong>Two-factor sign-in is on.</strong> Save these recovery codes somewhere safe; each works once if
            you lose your phone. They won't be shown again.
            <pre style={{ margin: '8px 0 0', fontSize: 14 }}>{codes.join('\n')}</pre>
          </div>
        )}
        {!codes && user?.mfa_enabled && <p style={{ margin: 0 }}>Two-factor sign-in is <strong>on</strong> for your account.</p>}
        {user?.mfa_enabled && !user.mfa_required && <DisableMfa />}
        {!user?.mfa_enabled && !setup && (
          <div>
            <p style={{ marginTop: 0 }}>Use an authenticator app (Google Authenticator, Microsoft Authenticator, Authy)
              for a code at each sign-in.</p>
            <button className="primary" onClick={() => start.mutate()} disabled={start.isPending}>Set up two-factor sign-in</button>
          </div>
        )}
        {setup && (
          <form className="stack" onSubmit={(e) => { e.preventDefault(); enable.mutate(); }}>
            <ol style={{ margin: 0, paddingLeft: 18 }}>
              <li>In your authenticator app, add an account and choose "Enter a setup key".</li>
              <li>Account name: <code>{user?.email}</code>. Key:{' '}
                <code style={{ fontSize: 15, letterSpacing: 1 }}>{setup.secret.match(/.{1,4}/g)?.join(' ')}</code> (time based).</li>
              <li>Enter the 6-digit code the app shows.</li>
            </ol>
            <Field label="6-digit code" error={fieldError(enable.error, 'code')}>
              <input required inputMode="numeric" autoComplete="one-time-code" value={code}
                     onChange={(e) => setCode(e.target.value)} style={{ maxWidth: 160 }} />
            </Field>
            <div><button className="primary" disabled={enable.isPending}>Turn on</button></div>
          </form>
        )}
      </div>
      <ChangePassword />
    </div>
  );
}

function ChangePassword() {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ current_password: '', new_password: '', confirm: '' });
  const save = useMutation({
    mutationFn: () => post('auth/change-password/', { current_password: form.current_password, new_password: form.new_password }),
    // The server signs every session out after a password change; follow it with a clear message
    onSuccess: async () => {
      navigate('/login', { replace: true, state: { notice: 'Password changed. Please sign in with your new password.' } });
      await logout().catch(() => undefined);
    },
  });
  const mismatch = form.confirm !== '' && form.confirm !== form.new_password;
  return (
    <form className="card stack" onSubmit={(e) => { e.preventDefault(); if (!mismatch) save.mutate(); }}>
      <h2 style={{ margin: 0 }}>Password</h2>
      <p className="muted" style={{ margin: 0 }}>You'll be signed out on all devices and asked to sign in again.</p>
      <ErrorAlert error={save.error} />
      <div className="form-grid">
        <Field label="Current password" error={fieldError(save.error, 'current_password')}>
          <input type="password" required autoComplete="current-password" value={form.current_password}
                 onChange={(e) => setForm({ ...form, current_password: e.target.value })} />
        </Field>
        <Field label="New password" hint="At least 8 characters; not a common or all-numeric password" error={fieldError(save.error, 'new_password')}>
          <input type="password" required autoComplete="new-password" value={form.new_password}
                 onChange={(e) => setForm({ ...form, new_password: e.target.value })} />
        </Field>
        <Field label="Repeat new password" error={mismatch ? "Passwords don't match" : undefined}>
          <input type="password" required autoComplete="new-password" value={form.confirm}
                 onChange={(e) => setForm({ ...form, confirm: e.target.value })} />
        </Field>
      </div>
      <div><button className="primary" disabled={save.isPending || mismatch}>Change password</button></div>
    </form>
  );
}

function DisableMfa() {
  const { refreshUser } = useAuth();
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState('');
  const disable = useMutation({
    mutationFn: () => post('auth/mfa/disable/', { password }),
    onSuccess: async () => { setOpen(false); await refreshUser(); },
  });
  if (!open) return <div><button className="danger" onClick={() => setOpen(true)}>Turn off two-factor sign-in</button></div>;
  return (
    <form className="stack" onSubmit={(e) => { e.preventDefault(); disable.mutate(); }}>
      <ErrorAlert error={disable.error} />
      <Field label="Confirm with your password" error={fieldError(disable.error, 'password')}>
        <input type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} style={{ maxWidth: 280 }} />
      </Field>
      <div className="row"><button type="button" onClick={() => setOpen(false)}>Cancel</button><button className="danger" disabled={disable.isPending}>Turn off</button></div>
    </form>
  );
}
