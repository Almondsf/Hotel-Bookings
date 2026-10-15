/**
 * Front-desk building blocks shared by the dashboard, room board and
 * reservation pages: check-in / check-out / walk-in / edit-stay dialogs and
 * the guest picker.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { api, patch, post } from '../api/client';
import type { Guest, Paginated, Reservation, RoomType } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { addDays, formatDate, formatMoney, todayISO } from '../lib/format';
import { ErrorAlert, Field, fieldError, Loading, Modal } from './ui';

export const ID_TYPES = [
  ['PASSPORT', 'International Passport'], ['NATIONAL_ID', 'National ID (NIN)'],
  ['DRIVERS_LICENCE', "Driver's Licence"], ['VOTERS_CARD', "Voter's Card"],
  ['RESIDENCE_PERMIT', 'Residence Permit'], ['OTHER', 'Other'],
];

/** Everything that shows reservations or rooms must refresh after a front-desk action. */
export function useRefreshFrontDesk() {
  const queryClient = useQueryClient();
  return () => {
    for (const key of ['reservations', 'reservation', 'summary', 'room-board', 'folio', 'folios', 'housekeeping']) {
      void queryClient.invalidateQueries({ queryKey: [key] });
    }
  };
}

/** POST a lifecycle action (check-in, check-out…) for one reservation. */
export function useReservationAction(id: number | string, onDone?: (r: Reservation) => void) {
  const refresh = useRefreshFrontDesk();
  return useMutation({
    mutationFn: ({ action, body }: { action: string; body?: unknown }) => post<Reservation>(`reservations/${id}/${action}/`, body),
    onSuccess: (data) => { refresh(); onDone?.(data); },
  });
}

// --- Identification -----------------------------------------------------------

export interface IdDocument { document_type: string; document_number: string; issuing_country: string; expiry_date: string }
export const emptyIdDocument = (): IdDocument => ({ document_type: 'NATIONAL_ID', document_number: '', issuing_country: 'Nigeria', expiry_date: '' });
export const idPayload = (doc: IdDocument) => ({ ...doc, expiry_date: doc.expiry_date || null });

export function IdFields({ doc, onChange, required }: { doc: IdDocument; onChange: (doc: IdDocument) => void; required: boolean }) {
  return (
    <div className="form-grid">
      <Field label="Document type">
        <select value={doc.document_type} onChange={(e) => onChange({ ...doc, document_type: e.target.value })}>
          {ID_TYPES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </Field>
      <Field label="Document number" hint="Stored encrypted">
        <input required={required} value={doc.document_number} autoComplete="off"
               onChange={(e) => onChange({ ...doc, document_number: e.target.value })} />
      </Field>
      <Field label="Issuing country">
        <input value={doc.issuing_country} onChange={(e) => onChange({ ...doc, issuing_country: e.target.value })} />
      </Field>
      <Field label="Expiry date">
        <input type="date" value={doc.expiry_date} onChange={(e) => onChange({ ...doc, expiry_date: e.target.value })} />
      </Field>
    </div>
  );
}

// --- Guest picker -------------------------------------------------------------

export interface NewGuest { first_name: string; last_name: string; email: string; phone_number: string; company_name: string }
export const emptyGuest = (): NewGuest => ({ first_name: '', last_name: '', email: '', phone_number: '', company_name: '' });

/** Search for a returning guest, or fill in a new one. */
export function GuestPicker({ existing, onPick, guest, onGuestChange, error }: {
  existing: Guest | null; onPick: (guest: Guest | null) => void;
  guest: NewGuest; onGuestChange: (guest: NewGuest) => void; error?: unknown;
}) {
  const [search, setSearch] = useState('');
  const matches = useQuery({
    queryKey: ['guests', search],
    queryFn: () => api<Paginated<Guest>>('guests/', { query: { q: search } }),
    enabled: search.length >= 2 && !existing,
  });

  if (existing) {
    return (
      <div className="row">
        <div>
          <strong>{existing.first_name} {existing.last_name}</strong>
          {existing.is_vip && <span className="badge warn" style={{ marginLeft: 6 }}>VIP</span>}
          <div className="muted">{existing.email}{existing.has_valid_identification ? ' · ID on file' : ''}</div>
        </div>
        <span className="spacer" />
        <button type="button" onClick={() => onPick(null)}>Change</button>
      </div>
    );
  }
  return (
    <div className="stack" style={{ gap: 10 }}>
      <Field label="Find a returning guest" hint="Name, email or phone">
        <input value={search} onChange={(e) => setSearch(e.target.value)} />
      </Field>
      {matches.data?.results.map((g) => (
        <button type="button" key={g.id} onClick={() => onPick(g)} style={{ justifyContent: 'space-between' }}>
          <span>{g.first_name} {g.last_name}</span><span className="muted">{g.email}</span>
        </button>
      ))}
      {matches.data && !matches.data.results.length && <div className="muted">No match: enter the guest below.</div>}
      <div className="muted">…or enter a new guest:</div>
      <div className="form-grid">
        <Field label="First name" error={fieldError(error, 'guest')}>
          <input required value={guest.first_name} onChange={(e) => onGuestChange({ ...guest, first_name: e.target.value })} />
        </Field>
        <Field label="Last name"><input required value={guest.last_name} onChange={(e) => onGuestChange({ ...guest, last_name: e.target.value })} /></Field>
        <Field label="Email"><input type="email" required value={guest.email} onChange={(e) => onGuestChange({ ...guest, email: e.target.value })} /></Field>
        <Field label="Phone"><input value={guest.phone_number} onChange={(e) => onGuestChange({ ...guest, phone_number: e.target.value })} /></Field>
        <Field label="Company"><input value={guest.company_name} onChange={(e) => onGuestChange({ ...guest, company_name: e.target.value })} /></Field>
      </div>
    </div>
  );
}

// --- Check-in / check-out -------------------------------------------------------

interface ActionDialogProps { reservation: Reservation; onClose: () => void; onDone?: (r: Reservation) => void }

export function CheckInDialog({ reservation, onClose, onDone }: ActionDialogProps) {
  const act = useReservationAction(reservation.id, (r) => { onDone?.(r); onClose(); });
  const needsId = !reservation.guest.has_valid_identification;
  const [doc, setDoc] = useState(emptyIdDocument());

  function submit(event: FormEvent) {
    event.preventDefault();
    act.mutate({ action: 'check-in', body: needsId || doc.document_number ? { identification: idPayload(doc) } : {} });
  }
  return (
    <Modal title={`Check in ${reservation.guest.first_name} ${reservation.guest.last_name}`} onClose={onClose}>
      <form onSubmit={submit} className="stack">
        <ErrorAlert error={act.error} />
        <p className="muted" style={{ margin: 0 }}>Room {reservation.room_number} until {formatDate(reservation.check_out_date)}.</p>
        {needsId ? <strong>Record the guest's ID document</strong> : <span className="muted">A valid ID is on file. You can add another.</span>}
        <IdFields doc={doc} onChange={setDoc} required={needsId} />
        <div className="actions">
          <button type="button" onClick={onClose}>Cancel</button>
          <button className="primary" disabled={act.isPending}>Check in</button>
        </div>
      </form>
    </Modal>
  );
}

export function CheckOutDialog({ reservation, onClose, onDone }: ActionDialogProps) {
  const { can } = useAuth();
  const act = useReservationAction(reservation.id, (r) => { onDone?.(r); onClose(); });
  // Post tonight's room charge first so the balance shown is what the guest actually owes
  const bill = useQuery({
    queryKey: ['checkout-bill', reservation.id],
    queryFn: () => post<Reservation>(`reservations/${reservation.id}/post-room-charges/`),
    staleTime: 0,
    refetchOnWindowFocus: false,
  });
  const accounts = useQuery({
    queryKey: ['accounts'],
    queryFn: () => api<Paginated<{ id: number; name: string }>>('billing/accounts/'),
  });
  const folio = bill.data?.folio ?? reservation.folio;
  const balance = Number(folio?.balance ?? 0);
  const [settle, setSettle] = useState<'pay' | 'company'>(reservation.guest.company_name ? 'company' : 'pay');
  const [account, setAccount] = useState('');
  const [method, setMethod] = useState('CARD_TERMINAL');
  const [reference, setReference] = useState('');

  const pay = useMutation({
    mutationFn: () => post(`billing/folios/${folio!.id}/payments/`, { method, amount: balance.toFixed(2), reference }),
  });

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (balance > 0 && settle === 'pay') {
      await pay.mutateAsync();
      act.mutate({ action: 'check-out', body: {} });
    } else {
      act.mutate({ action: 'check-out', body: balance > 0 && account ? { transfer_to_account: Number(account) } : {} });
    }
  }

  return (
    <Modal title={`Check out ${reservation.guest.first_name} ${reservation.guest.last_name}`} onClose={onClose}>
      <form className="stack" onSubmit={(e) => void submit(e)}>
        <ErrorAlert error={pay.error ?? act.error ?? bill.error} />
        <p style={{ margin: 0 }}>
          Balance to settle: <strong>{bill.isLoading ? '…' : formatMoney(folio?.balance ?? 0)}</strong>
          {folio && <> · <Link to={`/folios/${folio.id}`}>Open folio {folio.number}</Link></>}
        </p>
        {balance > 0 && (
          <>
            <div className="row">
              <label className="checkbox"><input type="radio" name="settle" checked={settle === 'pay'} onChange={() => setSettle('pay')}
                                                 disabled={!can('payments.take')} /> Guest pays now</label>
              <label className="checkbox"><input type="radio" name="settle" checked={settle === 'company'} onChange={() => setSettle('company')} /> Bill to a company</label>
            </div>
            {settle === 'pay' ? (
              <div className="form-grid">
                <Field label="Method">
                  <select value={method} onChange={(e) => setMethod(e.target.value)}>
                    <option value="CARD_TERMINAL">Card (POS terminal)</option><option value="BANK_TRANSFER">Bank transfer</option><option value="CASH">Cash</option>
                  </select>
                </Field>
                <Field label="Reference" hint={method === 'CASH' ? 'Optional' : 'Terminal RRN or transfer ID'} error={fieldError(pay.error, 'reference')}>
                  <input required={method !== 'CASH'} value={reference} onChange={(e) => setReference(e.target.value)} />
                </Field>
              </div>
            ) : (
              <Field label="Company account" hint="The balance moves to the company's city-ledger account">
                <select required value={account} onChange={(e) => setAccount(e.target.value)}>
                  <option value="">Select a company</option>
                  {accounts.data?.results.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                </select>
              </Field>
            )}
          </>
        )}
        {balance < 0 && <p className="muted" style={{ margin: 0 }}>The guest is in credit: refund the difference on the folio before checking out.</p>}
        <div className="actions">
          <button type="button" onClick={onClose}>Cancel</button>
          <button className="primary" disabled={act.isPending || pay.isPending || bill.isLoading || balance < 0}>
            {balance > 0 && settle === 'pay' ? `Take ${formatMoney(balance)} and check out` : 'Check out'}</button>
        </div>
      </form>
    </Modal>
  );
}

// --- Walk-in ------------------------------------------------------------------------

export interface RoomChoice { id: number; room_number: string; room_type: number }

/** Book and check in a guest who has just arrived, in one step. */
export function WalkInDialog({ room, onClose }: { room?: RoomChoice; onClose: () => void }) {
  const navigate = useNavigate();
  const refresh = useRefreshFrontDesk();
  const roomTypes = useQuery({ queryKey: ['room-types'], queryFn: () => api<RoomType[]>('rooms/types/') });
  const [existing, setExisting] = useState<Guest | null>(null);
  const [guest, setGuest] = useState(emptyGuest());
  const [roomType, setRoomType] = useState(room ? String(room.room_type) : '');
  const [checkOut, setCheckOut] = useState(addDays(todayISO(), 1));
  const [adults, setAdults] = useState(1);
  const [children, setChildren] = useState(0);
  const [doc, setDoc] = useState(emptyIdDocument());
  const needsId = !existing?.has_valid_identification;

  const create = useMutation({
    mutationFn: () => post<Reservation>('front-desk/walk-in/', {
      ...(existing ? { guest_id: existing.id } : { guest }),
      room: { room_type: Number(roomType), room: room?.id ?? null, number_of_adults: adults, number_of_children: children },
      check_out_date: checkOut,
      identification: needsId || doc.document_number ? idPayload(doc) : null,
    }),
    onSuccess: (booking) => { refresh(); onClose(); navigate(`/reservations/${booking.id}`); },
  });

  const type = roomTypes.data?.find((t) => String(t.id) === roomType);
  const nights = Math.max(1, Math.round((new Date(checkOut).getTime() - new Date(todayISO()).getTime()) / 86_400_000));

  return (
    <Modal title={room ? `Walk-in · Room ${room.room_number}` : 'Walk-in'} onClose={onClose}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
        <ErrorAlert error={create.error} />
        <GuestPicker existing={existing} onPick={setExisting} guest={guest} onGuestChange={setGuest} error={create.error} />
        <div className="form-grid">
          {!room && (
            <Field label="Room type">
              <select required value={roomType} onChange={(e) => setRoomType(e.target.value)}>
                <option value="">Select</option>
                {roomTypes.data?.map((t) => <option key={t.id} value={t.id}>{t.name} · {formatMoney(t.base_price)}</option>)}
              </select>
            </Field>
          )}
          <Field label="Departure" error={fieldError(create.error, 'check_out_date')}>
            <input type="date" required min={addDays(todayISO(), 1)} value={checkOut} onChange={(e) => setCheckOut(e.target.value)} />
          </Field>
          <Field label="Adults"><input type="number" min={1} max={type?.max_adults} value={adults} onChange={(e) => setAdults(Number(e.target.value))} /></Field>
          <Field label="Children"><input type="number" min={0} max={type?.max_children} value={children} onChange={(e) => setChildren(Number(e.target.value))} /></Field>
        </div>
        {type && <p className="muted" style={{ margin: 0 }}>{nights} night{nights === 1 ? '' : 's'} at about {formatMoney(Number(type.base_price) * nights)} before tax.</p>}
        {needsId ? <strong>Guest ID document</strong> : <span className="muted">A valid ID is on file.</span>}
        {needsId && <IdFields doc={doc} onChange={setDoc} required />}
        <div className="actions">
          <button type="button" onClick={onClose}>Cancel</button>
          <button className="primary" disabled={create.isPending}>Check in</button>
        </div>
      </form>
    </Modal>
  );
}

// --- Edit stay --------------------------------------------------------------------

/** Change dates, party size or requests; the server re-prices and re-checks availability. */
export function EditStayDialog({ reservation, onClose }: ActionDialogProps) {
  const refresh = useRefreshFrontDesk();
  const roomTypes = useQuery({ queryKey: ['room-types'], queryFn: () => api<RoomType[]>('rooms/types/') });
  const inHouse = reservation.status === 'CHECKED_IN';
  const [form, setForm] = useState({
    check_in_date: reservation.check_in_date, check_out_date: reservation.check_out_date,
    room_type: String(reservation.room_type), number_of_adults: reservation.number_of_adults,
    number_of_children: reservation.number_of_children, special_requests: reservation.special_requests ?? '',
  });

  const save = useMutation({
    mutationFn: () => {
      const changes: Record<string, unknown> = {};
      if (!inHouse && form.check_in_date !== reservation.check_in_date) changes.check_in_date = form.check_in_date;
      if (form.check_out_date !== reservation.check_out_date) changes.check_out_date = form.check_out_date;
      if (!inHouse && form.room_type !== String(reservation.room_type)) changes.room_type = Number(form.room_type);
      if (form.number_of_adults !== reservation.number_of_adults) changes.number_of_adults = form.number_of_adults;
      if (form.number_of_children !== reservation.number_of_children) changes.number_of_children = form.number_of_children;
      if (form.special_requests !== (reservation.special_requests ?? '')) changes.special_requests = form.special_requests;
      return patch<Reservation>(`reservations/${reservation.id}/`, changes);
    },
    onSuccess: () => { refresh(); onClose(); },
  });

  return (
    <Modal title="Change reservation" onClose={onClose}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        <ErrorAlert error={save.error} />
        {inHouse && <p className="muted" style={{ margin: 0 }}>The guest is in house: you can extend or shorten the stay and update the party. Use "Move room" to change rooms.</p>}
        <div className="form-grid">
          <Field label="Arrival" error={fieldError(save.error, 'check_in_date')}>
            <input type="date" disabled={inHouse} value={form.check_in_date} onChange={(e) => setForm({ ...form, check_in_date: e.target.value })} />
          </Field>
          <Field label="Departure" error={fieldError(save.error, 'check_out_date')}>
            <input type="date" min={addDays(form.check_in_date, 1)} value={form.check_out_date} onChange={(e) => setForm({ ...form, check_out_date: e.target.value })} />
          </Field>
          <Field label="Room type">
            <select disabled={inHouse} value={form.room_type} onChange={(e) => setForm({ ...form, room_type: e.target.value })}>
              {roomTypes.data?.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </Field>
          <Field label="Adults" error={fieldError(save.error, 'number_of_adults')}>
            <input type="number" min={1} value={form.number_of_adults} onChange={(e) => setForm({ ...form, number_of_adults: Number(e.target.value) })} />
          </Field>
          <Field label="Children" error={fieldError(save.error, 'number_of_children')}>
            <input type="number" min={0} value={form.number_of_children} onChange={(e) => setForm({ ...form, number_of_children: Number(e.target.value) })} />
          </Field>
        </div>
        <Field label="Special requests"><textarea value={form.special_requests} onChange={(e) => setForm({ ...form, special_requests: e.target.value })} /></Field>
        <div className="actions">
          <button type="button" onClick={onClose}>Cancel</button>
          <button className="primary" disabled={save.isPending}>Save changes</button>
        </div>
      </form>
    </Modal>
  );
}

// --- From a booking summary -------------------------------------------------------

/** Lists like the room board and night audit only carry a booking summary: load it, then check in or out. */
export function ReservationActionDialog({ bookingId, action, onClose }: {
  bookingId: number; action: 'check-in' | 'check-out'; onClose: () => void;
}) {
  const reservation = useQuery({
    queryKey: ['reservation', String(bookingId)],
    queryFn: () => api<Reservation>(`reservations/${bookingId}/`),
  });
  if (!reservation.data) {
    return <Modal title="Loading reservation" onClose={onClose}>{reservation.error ? <ErrorAlert error={reservation.error} /> : <Loading />}</Modal>;
  }
  return action === 'check-in'
    ? <CheckInDialog reservation={reservation.data} onClose={onClose} />
    : <CheckOutDialog reservation={reservation.data} onClose={onClose} />;
}
