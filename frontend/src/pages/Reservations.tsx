import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import { api } from '../api/client';
import type { Paginated, Reservation } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { Empty, ErrorAlert, Loading, PageHeader, StatusBadge } from '../components/ui';
import { formatDate, formatMoney } from '../lib/format';

const FILTERS = ['status', 'arrival', 'departure', 'in_house', 'q', 'page'] as const;

export function Reservations() {
  const { can } = useAuth();
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState(params.get('q') ?? '');
  const query = Object.fromEntries(FILTERS.map((key) => [key, params.get(key) ?? undefined]));

  const list = useQuery({
    queryKey: ['reservations', query],
    queryFn: () => api<Paginated<Reservation>>('reservations/', { query }),
    placeholderData: keepPreviousData,
  });

  function update(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    if (key !== 'page') next.delete('page');
    setParams(next);
  }

  const page = Number(params.get('page') ?? 1);
  return (
    <div className="stack">
      <PageHeader title="Reservations" actions={can('bookings.manage') && <Link className="button primary" to="/reservations/new">New reservation</Link>} />
      <div className="card row">
        <form className="row" style={{ flex: 1 }} onSubmit={(e) => { e.preventDefault(); update('q', search); }}>
          <input placeholder="Name, email, phone or confirmation number" value={search}
                 onChange={(e) => setSearch(e.target.value)} style={{ maxWidth: 340 }} aria-label="Search" />
          <button>Search</button>
        </form>
        <select value={params.get('status') ?? ''} onChange={(e) => update('status', e.target.value)} aria-label="Status"
                style={{ width: 'auto' }}>
          <option value="">All statuses</option>
          {['PENDING', 'CONFIRMED', 'CHECKED_IN', 'CHECKED_OUT', 'CANCELLED', 'NO_SHOW'].map((s) => (
            <option key={s} value={s}>{s.replace('_', ' ').toLowerCase()}</option>
          ))}
        </select>
        <label className="row muted">Arriving <input type="date" value={params.get('arrival') ?? ''}
                                                    onChange={(e) => update('arrival', e.target.value)} style={{ width: 'auto' }} /></label>
        <label className="checkbox"><input type="checkbox" checked={params.get('in_house') === 'true'}
                                            onChange={(e) => update('in_house', e.target.checked ? 'true' : '')} /> In house</label>
      </div>
      <ErrorAlert error={list.error} />
      <div className="card table-wrap">
        {list.isLoading ? <Loading /> : !list.data?.results.length ? <Empty>No reservations match.</Empty> : (
          <table>
            <thead>
              <tr><th>Confirmation</th><th>Guest</th><th>Room</th><th>Arrival</th><th>Departure</th><th>Status</th><th className="num">Total</th></tr>
            </thead>
            <tbody>
              {list.data.results.map((r) => (
                <tr key={r.id}>
                  <td><Link to={`/reservations/${r.id}`}>{r.confirmation_number}</Link>
                    {r.group_reference && <div style={{ fontSize: 12 }}><Link to={`/groups/${r.group_reference}`} className="muted">{r.group_reference}</Link></div>}</td>
                  <td>{r.guest.first_name} {r.guest.last_name}{r.guest.is_vip && <span className="badge warn" style={{ marginLeft: 6 }}>VIP</span>}</td>
                  <td>{r.room_number} <span className="muted">{r.room_type_name}</span></td>
                  <td>{formatDate(r.check_in_date)}</td>
                  <td>{formatDate(r.check_out_date)}</td>
                  <td><StatusBadge status={r.status} /></td>
                  <td className="num">{formatMoney(r.total_with_taxes)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {list.data && list.data.count > 50 && (
          <div className="row" style={{ marginTop: 12 }}>
            <span className="muted">{list.data.count} reservations</span>
            <span className="spacer" />
            <button disabled={!list.data.previous} onClick={() => update('page', String(page - 1))}>Previous</button>
            <button disabled={!list.data.next} onClick={() => update('page', String(page + 1))}>Next</button>
          </div>
        )}
      </div>
    </div>
  );
}
