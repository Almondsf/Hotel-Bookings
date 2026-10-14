import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';

import { api } from '../api/client';
import type { Paginated, Reservation, Summary } from '../api/types';
import { ErrorAlert, Loading, PageHeader, StatusBadge } from '../components/ui';
import { formatDate, todayISO } from '../lib/format';

function Stat({ label, value, to }: { label: string; value: string | number; to?: string }) {
  const body = (
    <div className="card stat">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
    </div>
  );
  return to ? <Link to={to} style={{ color: 'inherit', textDecoration: 'none' }}>{body}</Link> : body;
}

export function Dashboard() {
  const today = todayISO();
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

  return (
    <div className="stack">
      <PageHeader title="Today" subtitle={formatDate(today)} />
      <ErrorAlert error={summary.error} />
      {s && (
        <div className="grid stats">
          <Stat label="Occupancy tonight" value={`${s.occupancy_percent}%`} to="/room-board" />
          <Stat label="Arrivals expected" value={s.arrivals_expected} to={`/reservations?arrival=${today}`} />
          <Stat label="Checked in today" value={s.arrivals_checked_in} />
          <Stat label="Departures due" value={s.departures_expected} to={`/reservations?departure=${today}&status=CHECKED_IN`} />
          <Stat label="In house" value={s.in_house} to="/reservations?in_house=true" />
          <Stat label="Unpaid online holds" value={s.pending_holds} />
        </div>
      )}
      <div className="grid cols-2">
        <ReservationList title="Arriving today" data={arrivals.data?.results} />
        <ReservationList title="Departing today" data={departures.data?.results} />
      </div>
    </div>
  );
}

function ReservationList({ title, data }: { title: string; data?: Reservation[] }) {
  return (
    <div className="card">
      <h2>{title}</h2>
      {!data ? <Loading /> : data.length === 0 ? <div className="muted">None.</div> : (
        <table>
          <tbody>
            {data.map((r) => (
              <tr key={r.id}>
                <td><Link to={`/reservations/${r.id}`}>{r.guest.first_name} {r.guest.last_name}</Link>
                  {r.guest.is_vip && <span className="badge warn" style={{ marginLeft: 6 }}>VIP</span>}</td>
                <td>Room {r.room_number}</td>
                <td><StatusBadge status={r.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
