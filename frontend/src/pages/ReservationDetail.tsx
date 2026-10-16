import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { api, post } from '../api/client';
import type { Reservation, Room } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { CheckInDialog, CheckOutDialog, EditStayDialog } from '../components/frontDesk';
import { ErrorAlert, Field, Loading, Modal, PageHeader, StatusBadge } from '../components/ui';
import { formatDate, formatDateTime, formatMoney, humanize } from '../lib/format';

type Dialog = 'check-in' | 'check-out' | 'cancel' | 'no-show' | 'move-room' | 'edit' | null;

export function ReservationDetail() {
  const { id } = useParams();
  const { can } = useAuth();
  const queryClient = useQueryClient();
  const [dialog, setDialog] = useState<Dialog>(null);
  const reservation = useQuery({ queryKey: ['reservation', id], queryFn: () => api<Reservation>(`reservations/${id}/`) });

  const act = useMutation({
    mutationFn: ({ action, body }: { action: string; body?: unknown }) => post<Reservation>(`reservations/${id}/${action}/`, body),
    onSuccess: (data) => {
      queryClient.setQueryData(['reservation', id], data);
      void queryClient.invalidateQueries({ queryKey: ['reservations'] });
      void queryClient.invalidateQueries({ queryKey: ['folio'] });
      setDialog(null);
    },
  });

  if (reservation.isLoading) return <Loading />;
  if (!reservation.data) return <ErrorAlert error={reservation.error} />;
  const r = reservation.data;
  const manage = can('bookings.manage');

  return (
    <div className="stack">
      <PageHeader
        title={`${r.guest.first_name} ${r.guest.last_name}`}
        subtitle={<>{r.confirmation_number} · <StatusBadge status={r.status} />{r.group_reference && <> · Group <Link to={`/groups/${r.group_reference}`}>{r.group_reference}</Link></>}</>}
        actions={manage && <>
          {r.status === 'CONFIRMED' && <button className="primary" onClick={() => setDialog('check-in')}>Check in</button>}
          {r.status === 'CHECKED_IN' && <>
            <button onClick={() => act.mutate({ action: 'post-room-charges' })}>Update bill</button>
            <button className="primary" onClick={() => setDialog('check-out')}>Check out</button>
          </>}
          {['PENDING', 'CONFIRMED', 'CHECKED_IN'].includes(r.status) && <>
            <button onClick={() => setDialog('edit')}>Change</button>
            <button onClick={() => setDialog('move-room')}>Move room</button>
          </>}
          {r.status === 'CONFIRMED' && <button onClick={() => setDialog('no-show')}>No-show</button>}
          {['PENDING', 'CONFIRMED'].includes(r.status) && <button className="danger" onClick={() => setDialog('cancel')}>Cancel</button>}
        </>}
      />
      {!dialog && <ErrorAlert error={act.error} />}
      <div className="grid cols-2">
        <div className="card">
          <h2>Stay</h2>
          <dl className="details">
            <dt>Room</dt><dd>{r.room_number} · {r.room_type_name}</dd>
            <dt>Arrival</dt><dd>{formatDate(r.check_in_date)}</dd>
            <dt>Departure</dt><dd>{formatDate(r.check_out_date)} ({r.nights} night{r.nights === 1 ? '' : 's'})</dd>
            <dt>Guests</dt><dd>{r.number_of_adults} adult(s), {r.number_of_children} child(ren)</dd>
            <dt>Source</dt><dd>{humanize(r.source)}{r.created_by && ` · by ${r.created_by}`}</dd>
            <dt>Requests</dt><dd>{r.special_requests || '—'}</dd>
            {r.cancellation_reason && <><dt>Reason</dt><dd>{r.cancellation_reason}</dd></>}
          </dl>
        </div>
        <div className="card">
          <h2>Charges</h2>
          <dl className="details">
            <dt>Avg. rate</dt><dd>{formatMoney(r.price_per_night)} / night</dd>
            <dt>Room total</dt><dd>{formatMoney(r.total_price)}</dd>
            <dt>Taxes</dt><dd>{formatMoney(r.taxes)}</dd>
            <dt>Total</dt><dd><strong>{formatMoney(r.total_with_taxes)}</strong></dd>
            {Number(r.penalty_amount) > 0 && <><dt>Penalty</dt><dd>{formatMoney(r.penalty_amount)}</dd></>}
            {r.penalty_waived && <><dt>Penalty</dt><dd>Waived</dd></>}
            <dt>Folio</dt>
            <dd>{r.folio ? <><Link to={`/folios/${r.folio.id}`}>{r.folio.number}</Link> · balance {formatMoney(r.folio.balance)}</> : 'Not opened yet'}</dd>
          </dl>
          {r.cancellation_fee_if_cancelled_now !== null && <p className="muted" style={{ marginBottom: 0 }}>{r.cancellation_policy}</p>}
        </div>
        <div className="card">
          <h2>Guest</h2>
          <dl className="details">
            <dt>Email</dt><dd>{r.guest.email}</dd>
            <dt>Phone</dt><dd>{r.guest.phone_number || '—'}</dd>
            <dt>Company</dt><dd>{r.guest.company_name || '—'}</dd>
            <dt>ID on file</dt><dd>{r.guest.has_valid_identification ? 'Yes' : <span className="badge warn">Needed at check-in</span>}</dd>
            <dt>Notes</dt><dd>{r.guest.notes || '—'}</dd>
          </dl>
          <Link to={`/guests/${r.guest.id}`}>Guest profile</Link>
        </div>
        {r.status === 'CHECKED_IN' && <KeyCards bookingId={r.id} canManage={manage} />}
        <div className="card muted">Booked {formatDateTime(r.created_at)}</div>
      </div>

      {dialog === 'check-in' && <CheckInDialog reservation={r} onClose={() => setDialog(null)} />}
      {dialog === 'check-out' && <CheckOutDialog reservation={r} onClose={() => setDialog(null)} />}
      {dialog === 'edit' && <EditStayDialog reservation={r} onClose={() => setDialog(null)} />}
      {(dialog === 'cancel' || dialog === 'no-show') && (
        <PenaltyDialog reservation={r} action={dialog} canWaive={can('folios.adjust') || can('bookings.manage')}
                       busy={act.isPending} error={act.error} onClose={() => setDialog(null)}
                       onSubmit={(body) => act.mutate({ action: dialog, body })} />
      )}
      {dialog === 'move-room' && <MoveRoomDialog reservation={r} busy={act.isPending} error={act.error}
                                                 onClose={() => setDialog(null)} onSubmit={(body) => act.mutate({ action: 'move-room', body })} />}
    </div>
  );
}

function KeyCards({ bookingId, canManage }: { bookingId: number; canManage: boolean }) {
  const queryClient = useQueryClient();
  const keys = useQuery({
    queryKey: ['keys', bookingId],
    queryFn: () => api<{ id: number; room_number: string; status: string; valid_until: string }[]>(`locks/bookings/${bookingId}/keys/`),
  });
  const run = useMutation({
    mutationFn: (path: string) => post(path, { cards: 1, reason: 'Lost card' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['keys', bookingId] }),
  });
  const active = keys.data?.filter((k) => k.status === 'ACTIVE') ?? [];
  return (
    <div className="card">
      <h2>Room keys</h2>
      <ErrorAlert error={run.error} />
      <p style={{ marginTop: 0 }}>{active.length ? `${active.length} active card(s), valid until ${formatDateTime(active[0].valid_until)}` : 'No active key cards.'}</p>
      {canManage && <div className="row">
        <button onClick={() => run.mutate(`locks/bookings/${bookingId}/keys/`)} disabled={run.isPending}>Encode a card</button>
        {active.length > 0 && <button className="danger" onClick={() => run.mutate(`locks/bookings/${bookingId}/keys/revoke/`)}>Revoke all (lost card)</button>}
      </div>}
    </div>
  );
}

interface DialogProps {
  reservation: Reservation;
  busy: boolean;
  error: unknown;
  onClose: () => void;
  onSubmit: (body: unknown) => void;
}

function PenaltyDialog({ reservation, action, canWaive, busy, error, onClose, onSubmit }:
  DialogProps & { action: 'cancel' | 'no-show'; canWaive: boolean }) {
  const [reason, setReason] = useState('');
  const [waive, setWaive] = useState(false);
  const fee = action === 'cancel' ? reservation.cancellation_fee_if_cancelled_now : reservation.price_per_night;
  return (
    <Modal title={action === 'cancel' ? 'Cancel reservation' : 'Mark as no-show'} onClose={onClose}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); onSubmit({ reason, waive_penalty: waive }); }}>
        <ErrorAlert error={error} />
        <p style={{ margin: 0 }}>Policy charge: <strong>{formatMoney(fee)}</strong></p>
        <Field label="Reason"><textarea value={reason} onChange={(e) => setReason(e.target.value)} required={waive} /></Field>
        {canWaive && Number(fee) > 0 && (
          <label className="checkbox"><input type="checkbox" checked={waive} onChange={(e) => setWaive(e.target.checked)} />
            Waive the charge (reason required, recorded in the audit log)</label>
        )}
        <div className="actions">
          <button type="button" onClick={onClose}>Back</button>
          <button className="danger" disabled={busy}>{action === 'cancel' ? 'Cancel reservation' : 'Mark no-show'}</button>
        </div>
      </form>
    </Modal>
  );
}

function MoveRoomDialog({ reservation, busy, error, onClose, onSubmit }: DialogProps) {
  const rooms = useQuery({ queryKey: ['rooms'], queryFn: () => api<Room[]>('rooms/all/') });
  const [room, setRoom] = useState('');
  const [reason, setReason] = useState('');
  const [reprice, setReprice] = useState(false);
  return (
    <Modal title="Move to another room" onClose={onClose}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); onSubmit({ room: Number(room), reason, reprice }); }}>
        <ErrorAlert error={error} />
        <Field label="New room">
          <select required value={room} onChange={(e) => setRoom(e.target.value)}>
            <option value="">Select a room</option>
            {rooms.data?.filter((x) => x.id !== reservation.room).map((x) => (
              <option key={x.id} value={x.id}>{x.room_number} · {x.room_type_detail.name} ({humanize(x.status)})</option>
            ))}
          </select>
        </Field>
        <Field label="Reason"><input required value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
        <label className="checkbox"><input type="checkbox" checked={reprice} onChange={(e) => setReprice(e.target.checked)} />
          Charge the new room type's rate for the remaining nights</label>
        <div className="actions">
          <button type="button" onClick={onClose}>Cancel</button>
          <button className="primary" disabled={busy}>Move</button>
        </div>
      </form>
    </Modal>
  );
}
