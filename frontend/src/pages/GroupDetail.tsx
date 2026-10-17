import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { Link, useParams } from 'react-router-dom';

import { api, post } from '../api/client';
import type { BookingGroup, GroupActionResponse } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { emptyIdDocument, IdFields, idPayload, useRefreshFrontDesk } from '../components/frontDesk';
import { ErrorAlert, Field, Loading, Modal, PageHeader, StatusBadge } from '../components/ui';
import { formatDate, formatDateTime, formatMoney, todayISO } from '../lib/format';

type Dialog = 'check-in' | 'check-out' | 'cancel' | null;

/** A booking group: every room in it, with check-in, check-out and cancellation for the whole group. */
export function GroupDetail() {
  const { reference = '' } = useParams();
  const { can } = useAuth();
  const queryClient = useQueryClient();
  const refresh = useRefreshFrontDesk();
  const [dialog, setDialog] = useState<Dialog>(null);
  const [results, setResults] = useState<GroupActionResponse['results'] | null>(null);
  const group = useQuery({ queryKey: ['group', reference], queryFn: () => api<BookingGroup>(`groups/${reference}/`) });

  const act = useMutation({
    mutationFn: ({ action, body }: { action: string; body?: unknown }) =>
      post<GroupActionResponse>(`groups/${reference}/${action}/`, body),
    onSuccess: (data) => {
      queryClient.setQueryData(['group', reference], data.group);
      refresh();
      setResults(data.results);
      setDialog(null);
    },
  });

  if (group.isLoading) return <Loading />;
  if (!group.data) return <ErrorAlert error={group.error} />;
  const g = group.data;
  const today = todayISO();
  const arriving = g.bookings.filter((b) => b.status === 'CONFIRMED' && b.check_in_date <= today && today < b.check_out_date);
  const inHouse = g.bookings.filter((b) => b.status === 'CHECKED_IN');
  const cancellable = g.bookings.filter((b) => b.status === 'PENDING' || b.status === 'CONFIRMED');
  const manage = can('bookings.manage');
  const failed = results?.filter((r) => !r.ok) ?? [];

  return (
    <div className="stack">
      <PageHeader
        title={`Group ${g.reference}`}
        subtitle={<>{g.booker.first_name} {g.booker.last_name} · {g.totals.rooms} room{g.totals.rooms === 1 ? '' : 's'} ·{' '}
          {g.totals.adults} adult(s), {g.totals.children} child(ren)</>}
        actions={manage && <>
          {arriving.length > 0 && <button className="primary" onClick={() => setDialog('check-in')}>Check in {arriving.length} room{arriving.length === 1 ? '' : 's'}</button>}
          {inHouse.length > 0 && <button className="primary" onClick={() => setDialog('check-out')}>Check out {inHouse.length} room{inHouse.length === 1 ? '' : 's'}</button>}
          {cancellable.length > 0 && <button className="danger" onClick={() => setDialog('cancel')}>Cancel group</button>}
        </>}
      />
      {!dialog && <ErrorAlert error={act.error} />}
      {results && (
        <div className={`alert ${failed.length ? 'error' : 'success'}`} role="status">
          {results.length - failed.length} of {results.length} room{results.length === 1 ? '' : 's'} done.
          {failed.length > 0 && <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
            {failed.map((r) => <li key={r.confirmation_number}>Room {r.room_number ?? '—'} ({r.confirmation_number}): {r.error}</li>)}
          </ul>}
        </div>
      )}

      <div className="card table-wrap">
        <table>
          <thead>
            <tr><th>Confirmation</th><th>Room</th><th>Guests</th><th>Arrival</th><th>Departure</th><th>Status</th>
              <th className="num">Total</th><th className="num">Balance</th></tr>
          </thead>
          <tbody>
            {g.bookings.map((b) => (
              <tr key={b.id}>
                <td><Link to={`/reservations/${b.id}`}>{b.confirmation_number}</Link></td>
                <td>{b.room_number} <span className="muted">{b.room_type_name}</span></td>
                <td>{b.number_of_adults} + {b.number_of_children}</td>
                <td>{formatDate(b.check_in_date)}</td>
                <td>{formatDate(b.check_out_date)}</td>
                <td><StatusBadge status={b.status} /></td>
                <td className="num">{formatMoney(b.total_with_taxes)}</td>
                <td className="num">{b.folio ? <Link to={`/folios/${b.folio.id}`}>{formatMoney(b.folio.balance)}</Link> : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid cols-2">
        <div className="card">
          <h2>Booker</h2>
          <dl className="details">
            <dt>Name</dt><dd><Link to={`/guests/${g.booker.id}`}>{g.booker.first_name} {g.booker.last_name}</Link></dd>
            <dt>Email</dt><dd>{g.booker.email}</dd>
            <dt>Phone</dt><dd>{g.booker.phone_number || '—'}</dd>
            <dt>ID on file</dt><dd>{g.booker.has_valid_identification ? 'Yes' : <span className="badge warn">Needed at check-in</span>}</dd>
          </dl>
        </div>
        <div className="card">
          <h2>Group</h2>
          <dl className="details">
            <dt>Rooms total</dt><dd>{formatMoney(g.totals.total_price)} <span className="muted">before taxes</span></dd>
            <dt>Balance</dt><dd><strong>{formatMoney(g.totals.balance)}</strong></dd>
            <dt>Notes</dt><dd>{g.notes || '—'}</dd>
            <dt>Booked</dt><dd>{formatDateTime(g.created_at)}{g.created_by && ` · by ${g.created_by}`}</dd>
          </dl>
        </div>
      </div>

      {dialog === 'check-in' && (
        <GroupCheckInDialog group={g} rooms={arriving.length} busy={act.isPending} error={act.error}
                            onClose={() => setDialog(null)} onSubmit={(body) => act.mutate({ action: 'check-in', body })} />
      )}
      {dialog === 'check-out' && (
        <Modal title={`Check out group ${g.reference}`} onClose={() => setDialog(null)}>
          <div className="stack">
            <ErrorAlert error={act.error} />
            <p style={{ margin: 0 }}>Checks out {inHouse.length} room{inHouse.length === 1 ? '' : 's'}. Rooms that still owe money stay
              checked in and are listed afterwards; settle them from their bills. The guest gets one thank-you email with every invoice.</p>
            <div className="actions">
              <button type="button" onClick={() => setDialog(null)}>Back</button>
              <button className="primary" disabled={act.isPending} onClick={() => act.mutate({ action: 'check-out' })}>Check out</button>
            </div>
          </div>
        </Modal>
      )}
      {dialog === 'cancel' && (
        <GroupCancelDialog group={g} canWaive={can('folios.adjust') || manage} busy={act.isPending} error={act.error}
                           onClose={() => setDialog(null)} onSubmit={(body) => act.mutate({ action: 'cancel', body })} />
      )}
    </div>
  );
}

interface DialogProps {
  group: BookingGroup;
  busy: boolean;
  error: unknown;
  onClose: () => void;
  onSubmit: (body: unknown) => void;
}

function GroupCheckInDialog({ group, rooms, busy, error, onClose, onSubmit }: DialogProps & { rooms: number }) {
  const needsId = !group.booker.has_valid_identification;
  const [doc, setDoc] = useState(emptyIdDocument());
  function submit(event: FormEvent) {
    event.preventDefault();
    onSubmit(needsId || doc.document_number ? { identification: idPayload(doc) } : {});
  }
  return (
    <Modal title={`Check in group ${group.reference}`} onClose={onClose}>
      <form onSubmit={submit} className="stack">
        <ErrorAlert error={error} />
        <p className="muted" style={{ margin: 0 }}>
          Checks in {rooms} room{rooms === 1 ? '' : 's'} arriving today. A room that isn't ready is skipped and listed afterwards.
        </p>
        {needsId ? <strong>Record the booker's ID document</strong> : <span className="muted">A valid ID is on file for the booker.</span>}
        <IdFields doc={doc} onChange={setDoc} required={needsId} />
        <div className="actions">
          <button type="button" onClick={onClose}>Back</button>
          <button className="primary" disabled={busy}>Check in</button>
        </div>
      </form>
    </Modal>
  );
}

function GroupCancelDialog({ group, canWaive, busy, error, onClose, onSubmit }: DialogProps & { canWaive: boolean }) {
  const [reason, setReason] = useState('');
  const [waive, setWaive] = useState(false);
  const rooms = group.bookings.filter((b) => b.status === 'PENDING' || b.status === 'CONFIRMED');
  const fee = rooms.reduce((sum, b) => sum + Number(b.cancellation_fee_if_cancelled_now ?? 0), 0);
  return (
    <Modal title={`Cancel group ${group.reference}`} onClose={onClose}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); onSubmit({ reason, waive_penalty: waive }); }}>
        <ErrorAlert error={error} />
        <p style={{ margin: 0 }}>Cancels {rooms.length} room{rooms.length === 1 ? '' : 's'}.{' '}
          {fee > 0 ? <>Cancellation fees under the policy: <strong>{formatMoney(fee)}</strong>.</> : 'No cancellation fee applies.'}{' '}
          Anything prepaid online beyond the fees goes back to the guest's card. The guest gets one email for the group.</p>
        <Field label="Reason">
          <input value={reason} onChange={(e) => setReason(e.target.value)} required={waive} />
        </Field>
        {canWaive && fee > 0 && (
          <label className="checkbox"><input type="checkbox" checked={waive} onChange={(e) => setWaive(e.target.checked)} /> Waive the fees (reason required)</label>
        )}
        <div className="actions">
          <button type="button" onClick={onClose}>Back</button>
          <button className="danger" disabled={busy}>Cancel group</button>
        </div>
      </form>
    </Modal>
  );
}
