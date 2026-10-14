import { useMutation, useQuery } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';

import { api, post } from '../api/client';
import type { Guest, Paginated, Reservation, RoomType } from '../api/types';
import { ErrorAlert, Field, fieldError, PageHeader } from '../components/ui';
import { addDays, formatMoney, todayISO } from '../lib/format';

interface RoomLine { room_type: string; number_of_adults: number; number_of_children: number }

const SOURCES = [['FRONT_DESK', 'Front desk'], ['PHONE', 'Phone'], ['EMAIL', 'Email'], ['WALK_IN', 'Walk-in'],
  ['CORPORATE', 'Corporate'], ['TRAVEL_AGENT', 'Travel agent'], ['OTA', 'Online travel agency']];

export function NewReservation() {
  const navigate = useNavigate();
  const roomTypes = useQuery({ queryKey: ['room-types'], queryFn: () => api<RoomType[]>('rooms/types/') });
  const [checkIn, setCheckIn] = useState(todayISO());
  const [checkOut, setCheckOut] = useState(addDays(todayISO(), 1));
  const [lines, setLines] = useState<RoomLine[]>([{ room_type: '', number_of_adults: 1, number_of_children: 0 }]);
  const [source, setSource] = useState('FRONT_DESK');
  const [requests, setRequests] = useState('');
  const [existing, setExisting] = useState<Guest | null>(null);
  const [guest, setGuest] = useState({ first_name: '', last_name: '', email: '', phone_number: '', company_name: '' });
  const [search, setSearch] = useState('');

  const matches = useQuery({
    queryKey: ['guests', search],
    queryFn: () => api<Paginated<Guest>>('guests/', { query: { q: search } }),
    enabled: search.length >= 2 && !existing,
  });

  const create = useMutation({
    mutationFn: () => post<Reservation[]>('reservations/', {
      ...(existing ? { guest_id: existing.id } : { guest }),
      check_in_date: checkIn,
      check_out_date: checkOut,
      rooms: lines.map((l) => ({ ...l, room_type: Number(l.room_type) })),
      source,
      special_requests: requests,
    }),
    onSuccess: (created) => navigate(`/reservations/${created[0].id}`),
  });

  const nights = Math.max(0, (new Date(checkOut).getTime() - new Date(checkIn).getTime()) / 86_400_000);
  const estimate = lines.reduce((sum, line) => {
    const type = roomTypes.data?.find((t) => String(t.id) === line.room_type);
    return sum + (type ? Number(type.base_price) * nights : 0);
  }, 0);

  function updateLine(index: number, patch: Partial<RoomLine>) {
    setLines(lines.map((line, i) => (i === index ? { ...line, ...patch } : line)));
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }

  return (
    <form className="stack" onSubmit={submit}>
      <PageHeader title="New reservation" actions={<button className="primary" disabled={create.isPending}>Create reservation</button>} />
      <ErrorAlert error={create.error} />
      <div className="grid cols-2">
        <div className="card stack">
          <h2>Guest</h2>
          {existing ? (
            <div className="row">
              <div><strong>{existing.first_name} {existing.last_name}</strong><div className="muted">{existing.email}</div></div>
              <span className="spacer" />
              <button type="button" onClick={() => setExisting(null)}>Change</button>
            </div>
          ) : (
            <>
              <Field label="Find a returning guest" hint="Name, email or phone">
                <input value={search} onChange={(e) => setSearch(e.target.value)} />
              </Field>
              {matches.data?.results.map((g) => (
                <button type="button" key={g.id} onClick={() => setExisting(g)} style={{ justifyContent: 'space-between' }}>
                  <span>{g.first_name} {g.last_name}</span><span className="muted">{g.email}</span>
                </button>
              ))}
              <div className="muted">…or enter a new guest:</div>
              <div className="form-grid">
                <Field label="First name" error={fieldError(create.error, 'guest')}>
                  <input required value={guest.first_name} onChange={(e) => setGuest({ ...guest, first_name: e.target.value })} />
                </Field>
                <Field label="Last name"><input required value={guest.last_name} onChange={(e) => setGuest({ ...guest, last_name: e.target.value })} /></Field>
                <Field label="Email"><input type="email" required value={guest.email} onChange={(e) => setGuest({ ...guest, email: e.target.value })} /></Field>
                <Field label="Phone"><input value={guest.phone_number} onChange={(e) => setGuest({ ...guest, phone_number: e.target.value })} /></Field>
                <Field label="Company"><input value={guest.company_name} onChange={(e) => setGuest({ ...guest, company_name: e.target.value })} /></Field>
              </div>
            </>
          )}
        </div>
        <div className="card stack">
          <h2>Stay</h2>
          <div className="form-grid">
            <Field label="Arrival" error={fieldError(create.error, 'check_in_date')}>
              <input type="date" required value={checkIn} min={todayISO()} onChange={(e) => setCheckIn(e.target.value)} />
            </Field>
            <Field label="Departure" error={fieldError(create.error, 'check_out_date')}>
              <input type="date" required value={checkOut} min={addDays(checkIn, 1)} onChange={(e) => setCheckOut(e.target.value)} />
            </Field>
            <Field label="Source">
              <select value={source} onChange={(e) => setSource(e.target.value)}>
                {SOURCES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </Field>
          </div>
          <Field label="Special requests"><textarea value={requests} onChange={(e) => setRequests(e.target.value)} /></Field>
        </div>
      </div>
      <div className="card stack">
        <div className="row"><h2 style={{ margin: 0 }}>Rooms</h2><span className="spacer" />
          <span className="muted">Estimate at base rates: {formatMoney(estimate)} before tax</span></div>
        {lines.map((line, index) => (
          <div className="form-grid" key={index}>
            <Field label="Room type">
              <select required value={line.room_type} onChange={(e) => updateLine(index, { room_type: e.target.value })}>
                <option value="">Select</option>
                {roomTypes.data?.map((t) => (
                  <option key={t.id} value={t.id}>{t.name} · {formatMoney(t.base_price)} · up to {t.max_adults}+{t.max_children}</option>
                ))}
              </select>
            </Field>
            <Field label="Adults"><input type="number" min={1} value={line.number_of_adults}
                                         onChange={(e) => updateLine(index, { number_of_adults: Number(e.target.value) })} /></Field>
            <Field label="Children"><input type="number" min={0} value={line.number_of_children}
                                           onChange={(e) => updateLine(index, { number_of_children: Number(e.target.value) })} /></Field>
            {lines.length > 1 && <button type="button" onClick={() => setLines(lines.filter((_, i) => i !== index))}
                                         style={{ alignSelf: 'end' }}>Remove</button>}
          </div>
        ))}
        <div><button type="button" onClick={() => setLines([...lines, { room_type: '', number_of_adults: 1, number_of_children: 0 }])}>
          Add another room</button></div>
      </div>
    </form>
  );
}
