import { useMutation, useQuery } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { api, post } from '../api/client';
import type { Guest, Paginated, Reservation, Room, RoomType } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { emptyGuest, GuestPicker } from '../components/frontDesk';
import { ErrorAlert, Field, fieldError, PageHeader } from '../components/ui';
import { addDays, formatMoney, humanize, todayISO } from '../lib/format';

interface RoomLine { room_type: string; room: string; number_of_adults: number; number_of_children: number }
interface RatePlan { id: number; code: string; name: string; is_active: boolean; corporate_account: number | null; meal_plan: string; adjustment_percent: string }

const SOURCES = [['FRONT_DESK', 'Front desk'], ['PHONE', 'Phone'], ['EMAIL', 'Email'], ['WALK_IN', 'Walk-in'],
  ['CORPORATE', 'Corporate'], ['TRAVEL_AGENT', 'Travel agent'], ['OTA', 'Online travel agency']];

const newLine = (roomType = '', room = ''): RoomLine => ({ room_type: roomType, room, number_of_adults: 1, number_of_children: 0 });

export function NewReservation() {
  const navigate = useNavigate();
  const { can } = useAuth();
  const [params] = useSearchParams();
  const roomTypes = useQuery({ queryKey: ['room-types'], queryFn: () => api<RoomType[]>('rooms/types/') });
  const rooms = useQuery({ queryKey: ['rooms'], queryFn: () => api<Room[]>('rooms/all/'), staleTime: 300_000 });
  const plans = useQuery({ queryKey: ['rate-plans'], queryFn: () => api<Paginated<RatePlan>>('rates/plans/') });
  const accounts = useQuery({ queryKey: ['accounts'], queryFn: () => api<Paginated<{ id: number; name: string }>>('billing/accounts/') });

  const initialIn = params.get('check_in') ?? todayISO();
  const [checkIn, setCheckIn] = useState(initialIn);
  const [checkOut, setCheckOut] = useState(params.get('check_out') ?? addDays(initialIn, 1));
  const [lines, setLines] = useState<RoomLine[]>([newLine(params.get('room_type') ?? '', params.get('room') ?? '')]);
  const [source, setSource] = useState('FRONT_DESK');
  const [requests, setRequests] = useState('');
  const [notes, setNotes] = useState('');
  const [existing, setExisting] = useState<Guest | null>(null);
  const [guest, setGuest] = useState(emptyGuest());
  const [ratePlan, setRatePlan] = useState('');
  const [account, setAccount] = useState('');
  const [override, setOverride] = useState('');
  const [overrideReason, setOverrideReason] = useState('');

  const create = useMutation({
    mutationFn: () => post<Reservation[]>('reservations/', {
      ...(existing ? { guest_id: existing.id } : { guest }),
      check_in_date: checkIn,
      check_out_date: checkOut,
      rooms: lines.map((l) => ({
        room_type: Number(l.room_type), room: l.room ? Number(l.room) : null,
        number_of_adults: l.number_of_adults, number_of_children: l.number_of_children,
      })),
      source: account ? 'CORPORATE' : source,
      special_requests: requests,
      notes,
      ...(ratePlan ? { rate_plan: Number(ratePlan) } : {}),
      ...(account ? { corporate_account: Number(account) } : {}),
      ...(override ? { rate_override: override, override_reason: overrideReason } : {}),
    }),
    onSuccess: (created) => navigate(`/reservations/${created[0].id}`),
  });

  const nights = Math.max(0, Math.round((new Date(checkOut).getTime() - new Date(checkIn).getTime()) / 86_400_000));
  const estimate = lines.reduce((sum, line) => {
    const type = roomTypes.data?.find((t) => String(t.id) === line.room_type);
    const nightly = override ? Number(override) : type ? Number(type.base_price) : 0;
    return sum + nightly * nights;
  }, 0);
  // Negotiated plans only apply with their company; show the rest always
  const availablePlans = plans.data?.results.filter((p) => p.is_active && (!p.corporate_account || String(p.corporate_account) === account)) ?? [];

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
          <GuestPicker existing={existing} onPick={setExisting} guest={guest} onGuestChange={setGuest} error={create.error} />
        </div>
        <div className="card stack">
          <h2>Stay</h2>
          <div className="form-grid">
            <Field label="Arrival" error={fieldError(create.error, 'check_in_date')}>
              <input type="date" required value={checkIn} min={todayISO()}
                     onChange={(e) => { setCheckIn(e.target.value); if (e.target.value >= checkOut) setCheckOut(addDays(e.target.value, 1)); }} />
            </Field>
            <Field label="Departure" error={fieldError(create.error, 'check_out_date')}>
              <input type="date" required value={checkOut} min={addDays(checkIn, 1)} onChange={(e) => setCheckOut(e.target.value)} />
            </Field>
            <Field label="Source">
              <select value={account ? 'CORPORATE' : source} disabled={!!account} onChange={(e) => setSource(e.target.value)}>
                {SOURCES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </Field>
            <Field label="Bill to company" hint="Uses the company's negotiated rate and credit">
              <select value={account} onChange={(e) => { setAccount(e.target.value); setRatePlan(''); }}>
                <option value="">— None —</option>
                {accounts.data?.results.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
            </Field>
            <Field label="Rate plan" error={fieldError(create.error, 'rate_plan')}>
              <select value={ratePlan} onChange={(e) => setRatePlan(e.target.value)}>
                <option value="">Best available rate</option>
                {availablePlans.filter((p) => p.code !== 'BAR').map((p) => (
                  <option key={p.id} value={p.id}>{p.name} ({Number(p.adjustment_percent) > 0 ? '+' : ''}{Number(p.adjustment_percent)}% · {humanize(p.meal_plan)})</option>
                ))}
              </select>
            </Field>
          </div>
          <Field label="Special requests"><textarea value={requests} onChange={(e) => setRequests(e.target.value)} /></Field>
          {lines.length > 1 && <Field label="Group notes" hint="e.g. wedding party, conference block"><input value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>}
          {can('rates.override') && (
            <details>
              <summary className="muted">Agreed rate (manager override)</summary>
              <div className="form-grid" style={{ marginTop: 10 }}>
                <Field label="Nightly rate" error={fieldError(create.error, 'rate_override')}>
                  <input type="number" min={0} step="0.01" value={override} onChange={(e) => setOverride(e.target.value)} />
                </Field>
                <Field label="Reason" error={fieldError(create.error, 'override_reason')}>
                  <input required={!!override} value={overrideReason} onChange={(e) => setOverrideReason(e.target.value)} />
                </Field>
              </div>
            </details>
          )}
        </div>
      </div>
      <div className="card stack">
        <div className="row"><h2 style={{ margin: 0 }}>Rooms</h2><span className="spacer" />
          <span className="muted">{nights} night{nights === 1 ? '' : 's'} · estimate {formatMoney(estimate)} before tax{ratePlan && !override ? ' and plan adjustment' : ''}</span></div>
        {lines.map((line, index) => (
          <div className="form-grid" key={index}>
            <Field label="Room type">
              <select required value={line.room_type} onChange={(e) => updateLine(index, { room_type: e.target.value, room: '' })}>
                <option value="">Select</option>
                {roomTypes.data?.map((t) => (
                  <option key={t.id} value={t.id}>{t.name} · {formatMoney(t.base_price)} · up to {t.max_adults}+{t.max_children}</option>
                ))}
              </select>
            </Field>
            <Field label="Room" hint="Optional: assigned automatically">
              <select value={line.room} onChange={(e) => updateLine(index, { room: e.target.value })} disabled={!line.room_type}>
                <option value="">Any available</option>
                {rooms.data?.filter((r) => String(r.room_type) === line.room_type).map((r) => (
                  <option key={r.id} value={r.id}>{r.room_number}{r.status !== 'AVAILABLE' && r.status !== 'OCCUPIED' ? ` (${humanize(r.status)})` : ''}</option>
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
        <div><button type="button" onClick={() => setLines([...lines, newLine()])}>Add another room</button></div>
      </div>
    </form>
  );
}
