import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { api, downloadFile, patch, post } from '../api/client';
import type { Guest, Paginated } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { Empty, ErrorAlert, Field, Loading, PageHeader, StatusBadge } from '../components/ui';
import { formatDate, formatDateTime, formatMoney, humanize } from '../lib/format';

export function Guests() {
  const [q, setQ] = useState('');
  const [submitted, setSubmitted] = useState('');
  const results = useQuery({
    queryKey: ['guests', submitted],
    queryFn: () => api<Paginated<Guest>>('guests/', { query: { q: submitted } }),
    enabled: submitted.length > 0,
  });
  return (
    <div className="stack">
      <PageHeader title="Guests" subtitle="Search by name, email, phone or company." />
      <form className="card row" onSubmit={(e) => { e.preventDefault(); setSubmitted(q.trim()); }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search guests" style={{ maxWidth: 360 }} aria-label="Search guests" />
        <button>Search</button>
      </form>
      <ErrorAlert error={results.error} />
      {submitted && (
        <div className="card table-wrap">
          {results.isLoading ? <Loading /> : !results.data?.results.length ? <Empty>No guests found.</Empty> : (
            <table>
              <thead><tr><th>Name</th><th>Email</th><th>Phone</th><th>Company</th></tr></thead>
              <tbody>
                {results.data.results.map((g) => (
                  <tr key={g.id}>
                    <td><Link to={`/guests/${g.id}`}>{g.first_name} {g.last_name}</Link>{g.is_vip && <span className="badge warn" style={{ marginLeft: 6 }}>VIP</span>}</td>
                    <td>{g.email}</td><td>{g.phone_number || '—'}</td><td>{g.company_name || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}

interface GuestDetailData extends Guest {
  stays: { id: number; confirmation_number: string; status: string; room_number: string; check_in_date: string; check_out_date: string; total_price: string }[];
}

interface Identification {
  id: number; document_type: string; masked_number: string; issuing_country: string; expiry_date: string | null;
  is_expired: boolean; captured_by: string | null; captured_at: string;
}

export function GuestDetail() {
  const { id } = useParams();
  const { can } = useAuth();
  const queryClient = useQueryClient();
  const guest = useQuery({ queryKey: ['guest', id], queryFn: () => api<GuestDetailData>(`guests/${id}/`) });
  const ids = useQuery({ queryKey: ['guest-ids', id], queryFn: () => api<Identification[]>(`guests/${id}/identifications/`) });
  const [revealed, setRevealed] = useState<Record<number, string>>({});
  const [notes, setNotes] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: (body: Partial<Guest>) => patch<Guest>(`guests/${id}/`, body),
    onSuccess: () => { setNotes(null); void queryClient.invalidateQueries({ queryKey: ['guest', id] }); },
  });
  const navigate = useNavigate();
  const exportData = useMutation({ mutationFn: () => downloadFile(`/api/privacy/guests/${id}/export/`, `guest-${id}-data.json`) });
  const erase = useMutation({
    mutationFn: () => post(`privacy/guests/${id}/anonymise/`, { reason: 'Guest request (NDPA)' }),
    onSuccess: () => navigate('/guests'),
  });
  const reveal = useMutation({
    mutationFn: (identificationId: number) => post<{ id: number; document_number: string }>(
      `guests/${id}/identifications/${identificationId}/reveal/`),
    onSuccess: (data) => setRevealed({ ...revealed, [data.id]: data.document_number }),
  });

  if (guest.isLoading) return <Loading />;
  if (!guest.data) return <ErrorAlert error={guest.error} />;
  const g = guest.data;

  return (
    <div className="stack">
      <PageHeader title={`${g.first_name} ${g.last_name}`} subtitle={g.email}
                  actions={<>
                    {can('bookings.manage') && (
                      <button onClick={() => save.mutate({ is_vip: !g.is_vip })}>{g.is_vip ? 'Remove VIP' : 'Mark VIP'}</button>
                    )}
                    {can('privacy.manage') && <>
                      <button disabled={exportData.isPending} onClick={() => exportData.mutate()}>Export data</button>
                      <button className="danger" onClick={() => {
                        if (window.confirm("Erase this guest's personal data? Bookings and invoices are kept without their details. This cannot be undone.")) erase.mutate();
                      }}>Erase personal data</button>
                    </>}
                  </>} />
      <ErrorAlert error={save.error || reveal.error || erase.error || exportData.error} />
      <div className="grid cols-2">
        <div className="card">
          <h2>Profile</h2>
          <dl className="details">
            <dt>Phone</dt><dd>{g.phone_number || '—'}</dd>
            <dt>Company</dt><dd>{g.company_name || '—'}</dd>
            <dt>Nationality</dt><dd>{g.nationality || '—'}</dd>
            <dt>Address</dt><dd>{g.address || '—'}</dd>
          </dl>
          <div style={{ marginTop: 12 }}>
            {notes === null ? (
              <><strong>Notes</strong><p style={{ whiteSpace: 'pre-wrap' }}>{g.notes || <span className="muted">None</span>}</p>
                {can('bookings.manage') && <button onClick={() => setNotes(g.notes ?? '')}>Edit notes</button>}</>
            ) : (
              <div className="stack">
                <Field label="Notes" hint="Preferences visible to all staff"><textarea value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
                <div className="row"><button className="primary" onClick={() => save.mutate({ notes })}>Save</button>
                  <button onClick={() => setNotes(null)}>Cancel</button></div>
              </div>
            )}
          </div>
        </div>
        <div className="card">
          <h2>Identity documents</h2>
          {!ids.data?.length ? <div className="muted">None recorded.</div> : (
            <table>
              <tbody>
                {ids.data.map((doc) => (
                  <tr key={doc.id}>
                    <td>{humanize(doc.document_type)}<div className="muted" style={{ fontSize: 12 }}>{doc.issuing_country}</div></td>
                    <td><code>{revealed[doc.id] ?? doc.masked_number}</code></td>
                    <td>{doc.is_expired ? <span className="badge danger">Expired</span> : doc.expiry_date ? `Exp. ${formatDate(doc.expiry_date)}` : ''}</td>
                    <td className="muted" style={{ fontSize: 12 }}>{formatDateTime(doc.captured_at)}</td>
                    <td>{can('guests.view_identity') && !revealed[doc.id] && (
                      <button onClick={() => reveal.mutate(doc.id)} title="Recorded in the audit log">Reveal</button>
                    )}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
      <div className="card table-wrap">
        <h2>Stays</h2>
        {!g.stays.length ? <div className="muted">No stays yet.</div> : (
          <table>
            <thead><tr><th>Confirmation</th><th>Room</th><th>Arrival</th><th>Departure</th><th>Status</th><th className="num">Room total</th></tr></thead>
            <tbody>
              {g.stays.map((s) => (
                <tr key={s.id}>
                  <td><Link to={`/reservations/${s.id}`}>{s.confirmation_number}</Link></td>
                  <td>{s.room_number}</td><td>{formatDate(s.check_in_date)}</td><td>{formatDate(s.check_out_date)}</td>
                  <td><StatusBadge status={s.status} /></td><td className="num">{formatMoney(s.total_price)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
