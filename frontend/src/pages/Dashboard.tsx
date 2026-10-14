import { useQuery } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';

import { api } from '../api/client';
import type { Paginated, Reservation, Summary } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { CheckInDialog, CheckOutDialog, WalkInDialog } from '../components/frontDesk';
import { ErrorAlert, Loading, PageHeader, StatusBadge } from '../components/ui';
import { formatDate, formatMoney, todayISO } from '../lib/format';

function Stat({ label, value, to }: { label: string; value: string | number; to?: string }) {
  const body = (
    <div className="card stat">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
    </div>
  );
  return to ? <Link to={to} className="stat-link">{body}</Link> : body;
}

type Pending = { kind: 'check-in' | 'check-out'; reservation: Reservation } | { kind: 'walk-in' } | null;

export function Dashboard() {
  const { can } = useAuth();
  const manage = can('bookings.manage');
  const today = todayISO();
  const [pending, setPending] = useState<Pending>(null);
  const summary = useQuery({ queryKey: ['summary', today], queryFn: () => api<Summary>('reservations/summary/') });
  const arrivals = useQuery({
    queryKey: ['reservations', { arrival: today }],
    queryFn: () => api<Paginated<Reservation>>('reservations/', { query: { arrival: today } }),
  });
  const departures = useQuery({
    queryKey: ['reservations', { departure: today, status: 'CHECKED_IN' }],
    queryFn: () => api<Paginated<Reservation>>('reservations/', { query: { departure: today, status: 'CHECKED_IN' } }),
  });

  if (summary.isLoading) return <Loading />;
  const s = summary.data;
  // Cancelled and no-show bookings for today are history, not work to do
  const arriving = arrivals.data?.results.filter((r) => ['CONFIRMED', 'PENDING', 'CHECKED_IN'].includes(r.status));

  return (
    <div className="stack">
      <PageHeader
        title="Today"
        subtitle={formatDate(today)}
        actions={manage && <>
          <button onClick={() => setPending({ kind: 'walk-in' })}>Walk-in</button>
          <Link className="button primary" to="/reservations/new">New reservation</Link>
        </>}
      />
      <ErrorAlert error={summary.error} />
      {s && (
        <div className="grid stats">
          <Stat label="Occupancy tonight" value={`${s.occupancy_percent}%`} to="/room-board" />
          <Stat label="Arrivals expected" value={s.arrivals_expected} to={`/reservations?arrival=${today}&status=CONFIRMED`} />
          <Stat label="Checked in today" value={s.arrivals_checked_in} to={`/reservations?arrival=${today}&status=CHECKED_IN`} />
          <Stat label="Departures due" value={s.departures_expected} to={`/reservations?departure=${today}&status=CHECKED_IN`} />
          <Stat label="In house" value={s.in_house} to="/reservations?in_house=true" />
          <Stat label="Unpaid online holds" value={s.pending_holds} to="/reservations?status=PENDING" />
        </div>
      )}
      <div className="grid cols-2">
        <ReservationList
          title="Arriving today" data={arriving} empty="No more arrivals today."
          action={(r) => manage && r.status === 'CONFIRMED' &&
            <button className="primary small" onClick={() => setPending({ kind: 'check-in', reservation: r })}>Check in</button>}
        />
        <ReservationList
          title="Departing today" data={departures.data?.results} empty="Everyone due out has left."
          action={(r) => manage &&
            <button className="small" onClick={() => setPending({ kind: 'check-out', reservation: r })}>Check out</button>}
        />
      </div>

      {pending?.kind === 'check-in' && <CheckInDialog reservation={pending.reservation} onClose={() => setPending(null)} />}
      {pending?.kind === 'check-out' && <CheckOutDialog reservation={pending.reservation} onClose={() => setPending(null)} />}
      {pending?.kind === 'walk-in' && <WalkInDialog onClose={() => setPending(null)} />}
    </div>
  );
}

function ReservationList({ title, data, empty, action }: {
  title: string; data?: Reservation[]; empty: string; action: (r: Reservation) => ReactNode;
}) {
  return (
    <div className="card">
      <h2>{title}</h2>
      {!data ? <Loading /> : data.length === 0 ? <div className="muted">{empty}</div> : (
        <table>
          <tbody>
            {data.map((r) => (
              <tr key={r.id}>
                <td>
                  <Link to={`/reservations/${r.id}`}>{r.guest.first_name} {r.guest.last_name}</Link>
                  {r.guest.is_vip && <span className="badge warn" style={{ marginLeft: 6 }}>VIP</span>}
                  {r.folio && Number(r.folio.balance) > 0 && r.status === 'CHECKED_IN' &&
                    <div className="muted" style={{ fontSize: 12 }}>Owes {formatMoney(r.folio.balance)}</div>}
                </td>
                <td>Room {r.room_number}</td>
                <td><StatusBadge status={r.status} /></td>
                <td style={{ textAlign: 'right' }}>{action(r)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
