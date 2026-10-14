import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';

import { api, patch, post } from '../api/client';
import type { Room } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { Empty, ErrorAlert, Field, fieldError, Loading, Modal, PageHeader, StatusBadge } from '../components/ui';
import { formatDate, formatDateTime, humanize, todayISO } from '../lib/format';
import { ReasonDialog } from './Folios';

interface Task {
  id: number; room_number: string; floor_number: number; room_status: string; task_type: string; status: string;
  is_rush: boolean; assigned_to: number | null; assigned_to_name: string | null; notes: string;
}

interface RoomStatus {
  room_id: number; room_number: string; floor_number: number; room_type: string; status: string;
  housekeeping_status: string; occupied: boolean;
}

export function Housekeeping() {
  const { can } = useAuth();
  const queryClient = useQueryClient();
  const [date, setDate] = useState(todayISO());
  const [mine, setMine] = useState(!can('housekeeping.manage'));
  const [skipping, setSkipping] = useState<Task | null>(null);
  const tasks = useQuery({
    queryKey: ['hk-tasks', date, mine],
    queryFn: () => api<Task[]>('housekeeping/tasks/', { query: { date, mine: mine ? 'true' : undefined } }),
    refetchInterval: 30_000,
  });
  const rooms = useQuery({ queryKey: ['hk-rooms'], queryFn: () => api<RoomStatus[]>('housekeeping/rooms/') });
  const staff = useQuery({
    queryKey: ['hk-staff'], queryFn: () => api<{ id: number; name: string }[]>('housekeeping/staff/'),
    enabled: can('housekeeping.manage'),
  });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['hk-tasks'] });
    void queryClient.invalidateQueries({ queryKey: ['hk-rooms'] });
  };
  const run = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: unknown }) => post(path, body),
    onSuccess: () => { setSkipping(null); refresh(); },
  });
  const assign = useMutation({
    mutationFn: ({ id, user }: { id: number; user: string }) => patch(`housekeeping/tasks/${id}/`, { assigned_to: user ? Number(user) : null }),
    onSuccess: refresh,
  });

  return (
    <div className="stack">
      <PageHeader title="Housekeeping" subtitle={formatDate(date)} actions={<>
        <label className="checkbox"><input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} /> My tasks</label>
        <input type="date" value={date} onChange={(e) => setDate(e.target.value)} aria-label="Date" style={{ width: 'auto' }} />
        {can('housekeeping.manage') && <button className="primary" onClick={() => run.mutate({ path: 'housekeeping/tasks/generate/', body: { date } })}>
          Generate today's list</button>}
      </>} />
      <ErrorAlert error={tasks.error || run.error || assign.error} />
      <div className="card table-wrap">
        {tasks.isLoading ? <Loading /> : !tasks.data?.length ? <Empty>No tasks{mine ? ' assigned to you' : ''}.</Empty> : (
          <table>
            <thead><tr><th>Room</th><th>Task</th><th>Room status</th><th>Assigned to</th><th>Status</th><th /></tr></thead>
            <tbody>
              {tasks.data.map((t) => (
                <tr key={t.id}>
                  <td><strong>{t.room_number}</strong>{t.is_rush && <span className="badge danger" style={{ marginLeft: 6 }}>Rush</span>}</td>
                  <td>{humanize(t.task_type)}{t.notes && <div className="muted" style={{ fontSize: 12 }}>{t.notes}</div>}</td>
                  <td><StatusBadge status={t.room_status} /></td>
                  <td>{can('housekeeping.manage') ? (
                    <select value={t.assigned_to ?? ''} onChange={(e) => assign.mutate({ id: t.id, user: e.target.value })}
                            aria-label={`Assign room ${t.room_number}`} style={{ width: 'auto' }}>
                      <option value="">Unassigned</option>
                      {staff.data?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                    </select>
                  ) : t.assigned_to_name ?? '—'}</td>
                  <td><StatusBadge status={t.status} /></td>
                  <td className="row">
                    {can('housekeeping.work') && t.status === 'PENDING' &&
                      <button onClick={() => run.mutate({ path: `housekeeping/tasks/${t.id}/start/` })}>Start</button>}
                    {can('housekeeping.work') && ['PENDING', 'IN_PROGRESS'].includes(t.status) && <>
                      <button className="primary" onClick={() => run.mutate({ path: `housekeeping/tasks/${t.id}/complete/` })}>Done</button>
                      <button onClick={() => setSkipping(t)}>Skip</button>
                    </>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <div className="card">
        <h2>Room status</h2>
        <div className="rooms">
          {rooms.data?.map((r) => (
            <div key={r.room_id} className={`room-tile ${r.occupied ? 'occupied' : ''} ${r.status !== 'AVAILABLE' && r.status !== 'OCCUPIED' ? 'blocked' : ''}`}
                 style={{ minHeight: 0 }}>
              <div className="row"><span className="number">{r.room_number}</span><span className="spacer" /><StatusBadge status={r.housekeeping_status} /></div>
              <div className="type">{r.room_type}{r.occupied ? ' · Occupied' : ''}</div>
              {can('housekeeping.manage') && r.housekeeping_status === 'CLEAN' && (
                <button style={{ marginTop: 6 }} onClick={() => run.mutate({ path: `housekeeping/rooms/${r.room_id}/status/`, body: { housekeeping_status: 'INSPECTED' } })}>
                  Mark inspected</button>
              )}
            </div>
          ))}
        </div>
      </div>
      {skipping && <ReasonDialog title={`Skip room ${skipping.room_number}`} busy={run.isPending} error={run.error}
                                 onClose={() => setSkipping(null)}
                                 onSubmit={(reason) => run.mutate({ path: `housekeeping/tasks/${skipping.id}/skip/`, body: { reason } })} />}
    </div>
  );
}

interface Ticket {
  id: number; number: string; room: number | null; room_number: string | null; location: string; title: string;
  description: string; category: string; priority: string; status: string; reported_by: string | null;
  assigned_to_name: string | null; out_of_order_until: string | null; resolution_notes: string; created_at: string;
}

const PRIORITY_TONE: Record<string, string> = { URGENT: 'danger', HIGH: 'warn', MEDIUM: 'info', LOW: '' };

export function Maintenance() {
  const { can } = useAuth();
  const queryClient = useQueryClient();
  const [active, setActive] = useState(true);
  const [reporting, setReporting] = useState(false);
  const [resolving, setResolving] = useState<Ticket | null>(null);
  const [moveList, setMoveList] = useState<{ confirmation_number: string; guest_name: string; check_in_date: string }[]>([]);
  const tickets = useQuery({
    queryKey: ['tickets', active],
    queryFn: () => api<{ results: Ticket[] }>('maintenance/tickets/', { query: { active: active ? 'true' : undefined } }),
  });
  const run = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: unknown }) => post(path, body),
    onSuccess: () => { setResolving(null); void queryClient.invalidateQueries({ queryKey: ['tickets'] }); },
  });

  return (
    <div className="stack">
      <PageHeader title="Maintenance" actions={<>
        <label className="checkbox"><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} /> Open tickets only</label>
        {can('maintenance.report') && <button className="primary" onClick={() => setReporting(true)}>Report a fault</button>}
      </>} />
      {moveList.length > 0 && (
        <div className="alert error">
          These reservations are booked into the room while it's out of order. Move them:{' '}
          {moveList.map((b) => `${b.confirmation_number} (${b.guest_name}, ${formatDate(b.check_in_date)})`).join(', ')}
        </div>
      )}
      <ErrorAlert error={tickets.error || run.error} />
      <div className="card table-wrap">
        {tickets.isLoading ? <Loading /> : !tickets.data?.results.length ? <Empty>No tickets.</Empty> : (
          <table>
            <thead><tr><th>Ticket</th><th>Where</th><th>Issue</th><th>Priority</th><th>Status</th><th>Assigned</th><th /></tr></thead>
            <tbody>
              {tickets.data.results.map((t) => (
                <tr key={t.id}>
                  <td>{t.number}<div className="muted" style={{ fontSize: 12 }}>{formatDateTime(t.created_at)}</div></td>
                  <td>{t.room_number ? `Room ${t.room_number}` : t.location}
                    {t.out_of_order_until && <div className="badge danger">Out of order until {formatDate(t.out_of_order_until)}</div>}</td>
                  <td><strong>{t.title}</strong><div className="muted" style={{ fontSize: 12 }}>{humanize(t.category)} · by {t.reported_by ?? '—'}</div>
                    {t.resolution_notes && <div style={{ fontSize: 12 }}>Fix: {t.resolution_notes}</div>}</td>
                  <td><span className={`badge ${PRIORITY_TONE[t.priority]}`}>{humanize(t.priority)}</span></td>
                  <td><StatusBadge status={t.status} /></td>
                  <td>{t.assigned_to_name ?? '—'}</td>
                  <td className="row">{can('maintenance.manage') && t.status !== 'RESOLVED' && <>
                    {t.status !== 'IN_PROGRESS' && <button onClick={() => run.mutate({ path: `maintenance/tickets/${t.id}/start/` })}>Start</button>}
                    {t.status === 'IN_PROGRESS' && <button onClick={() => run.mutate({ path: `maintenance/tickets/${t.id}/hold/` })}>Hold</button>}
                    <button className="primary" onClick={() => setResolving(t)}>Resolve</button>
                  </>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {reporting && <ReportDialog onClose={() => setReporting(false)} onReported={(list) => {
        setMoveList(list); setReporting(false); void queryClient.invalidateQueries({ queryKey: ['tickets'] });
      }} />}
      {resolving && (
        <Modal title={`Resolve ${resolving.number}`} onClose={() => setResolving(null)}>
          <ResolveForm busy={run.isPending} error={run.error} onCancel={() => setResolving(null)}
                       onSubmit={(notes) => run.mutate({ path: `maintenance/tickets/${resolving.id}/resolve/`, body: { resolution_notes: notes } })} />
        </Modal>
      )}
    </div>
  );
}

function ResolveForm({ busy, error, onCancel, onSubmit }: { busy: boolean; error: unknown; onCancel: () => void; onSubmit: (notes: string) => void }) {
  const [notes, setNotes] = useState('');
  return (
    <form className="stack" onSubmit={(e) => { e.preventDefault(); onSubmit(notes); }}>
      <ErrorAlert error={error} />
      <Field label="What was done" hint="The room goes back on sale and to housekeeping for cleaning.">
        <textarea required value={notes} onChange={(e) => setNotes(e.target.value)} />
      </Field>
      <div className="actions"><button type="button" onClick={onCancel}>Cancel</button><button className="primary" disabled={busy}>Resolve</button></div>
    </form>
  );
}

function ReportDialog({ onClose, onReported }: { onClose: () => void; onReported: (bookings: { confirmation_number: string; guest_name: string; check_in_date: string }[]) => void }) {
  const rooms = useQuery({ queryKey: ['rooms'], queryFn: () => api<Room[]>('rooms/all/') });
  const [form, setForm] = useState({ room: '', location: '', title: '', description: '', category: 'OTHER', priority: 'MEDIUM', out_of_order_until: '' });
  const report = useMutation({
    mutationFn: () => post<{ bookings_to_move: { confirmation_number: string; guest_name: string; check_in_date: string }[] }>('maintenance/tickets/', {
      ...form, room: form.room ? Number(form.room) : null, out_of_order_until: form.out_of_order_until || null,
    }),
    onSuccess: (data) => onReported(data.bookings_to_move),
  });
  return (
    <Modal title="Report a fault" onClose={onClose}>
      <form className="stack" onSubmit={(e: FormEvent) => { e.preventDefault(); report.mutate(); }}>
        <ErrorAlert error={report.error} />
        <div className="form-grid">
          <Field label="Room">
            <select value={form.room} onChange={(e) => setForm({ ...form, room: e.target.value })}>
              <option value="">Public area</option>
              {rooms.data?.map((r) => <option key={r.id} value={r.id}>{r.room_number}</option>)}
            </select>
          </Field>
          {!form.room && <Field label="Location" error={fieldError(report.error, 'location')}>
            <input value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} placeholder="e.g. Lobby restroom" />
          </Field>}
          <Field label="Category">
            <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
              {['PLUMBING', 'ELECTRICAL', 'HVAC', 'FURNITURE', 'APPLIANCE', 'IT', 'GENERATOR', 'OTHER'].map((c) => <option key={c} value={c}>{humanize(c)}</option>)}
            </select>
          </Field>
          <Field label="Priority">
            <select value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })}>
              {['LOW', 'MEDIUM', 'HIGH', 'URGENT'].map((p) => <option key={p} value={p}>{humanize(p)}</option>)}
            </select>
          </Field>
        </div>
        <Field label="Issue"><input required value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></Field>
        <Field label="Details"><textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
        {form.room && <Field label="Take room out of order until" hint="Blocks it from sale; you'll see any bookings to move."
                             error={fieldError(report.error, 'out_of_order_until')}>
          <input type="date" min={todayISO()} value={form.out_of_order_until} onChange={(e) => setForm({ ...form, out_of_order_until: e.target.value })} />
        </Field>}
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={report.isPending}>Report</button></div>
      </form>
    </Modal>
  );
}
