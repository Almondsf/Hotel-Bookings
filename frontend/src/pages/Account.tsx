import { useMutation } from '@tanstack/react-query';
import { useState } from 'react';

import { post } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { ErrorAlert, Field, fieldError, PageHeader } from '../components/ui';

/** Personal security settings: two-factor sign-in enrolment. */
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
    </div>
  );
}
