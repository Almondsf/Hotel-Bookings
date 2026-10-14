import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';

import { api, post } from '../api/client';
import type { AuditEntry, Paginated, StaffMember } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { Empty, ErrorAlert, Field, fieldError, Loading, Modal, PageHeader } from '../components/ui';
import { formatDateTime, humanize } from '../lib/format';

const ROLES = ['manager', 'receptionist', 'accountant', 'restaurant', 'bar', 'laundry', 'housekeeping', 'maintenance', 'admin'];

export function Staff() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [inviting, setInviting] = useState(false);
  const staff = useQuery({ queryKey: ['staff'], queryFn: () => api<Paginated<StaffMember>>('staff/') });
  const toggle = useMutation({
    mutationFn: (member: StaffMember) => post(`staff/${member.id}/${member.is_active ? 'deactivate' : 'reactivate'}/`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['staff'] }),
  });
  return (
    <div className="stack">
      <PageHeader title="Staff" subtitle="New staff receive an email to set their own password."
                  actions={<button className="primary" onClick={() => setInviting(true)}>Invite staff</button>} />
      <ErrorAlert error={staff.error || toggle.error} />
      <div className="card table-wrap">
        {staff.isLoading ? <Loading /> : !staff.data?.results.length ? <Empty>No staff.</Empty> : (
          <table>
            <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Last sign-in</th><th>Status</th><th /></tr></thead>
            <tbody>
              {staff.data.results.map((m) => (
                <tr key={m.id}>
                  <td>{m.first_name} {m.last_name}</td><td>{m.email}</td><td>{humanize(m.role)}</td>
                  <td>{m.last_login ? formatDateTime(m.last_login) : <span className="muted">Invite pending</span>}</td>
                  <td>{m.is_active ? <span className="badge ok">Active</span> : <span className="badge">Deactivated</span>}</td>
                  <td>{m.id !== user?.id && <button onClick={() => toggle.mutate(m)}>{m.is_active ? 'Deactivate' : 'Reactivate'}</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {inviting && <InviteDialog onClose={() => setInviting(false)} />}
    </div>
  );
}

function InviteDialog({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({ email: '', first_name: '', last_name: '', phone: '', role: 'receptionist' });
  const invite = useMutation({
    mutationFn: () => post('staff/', form),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['staff'] }); onClose(); },
  });
  return (
    <Modal title="Invite staff member" onClose={onClose}>
      <form className="stack" onSubmit={(e: FormEvent) => { e.preventDefault(); invite.mutate(); }}>
        <ErrorAlert error={invite.error} />
        <div className="form-grid">
          <Field label="First name"><input required value={form.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} /></Field>
          <Field label="Last name"><input required value={form.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })} /></Field>
          <Field label="Email" error={fieldError(invite.error, 'email')}><input type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
          <Field label="Phone"><input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></Field>
          <Field label="Role" error={fieldError(invite.error, 'role')}>
            <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
              {ROLES.map((r) => <option key={r} value={r}>{humanize(r)}</option>)}
            </select>
          </Field>
        </div>
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={invite.isPending}>Send invite</button></div>
      </form>
    </Modal>
  );
}

export function AuditLog() {
  const [action, setAction] = useState('');
  const [page, setPage] = useState(1);
  const log = useQuery({
    queryKey: ['audit', action, page],
    queryFn: () => api<Paginated<AuditEntry>>('audit/', { query: { action, page } }),
    placeholderData: keepPreviousData,
  });
  return (
    <div className="stack">
      <PageHeader title="Audit log" subtitle="Every sensitive action, who did it, and from where. Entries can't be edited or deleted."
                  actions={<input placeholder="Filter by action, e.g. billing.charge_voided" value={action}
                                  onChange={(e) => { setAction(e.target.value); setPage(1); }} style={{ width: 300 }} aria-label="Filter" />} />
      <ErrorAlert error={log.error} />
      <div className="card table-wrap">
        {log.isLoading ? <Loading /> : !log.data?.results.length ? <Empty>No entries.</Empty> : (
          <table>
            <thead><tr><th>When</th><th>Who</th><th>Action</th><th>Target</th><th>Details</th><th>IP</th></tr></thead>
            <tbody>
              {log.data.results.map((e) => (
                <tr key={e.id}>
                  <td style={{ whiteSpace: 'nowrap' }}>{formatDateTime(e.created_at)}</td>
                  <td>{e.actor_email || <span className="muted">system</span>}</td>
                  <td><code>{e.action}</code></td>
                  <td>{e.target_repr}</td>
                  <td className="muted" style={{ fontSize: 12, maxWidth: 320 }}>{Object.keys(e.changes).length ? JSON.stringify(e.changes) : ''}</td>
                  <td className="muted">{e.ip_address ?? ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {log.data && (
          <div className="row" style={{ marginTop: 12 }}>
            <span className="muted">{log.data.count} entries</span><span className="spacer" />
            <button disabled={!log.data.previous} onClick={() => setPage(page - 1)}>Previous</button>
            <button disabled={!log.data.next} onClick={() => setPage(page + 1)}>Next</button>
          </div>
        )}
      </div>
    </div>
  );
}

interface ChannelStatus {
  connected: boolean; provider: string | null; last_full_sync_at: string | null; last_error: string;
  needs_attention: { id: number; ota_name: string; ota_reference: string; problem: string; updated_at: string }[];
  recent: { id: number; ota_name: string; ota_reference: string; status: string; bookings: string[]; updated_at: string }[];
}

export function Channels() {
  const { can } = useAuth();
  const queryClient = useQueryClient();
  const status = useQuery({ queryKey: ['channels'], queryFn: () => api<ChannelStatus>('distribution/status/'), refetchInterval: 60_000 });
  const run = useMutation({
    mutationFn: (path: string) => post(path),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['channels'] }),
  });
  if (status.isLoading) return <Loading />;
  const s = status.data;
  return (
    <div className="stack">
      <PageHeader title="Online channels" subtitle={s?.connected ? `Connected to ${s.provider} · last full sync ${formatDateTime(s.last_full_sync_at)}` : 'No channel manager connected (set it up in the admin).'}
                  actions={s?.connected && can('rates.manage') && <button onClick={() => run.mutate('distribution/sync/')}>Sync now</button>} />
      <ErrorAlert error={status.error || run.error} />
      {s?.last_error && <div className="alert error">Last sync failed: {s.last_error}</div>}
      <div className="card table-wrap">
        <h2>Needs attention</h2>
        {!s?.needs_attention.length ? <p className="muted">Nothing to resolve.</p> : (
          <table>
            <thead><tr><th>Channel</th><th>Reference</th><th>Problem</th><th /></tr></thead>
            <tbody>{s.needs_attention.map((b) => (
              <tr key={b.id}><td>{b.ota_name}</td><td>{b.ota_reference}</td><td>{b.problem}</td>
                <td><button onClick={() => run.mutate(`distribution/bookings/${b.id}/resolve/`)}>Mark handled</button></td></tr>
            ))}</tbody>
          </table>
        )}
      </div>
      <div className="card table-wrap">
        <h2>Recent channel bookings</h2>
        {!s?.recent.length ? <p className="muted">None yet.</p> : (
          <table>
            <thead><tr><th>Channel</th><th>Reference</th><th>Status</th><th>Bookings</th><th>Updated</th></tr></thead>
            <tbody>{s.recent.map((b) => (
              <tr key={b.id}><td>{b.ota_name}</td><td>{b.ota_reference}</td><td>{humanize(b.status)}</td>
                <td>{b.bookings.join(', ') || '—'}</td><td>{formatDateTime(b.updated_at)}</td></tr>
            ))}</tbody>
          </table>
        )}
      </div>
    </div>
  );
}
