import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { api, openFile, post } from '../api/client';
import { ErrorAlert, Loading, PageHeader } from '../components/ui';
import { addDays, formatDate, formatDateTime, formatMoney, humanize, todayISO } from '../lib/format';

interface OccupancyRow {
  date: string; actual: boolean; rooms_available: number; rooms_sold: number; occupancy_percent: number;
  room_revenue: string; adr: string; revpar: string;
}

interface RevenueReport {
  categories: { category: string; name: string; net: string; tax: string; gross: string }[];
  taxes: { code: string; name: string; amount: string }[];
  totals: { net: string; tax: string; gross: string };
}

interface PaymentsReport {
  by_method: { method: string; received: string; refunded: string; net: string }[];
  by_staff: { staff: string; net: string }[];
  total: string;
}

const compactMoney = new Intl.NumberFormat('en-NG', { style: 'currency', currency: 'NGN', notation: 'compact', maximumFractionDigits: 1 });

function sum(rows: OccupancyRow[], key: 'rooms_sold' | 'rooms_available' | 'room_revenue') {
  return rows.reduce((total, row) => total + Number(row[key]), 0);
}

function Tile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="card stat">
      <div className="label">{label}</div>
      <div className="value kpi">{value}</div>
      {note && <div className="muted" style={{ fontSize: 12 }}>{note}</div>}
    </div>
  );
}

/** Daily occupancy, one bar per day. Solid = actual (closed days), hatched = on the books. */
function OccupancyChart({ rows }: { rows: OccupancyRow[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const height = 180;
  const slot = 100 / rows.length;
  const hovered = hover === null ? null : rows[hover];
  return (
    <figure className="viz" aria-label="Daily occupancy">
      <div className="viz-legend" aria-hidden="true">
        <span><i className="swatch" /> Actual</span>
        <span><i className="swatch forecast" /> On the books</span>
      </div>
      <div className="viz-plot" style={{ height }} onMouseLeave={() => setHover(null)}>
        {[100, 50, 0].map((tick) => (
          <div key={tick} className="viz-grid" style={{ bottom: `${tick}%` }}><span>{tick}%</span></div>
        ))}
        {rows.map((row, i) => (
          <div key={row.date} className="viz-slot" style={{ left: `${i * slot}%`, width: `${slot}%` }}
               onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)} tabIndex={0}
               aria-label={`${formatDate(row.date)}: ${row.occupancy_percent}% (${row.actual ? 'actual' : 'on the books'})`}>
            <div className={`viz-bar ${row.actual ? '' : 'forecast'}`}
                 style={{ height: `${Math.min(100, row.occupancy_percent)}%` }} />
          </div>
        ))}
        {hovered && (
          <div className="viz-tooltip" style={{ left: `${(hover! + 0.5) * slot}%` }} role="status">
            <strong>{formatDate(hovered.date)}</strong>
            <div>{hovered.occupancy_percent}% · {hovered.rooms_sold}/{hovered.rooms_available} rooms</div>
            <div>ADR {formatMoney(hovered.adr)}</div>
            <div className="muted">{hovered.actual ? 'Actual' : 'On the books'}</div>
          </div>
        )}
      </div>
      <div className="viz-axis">
        <span>{formatDate(rows[0].date)}</span><span>{formatDate(rows[rows.length - 1].date)}</span>
      </div>
    </figure>
  );
}

export function Reports() {
  const [from, setFrom] = useState(addDays(todayISO(), -6));
  const [to, setTo] = useState(addDays(todayISO(), 7));
  const range = { from, to };
  const occupancy = useQuery({ queryKey: ['occupancy', range], queryFn: () => api<OccupancyRow[]>('reports/occupancy/', { query: range }) });
  const revenue = useQuery({ queryKey: ['revenue', range], queryFn: () => api<RevenueReport>('reports/revenue/', { query: range }) });
  const payments = useQuery({ queryKey: ['payments', range], queryFn: () => api<PaymentsReport>('reports/payments/', { query: range }) });

  const rows = occupancy.data ?? [];
  const sold = sum(rows, 'rooms_sold');
  const available = sum(rows, 'rooms_available');
  const roomRevenue = sum(rows, 'room_revenue');
  const csv = (path: string) => void openFile(`/api/reports/${path}/?from=${from}&to=${to}&export=csv`);

  return (
    <div className="stack">
      <PageHeader title="Reports" subtitle={`${formatDate(from)} – ${formatDate(to)}`} actions={<>
        <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} aria-label="From" style={{ width: 'auto' }} />
        <input type="date" value={to} onChange={(e) => setTo(e.target.value)} aria-label="To" style={{ width: 'auto' }} />
        <Link className="button" to="/reports/ledgers">Ledgers</Link>
      </>} />
      <ErrorAlert error={occupancy.error || revenue.error || payments.error} />
      {occupancy.isLoading ? <Loading /> : rows.length > 0 && (
        <>
          <div className="grid stats">
            <Tile label="Occupancy" value={`${available ? ((sold / available) * 100).toFixed(1) : '0'}%`} note={`${sold} room nights`} />
            <Tile label="ADR" value={compactMoney.format(sold ? roomRevenue / sold : 0)} note="Average daily rate" />
            <Tile label="RevPAR" value={compactMoney.format(available ? roomRevenue / available : 0)} note="Revenue per available room" />
            <Tile label="Room revenue" value={compactMoney.format(roomRevenue)} note="Actual + on the books" />
          </div>
          <div className="card">
            <div className="row"><h2 style={{ margin: 0 }}>Daily occupancy</h2><span className="spacer" />
              <button onClick={() => csv('occupancy')}>Export CSV</button></div>
            <OccupancyChart rows={rows} />
            <details>
              <summary className="muted">Table view</summary>
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Date</th><th>Basis</th><th className="num">Sold</th><th className="num">Available</th>
                    <th className="num">Occupancy</th><th className="num">ADR</th><th className="num">RevPAR</th><th className="num">Room revenue</th></tr></thead>
                  <tbody>{rows.map((r) => (
                    <tr key={r.date}><td>{formatDate(r.date)}</td><td>{r.actual ? 'Actual' : 'On the books'}</td>
                      <td className="num">{r.rooms_sold}</td><td className="num">{r.rooms_available}</td>
                      <td className="num">{r.occupancy_percent}%</td><td className="num">{formatMoney(r.adr)}</td>
                      <td className="num">{formatMoney(r.revpar)}</td><td className="num">{formatMoney(r.room_revenue)}</td></tr>
                  ))}</tbody>
                </table>
              </div>
            </details>
          </div>
        </>
      )}
      <div className="grid cols-2">
        <div className="card table-wrap">
          <div className="row"><h2 style={{ margin: 0 }}>Revenue by department</h2><span className="spacer" />
            <button onClick={() => csv('revenue')}>Export CSV</button></div>
          {revenue.data && !revenue.data.categories.length && <p className="muted">No charges posted in this period.</p>}
          {revenue.data && revenue.data.categories.length > 0 && (
            <table>
              <thead><tr><th>Department</th><th className="num">Net</th><th className="num">Tax</th><th className="num">Gross</th></tr></thead>
              <tbody>
                {revenue.data.categories.map((c) => (
                  <tr key={c.category}><td>{c.name}</td><td className="num">{formatMoney(c.net)}</td>
                    <td className="num">{formatMoney(c.tax)}</td><td className="num">{formatMoney(c.gross)}</td></tr>
                ))}
                <tr><td><strong>Total</strong></td><td className="num"><strong>{formatMoney(revenue.data.totals.net)}</strong></td>
                  <td className="num"><strong>{formatMoney(revenue.data.totals.tax)}</strong></td>
                  <td className="num"><strong>{formatMoney(revenue.data.totals.gross)}</strong></td></tr>
              </tbody>
            </table>
          )}
          {revenue.data && revenue.data.taxes.length > 0 && (
            <p className="muted" style={{ marginBottom: 0 }}>Taxes collected: {revenue.data.taxes.map((t) => `${t.name} ${formatMoney(t.amount)}`).join(' · ')}</p>
          )}
        </div>
        <div className="card table-wrap">
          <div className="row"><h2 style={{ margin: 0 }}>Payments received</h2><span className="spacer" />
            <button onClick={() => csv('payments')}>Export CSV</button></div>
          {payments.data && !payments.data.by_method.length && <p className="muted">No payments received in this period.</p>}
          {payments.data && payments.data.by_method.length > 0 && (
            <table>
              <thead><tr><th>Method</th><th className="num">Received</th><th className="num">Refunded</th><th className="num">Net</th></tr></thead>
              <tbody>
                {payments.data.by_method.map((m) => (
                  <tr key={m.method}><td>{humanize(m.method)}</td><td className="num">{formatMoney(m.received)}</td>
                    <td className="num">{formatMoney(m.refunded)}</td><td className="num">{formatMoney(m.net)}</td></tr>
                ))}
                <tr><td><strong>Total</strong></td><td /><td /><td className="num"><strong>{formatMoney(payments.data.total)}</strong></td></tr>
              </tbody>
            </table>
          )}
          {payments.data && payments.data.by_staff.length > 0 && (
            <p className="muted" style={{ marginBottom: 0 }}>By staff: {payments.data.by_staff.map((s) => `${s.staff} ${formatMoney(s.net)}`).join(' · ')}</p>
          )}
        </div>
      </div>
    </div>
  );
}

interface Ledger { folios: { folio_id: number; folio: string; name: string; room: string | null; balance: string }[]; total_balance: string }
interface CityLedger { accounts: { account_id: number; name: string; current: string; '31_60': string; '61_90': string; over_90: string; balance: string }[]; total: string }

export function Ledgers() {
  const guest = useQuery({ queryKey: ['guest-ledger'], queryFn: () => api<Ledger>('reports/guest-ledger/') });
  const city = useQuery({ queryKey: ['city-ledger'], queryFn: () => api<CityLedger>('reports/city-ledger/') });
  return (
    <div className="stack">
      <PageHeader title="Ledgers" subtitle="What guests and companies owe the hotel right now." />
      <ErrorAlert error={guest.error || city.error} />
      <div className="card table-wrap">
        <h2>Guest ledger (open folios) · {formatMoney(guest.data?.total_balance)}</h2>
        <table>
          <thead><tr><th>Folio</th><th>Name</th><th>Room</th><th className="num">Balance</th></tr></thead>
          <tbody>{guest.data?.folios.map((f) => (
            <tr key={f.folio_id}><td><Link to={`/folios/${f.folio_id}`}>{f.folio}</Link></td><td>{f.name}</td>
              <td>{f.room ?? '—'}</td><td className="num">{formatMoney(f.balance)}</td></tr>
          ))}</tbody>
        </table>
      </div>
      <div className="card table-wrap">
        <h2>City ledger (companies) · {formatMoney(city.data?.total)}</h2>
        <table>
          <thead><tr><th>Company</th><th className="num">0–30 days</th><th className="num">31–60</th><th className="num">61–90</th>
            <th className="num">90+</th><th className="num">Balance</th></tr></thead>
          <tbody>{city.data?.accounts.map((a) => (
            <tr key={a.account_id}><td>{a.name}</td><td className="num">{formatMoney(a.current)}</td>
              <td className="num">{formatMoney(a['31_60'])}</td><td className="num">{formatMoney(a['61_90'])}</td>
              <td className="num">{formatMoney(a.over_90)}</td><td className="num"><strong>{formatMoney(a.balance)}</strong></td></tr>
          ))}</tbody>
        </table>
      </div>
    </div>
  );
}

interface AuditStatus {
  business_date: string;
  exceptions: { pending_arrivals: { id: number; confirmation_number: string; guest_name: string; room: string }[];
    departures_not_checked_out: { id: number; confirmation_number: string; guest_name: string; room: string }[] };
  history: { date: string; closed_at: string; statistics: Record<string, unknown> }[];
}

export function NightAudit() {
  const queryClient = useQueryClient();
  const [autoNoShow, setAutoNoShow] = useState(false);
  const status = useQuery({ queryKey: ['night-audit'], queryFn: () => api<AuditStatus>('night-audit/') });
  const run = useMutation({
    mutationFn: () => post<{ closed: string; opened: string; room_charges_posted: number; no_shows: number }>('night-audit/', { auto_no_show: autoNoShow }),
    onSuccess: () => queryClient.invalidateQueries(),
  });
  if (status.isLoading) return <Loading />;
  const s = status.data;
  if (!s) return <ErrorAlert error={status.error} />;
  const departures = s.exceptions.departures_not_checked_out;
  const arrivals = s.exceptions.pending_arrivals;
  const blocked = departures.length > 0 || (arrivals.length > 0 && !autoNoShow);

  return (
    <div className="stack">
      <PageHeader title="Night audit" subtitle={`Business date ${formatDate(s.business_date)}`} />
      {run.data && <div className="alert success">Closed {formatDate(run.data.closed)}: {run.data.room_charges_posted} room charges posted,
        {' '}{run.data.no_shows} no-shows. Business date is now {formatDate(run.data.opened)}.</div>}
      <ErrorAlert error={run.error} />
      <div className="card stack">
        <h2 style={{ margin: 0 }}>Before closing the day</h2>
        {departures.length > 0 && <div><strong>Guests due out but still checked in</strong> (check them out or extend their stay):
          <ul>{departures.map((b) => <li key={b.id}><Link to={`/reservations/${b.id}`}>{b.guest_name}</Link> · Room {b.room}</li>)}</ul></div>}
        {arrivals.length > 0 && <div><strong>Arrivals still expected</strong>:
          <ul>{arrivals.map((b) => <li key={b.id}><Link to={`/reservations/${b.id}`}>{b.guest_name}</Link> · Room {b.room}</li>)}</ul>
          <label className="checkbox"><input type="checkbox" checked={autoNoShow} onChange={(e) => setAutoNoShow(e.target.checked)} />
            Mark them as no-shows (the no-show fee is charged)</label></div>}
        {!departures.length && !arrivals.length && <div className="muted">Nothing outstanding.</div>}
        <div><button className="primary" disabled={blocked || run.isPending} onClick={() => run.mutate()}>
          Close {formatDate(s.business_date)} and post room charges</button></div>
      </div>
      <div className="card table-wrap">
        <h2>Recent days</h2>
        {!s.history.length ? <p className="muted">No days closed yet. The first night audit starts the history.</p> : <table>
          <thead><tr><th>Date</th><th>Closed</th><th className="num">Occupancy</th><th className="num">ADR</th><th className="num">Room revenue</th></tr></thead>
          <tbody>{s.history.map((d) => (
            <tr key={d.date}><td>{formatDate(d.date)}</td><td>{formatDateTime(d.closed_at)}</td>
              <td className="num">{String(d.statistics.occupancy_percent ?? '—')}%</td>
              <td className="num">{formatMoney(d.statistics.adr as string)}</td>
              <td className="num">{formatMoney(d.statistics.room_revenue as string)}</td></tr>
          ))}</tbody>
        </table>}
      </div>
    </div>
  );
}
