/**
 * Hotel configuration for managers: rooms and room types, rate plans and
 * selling restrictions, outlet menus, taxes and exchange rates. Every change
 * is recorded in the audit log by the API.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { useSearchParams } from 'react-router-dom';

import { api, patch, post } from '../api/client';
import type { Capability, Paginated, Room } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { Empty, ErrorAlert, Field, fieldError, Loading, Modal, PageHeader, StatusBadge } from '../components/ui';
import { formatDate, formatDateTime, formatMoney, humanize, todayISO } from '../lib/format';

const TABS: { key: string; label: string; capability: Capability }[] = [
  { key: 'rooms', label: 'Rooms', capability: 'rooms.manage' },
  { key: 'rates', label: 'Rate plans', capability: 'rates.manage' },
  { key: 'restrictions', label: 'Restrictions', capability: 'rates.manage' },
  { key: 'menus', label: 'Menus', capability: 'pos.manage' },
  { key: 'taxes', label: 'Taxes & currency', capability: 'billing.configure' },
];

export function Settings() {
  const { can } = useAuth();
  const [params, setParams] = useSearchParams();
  const tabs = TABS.filter((t) => can(t.capability));
  const active = tabs.find((t) => t.key === params.get('tab')) ?? tabs[0];
  if (!active) return <Empty>You don't have access to any settings.</Empty>;
  return (
    <div className="stack">
      <PageHeader title="Settings" subtitle="Changes apply to new bookings and sales; past bills keep their prices." />
      <nav className="tabs" aria-label="Settings sections">
        {tabs.map((t) => (
          <button key={t.key} className={t.key === active.key ? 'active' : ''} aria-current={t.key === active.key}
                  onClick={() => setParams({ tab: t.key })}>{t.label}</button>
        ))}
      </nav>
      {active.key === 'rooms' && <RoomsSettings />}
      {active.key === 'rates' && <RatePlansSettings />}
      {active.key === 'restrictions' && <RestrictionsSettings />}
      {active.key === 'menus' && <MenuSettings />}
      {active.key === 'taxes' && <TaxSettings />}
    </div>
  );
}

/** Small helper: a mutation that refreshes the given query keys and closes its dialog. */
function useSave<T>(fn: (body: T) => Promise<unknown>, keys: string[], onDone?: () => void) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => { for (const k of keys) void queryClient.invalidateQueries({ queryKey: [k] }); onDone?.(); },
  });
}

function Section({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <div className="card table-wrap">
      <div className="row" style={{ marginBottom: 10 }}><h2 style={{ margin: 0 }}>{title}</h2><span className="spacer" />{action}</div>
      {children}
    </div>
  );
}

function DialogActions({ busy, onClose, label = 'Save' }: { busy: boolean; onClose: () => void; label?: string }) {
  return <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy}>{label}</button></div>;
}

// --- Rooms ----------------------------------------------------------------------

interface RoomTypeFull {
  id: number; name: string; description: string; base_price: string; max_adults: number; max_children: number;
  bed_type: string; bed_count: number; size: number; available_room_count: number;
}
const BED_TYPES = ['KING', 'QUEEN', 'DOUBLE', 'TWIN', 'SINGLE', 'SOFA_BED', 'FUTON', 'BUNK_BED'];

function RoomsSettings() {
  const types = useQuery({ queryKey: ['room-types'], queryFn: () => api<RoomTypeFull[]>('rooms/types/') });
  const rooms = useQuery({ queryKey: ['rooms'], queryFn: () => api<Room[]>('rooms/all/') });
  const [editType, setEditType] = useState<RoomTypeFull | 'new' | null>(null);
  const [editRoom, setEditRoom] = useState<Room | 'new' | null>(null);

  return (
    <>
      <Section title="Room types" action={<button onClick={() => setEditType('new')}>Add room type</button>}>
        <ErrorAlert error={types.error} />
        {!types.data ? <Loading /> : (
          <table>
            <thead><tr><th>Name</th><th className="num">Base rate</th><th>Sleeps</th><th>Beds</th><th>Size</th><th>Rooms</th><th /></tr></thead>
            <tbody>{types.data.map((t) => (
              <tr key={t.id}>
                <td><strong>{t.name}</strong><div className="muted" style={{ fontSize: 12, maxWidth: 380 }}>{t.description}</div></td>
                <td className="num">{formatMoney(t.base_price)}</td>
                <td>{t.max_adults} + {t.max_children}</td>
                <td>{t.bed_count} × {humanize(t.bed_type)}</td>
                <td>{t.size} sq ft</td>
                <td>{rooms.data?.filter((r) => r.room_type === t.id).length ?? '—'}</td>
                <td className="row-actions"><button className="small" onClick={() => setEditType(t)}>Edit</button></td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </Section>
      <Section title="Rooms" action={<button onClick={() => setEditRoom('new')}>Add room</button>}>
        {!rooms.data ? <Loading /> : (
          <table>
            <thead><tr><th>Room</th><th>Type</th><th>Floor</th><th>Status</th><th>Notes</th><th /></tr></thead>
            <tbody>{rooms.data.map((r) => (
              <tr key={r.id}>
                <td><strong>{r.room_number}</strong></td><td>{r.room_type_detail.name}</td><td>{r.floor_number}</td>
                <td><StatusBadge status={r.status} /></td><td className="muted">{(r as Room & { notes?: string }).notes || '—'}</td>
                <td className="row-actions"><button className="small" onClick={() => setEditRoom(r)}>Edit</button></td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </Section>
      {editType && <RoomTypeDialog type={editType === 'new' ? null : editType} onClose={() => setEditType(null)} />}
      {editRoom && <RoomDialog room={editRoom === 'new' ? null : editRoom} types={types.data ?? []} onClose={() => setEditRoom(null)} />}
    </>
  );
}

function RoomTypeDialog({ type, onClose }: { type: RoomTypeFull | null; onClose: () => void }) {
  const [form, setForm] = useState({
    name: type?.name ?? '', description: type?.description ?? '', base_price: type?.base_price ?? '',
    max_adults: type?.max_adults ?? 2, max_children: type?.max_children ?? 0, bed_type: type?.bed_type ?? 'KING',
    bed_count: type?.bed_count ?? 1, size: type?.size ?? 300,
  });
  const save = useSave(() => (type ? patch(`rooms/types/${type.id}/`, form) : post('rooms/create-room-type/', form)), ['room-types', 'rooms'], onClose);
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  return (
    <Modal title={type ? `Edit ${type.name}` : 'Add a room type'} onClose={onClose}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); save.mutate(undefined); }}>
        <ErrorAlert error={save.error} />
        <div className="form-grid">
          <Field label="Name" error={fieldError(save.error, 'name')}><input required value={form.name} onChange={set('name')} /></Field>
          <Field label="Base nightly rate (₦)" hint="The Best Available Rate; plans derive from it" error={fieldError(save.error, 'base_price')}>
            <input type="number" min="0" step="500" required value={form.base_price} onChange={set('base_price')} />
          </Field>
          <Field label="Max adults"><input type="number" min="1" required value={form.max_adults} onChange={set('max_adults')} /></Field>
          <Field label="Max children"><input type="number" min="0" required value={form.max_children} onChange={set('max_children')} /></Field>
          <Field label="Bed type">
            <select value={form.bed_type} onChange={set('bed_type')}>{BED_TYPES.map((b) => <option key={b} value={b}>{humanize(b)}</option>)}</select>
          </Field>
          <Field label="Beds"><input type="number" min="1" required value={form.bed_count} onChange={set('bed_count')} /></Field>
          <Field label="Size (sq ft)"><input type="number" min="1" required value={form.size} onChange={set('size')} /></Field>
        </div>
        <Field label="Description" hint="Shown on the website"><textarea required value={form.description} onChange={set('description')} /></Field>
        <DialogActions busy={save.isPending} onClose={onClose} />
      </form>
    </Modal>
  );
}

function RoomDialog({ room, types, onClose }: { room: Room | null; types: RoomTypeFull[]; onClose: () => void }) {
  const [form, setForm] = useState({
    room_number: room?.room_number ?? '', room_type: String(room?.room_type ?? types[0]?.id ?? ''),
    floor_number: room?.floor_number ?? 1, notes: (room as (Room & { notes?: string }) | null)?.notes ?? '',
    status: room?.status ?? 'AVAILABLE',
  });
  const lockedStatus = room && (room.status === 'OCCUPIED' || room.status === 'MAINTENANCE');
  const save = useSave(() => {
    const body = { room_type: Number(form.room_type), floor_number: Number(form.floor_number), notes: form.notes };
    return room
      ? patch(`rooms/all/${room.id}/`, lockedStatus ? body : { ...body, status: form.status })
      : post('rooms/create/', { ...body, room_number: form.room_number });
  }, ['rooms', 'room-types', 'room-board'], onClose);
  return (
    <Modal title={room ? `Room ${room.room_number}` : 'Add a room'} onClose={onClose}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); save.mutate(undefined); }}>
        <ErrorAlert error={save.error} />
        <div className="form-grid">
          {!room && <Field label="Room number" error={fieldError(save.error, 'room_number')}>
            <input required value={form.room_number} onChange={(e) => setForm({ ...form, room_number: e.target.value })} /></Field>}
          <Field label="Room type">
            <select value={form.room_type} onChange={(e) => setForm({ ...form, room_type: e.target.value })}>
              {types.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </Field>
          <Field label="Floor"><input type="number" min="0" required value={form.floor_number} onChange={(e) => setForm({ ...form, floor_number: Number(e.target.value) })} /></Field>
          {room && (
            <Field label="Availability" hint={lockedStatus ? 'Managed by check-in/out and maintenance tickets' : 'Out of service removes it from sale'} error={fieldError(save.error, 'status')}>
              <select disabled={!!lockedStatus} value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                {lockedStatus && <option value={room.status}>{humanize(room.status)}</option>}
                <option value="AVAILABLE">In service</option><option value="OUT_OF_SERVICE">Out of service</option>
              </select>
            </Field>
          )}
        </div>
        <Field label="Notes" hint="e.g. connecting door to 204, accessible bathroom"><textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></Field>
        <DialogActions busy={save.isPending} onClose={onClose} />
      </form>
    </Modal>
  );
}

// --- Rate plans ---------------------------------------------------------------

interface RatePlan {
  id: number; code: string; name: string; description: string; meal_plan: string; pricing: 'DERIVED' | 'FIXED';
  adjustment_percent: string; room_types: number[]; is_active: boolean; is_public: boolean; promo_code: string;
  corporate_account: number | null; min_stay: number; max_stay: number | null; min_advance_days: number;
  max_advance_days: number | null; sell_from: string | null; sell_until: string | null; is_refundable: boolean;
  free_cancellation_hours: number | null;
}
interface RatePrice { id: number; rate_plan: number; room_type: number; start_date: string; end_date: string; price: string }
const MEAL_PLANS = [['RO', 'Room only'], ['BB', 'Bed & breakfast'], ['HB', 'Half board'], ['FB', 'Full board'], ['AI', 'All inclusive']];

function RatePlansSettings() {
  const plans = useQuery({ queryKey: ['rate-plans'], queryFn: () => api<Paginated<RatePlan>>('rates/plans/') });
  const accounts = useQuery({ queryKey: ['accounts'], queryFn: () => api<Paginated<{ id: number; name: string }>>('billing/accounts/') });
  const [editing, setEditing] = useState<RatePlan | 'new' | null>(null);
  const accountName = (id: number | null) => accounts.data?.results.find((a) => a.id === id)?.name;

  return (
    <>
      <Section title="Rate plans" action={<button onClick={() => setEditing('new')}>Add rate plan</button>}>
        <ErrorAlert error={plans.error} />
        {!plans.data ? <Loading /> : (
          <table>
            <thead><tr><th>Plan</th><th>Price</th><th>Meals</th><th>Who can book</th><th>Conditions</th><th>Status</th><th /></tr></thead>
            <tbody>{plans.data.results.map((p) => (
              <tr key={p.id} className={p.is_active ? '' : 'void'}>
                <td><strong>{p.name}</strong><div className="muted" style={{ fontSize: 12 }}>{p.code}</div></td>
                <td>{p.code === 'BAR' ? 'Room type base rates' : p.pricing === 'FIXED' ? 'Own prices' : `${Number(p.adjustment_percent) > 0 ? '+' : ''}${Number(p.adjustment_percent)}% of BAR`}</td>
                <td>{MEAL_PLANS.find(([v]) => v === p.meal_plan)?.[1]}</td>
                <td>{p.corporate_account ? accountName(p.corporate_account) ?? 'One company'
                  : p.promo_code ? `Code ${p.promo_code}` : p.is_public ? 'Everyone (website too)' : 'Staff only'}</td>
                <td className="muted" style={{ fontSize: 13 }}>{[
                  p.min_stay > 1 && `${p.min_stay}+ nights`, p.min_advance_days > 0 && `book ${p.min_advance_days}+ days ahead`,
                  !p.is_refundable && 'non-refundable', p.sell_until && `until ${formatDate(p.sell_until)}`,
                ].filter(Boolean).join(' · ') || '—'}</td>
                <td>{p.is_active ? <span className="badge ok">Active</span> : <span className="badge">Inactive</span>}</td>
                <td className="row-actions">{p.code !== 'BAR' && <button className="small" onClick={() => setEditing(p)}>Edit</button>}</td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </Section>
      {editing && <RatePlanDialog plan={editing === 'new' ? null : editing} accounts={accounts.data?.results ?? []} onClose={() => setEditing(null)} />}
    </>
  );
}

function RatePlanDialog({ plan, accounts, onClose }: { plan: RatePlan | null; accounts: { id: number; name: string }[]; onClose: () => void }) {
  const types = useQuery({ queryKey: ['room-types'], queryFn: () => api<RoomTypeFull[]>('rooms/types/') });
  const [form, setForm] = useState({
    code: plan?.code ?? '', name: plan?.name ?? '', description: plan?.description ?? '', meal_plan: plan?.meal_plan ?? 'RO',
    pricing: plan?.pricing ?? 'DERIVED', adjustment_percent: plan?.adjustment_percent ?? '0', is_active: plan?.is_active ?? true,
    is_public: plan?.is_public ?? true, promo_code: plan?.promo_code ?? '', corporate_account: plan?.corporate_account ? String(plan.corporate_account) : '',
    min_stay: plan?.min_stay ?? 1, max_stay: plan?.max_stay ?? '', min_advance_days: plan?.min_advance_days ?? 0,
    sell_from: plan?.sell_from ?? '', sell_until: plan?.sell_until ?? '', is_refundable: plan?.is_refundable ?? true,
    room_types: plan?.room_types ?? [],
  });
  const save = useSave(() => {
    const body = {
      ...form, corporate_account: form.corporate_account ? Number(form.corporate_account) : null,
      max_stay: form.max_stay === '' ? null : Number(form.max_stay), sell_from: form.sell_from || null, sell_until: form.sell_until || null,
    };
    return plan ? patch(`rates/plans/${plan.id}/`, body) : post('rates/plans/', body);
  }, ['rate-plans'], onClose);
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  const check = (k: keyof typeof form) => (e: { target: { checked: boolean } }) => setForm({ ...form, [k]: e.target.checked });

  return (
    <Modal title={plan ? `Edit ${plan.name}` : 'Add a rate plan'} onClose={onClose}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); save.mutate(undefined); }}>
        <ErrorAlert error={save.error} />
        <div className="form-grid">
          <Field label="Name" error={fieldError(save.error, 'name')}><input required value={form.name} onChange={set('name')} /></Field>
          <Field label="Code" hint="Short id, e.g. BB, NRF" error={fieldError(save.error, 'code')}>
            <input required disabled={!!plan} value={form.code} onChange={set('code')} /></Field>
          <Field label="Meals">
            <select value={form.meal_plan} onChange={set('meal_plan')}>{MEAL_PLANS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
          </Field>
          <Field label="Pricing">
            <select value={form.pricing} onChange={set('pricing')}>
              <option value="DERIVED">Percentage of BAR</option><option value="FIXED">Own prices per room type</option>
            </select>
          </Field>
          {form.pricing === 'DERIVED' && (
            <Field label="Adjustment %" hint="-10 = 10% below BAR, 12 = 12% above" error={fieldError(save.error, 'adjustment_percent')}>
              <input type="number" step="0.5" min="-90" max="500" value={form.adjustment_percent} onChange={set('adjustment_percent')} />
            </Field>
          )}
          <Field label="Company (negotiated rate)">
            <select value={form.corporate_account} onChange={set('corporate_account')}>
              <option value="">— Any guest —</option>{accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          </Field>
          <Field label="Promo code" hint="Optional: guests must enter it" error={fieldError(save.error, 'promo_code')}>
            <input value={form.promo_code} onChange={set('promo_code')} /></Field>
          <Field label="Minimum nights"><input type="number" min="1" value={form.min_stay} onChange={set('min_stay')} /></Field>
          <Field label="Maximum nights" error={fieldError(save.error, 'max_stay')}><input type="number" min="1" value={form.max_stay} onChange={set('max_stay')} /></Field>
          <Field label="Book at least … days ahead"><input type="number" min="0" value={form.min_advance_days} onChange={set('min_advance_days')} /></Field>
          <Field label="On sale from"><input type="date" value={form.sell_from} onChange={set('sell_from')} /></Field>
          <Field label="On sale until"><input type="date" value={form.sell_until} onChange={set('sell_until')} /></Field>
        </div>
        <Field label="Room types" hint="None ticked = all room types">
          <div className="row">{types.data?.map((t) => (
            <label key={t.id} className="checkbox"><input type="checkbox" checked={form.room_types.includes(t.id)}
              onChange={(e) => setForm({ ...form, room_types: e.target.checked ? [...form.room_types, t.id] : form.room_types.filter((x) => x !== t.id) })} />{t.name}</label>
          ))}</div>
        </Field>
        <Field label="Description" hint="Shown to guests when they choose a rate"><textarea value={form.description} onChange={set('description')} /></Field>
        <div className="row">
          <label className="checkbox"><input type="checkbox" checked={form.is_refundable} onChange={check('is_refundable')} /> Refundable</label>
          <label className="checkbox"><input type="checkbox" checked={form.is_public} onChange={check('is_public')} /> Bookable on the website</label>
          <label className="checkbox"><input type="checkbox" checked={form.is_active} onChange={check('is_active')} /> Active</label>
        </div>
        {plan && form.pricing === 'FIXED' && <FixedPrices plan={plan} types={types.data ?? []} />}
        <DialogActions busy={save.isPending} onClose={onClose} />
      </form>
    </Modal>
  );
}

function FixedPrices({ plan, types }: { plan: RatePlan; types: RoomTypeFull[] }) {
  const prices = useQuery({ queryKey: ['rate-prices', plan.id], queryFn: () => api<Paginated<RatePrice>>('rates/prices/') });
  const [row, setRow] = useState({ room_type: String(types[0]?.id ?? ''), start_date: todayISO(), end_date: todayISO(), price: '' });
  const add = useSave(() => post('rates/prices/', { ...row, rate_plan: plan.id, room_type: Number(row.room_type) }), ['rate-prices']);
  const mine = prices.data?.results.filter((p) => p.rate_plan === plan.id) ?? [];
  return (
    <div className="stack" style={{ gap: 8 }}>
      <strong>Prices</strong>
      {mine.length ? (
        <table><tbody>{mine.map((p) => (
          <tr key={p.id}><td>{types.find((t) => t.id === p.room_type)?.name}</td><td>{formatDate(p.start_date)} – {formatDate(p.end_date)}</td>
            <td className="num">{formatMoney(p.price)}</td></tr>
        ))}</tbody></table>
      ) : <span className="muted">No prices yet: the plan can't be booked until it has some.</span>}
      <ErrorAlert error={add.error} />
      <div className="form-grid">
        <Field label="Room type"><select value={row.room_type} onChange={(e) => setRow({ ...row, room_type: e.target.value })}>
          {types.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select></Field>
        <Field label="From"><input type="date" value={row.start_date} onChange={(e) => setRow({ ...row, start_date: e.target.value })} /></Field>
        <Field label="To (inclusive)"><input type="date" value={row.end_date} onChange={(e) => setRow({ ...row, end_date: e.target.value })} /></Field>
        <Field label="Nightly price (₦)"><input type="number" min="0" value={row.price} onChange={(e) => setRow({ ...row, price: e.target.value })} /></Field>
      </div>
      <div><button type="button" disabled={!row.price || add.isPending} onClick={() => add.mutate(undefined)}>Add price</button></div>
    </div>
  );
}

// --- Restrictions ----------------------------------------------------------------

interface Restriction {
  id: number; rate_plan: number | null; room_type: number | null; start_date: string; end_date: string;
  stop_sell: boolean; closed_to_arrival: boolean; closed_to_departure: boolean; min_stay: number | null; note: string;
}

function RestrictionsSettings() {
  const restrictions = useQuery({ queryKey: ['restrictions'], queryFn: () => api<Paginated<Restriction>>('rates/restrictions/') });
  const plans = useQuery({ queryKey: ['rate-plans'], queryFn: () => api<Paginated<RatePlan>>('rates/plans/') });
  const types = useQuery({ queryKey: ['room-types'], queryFn: () => api<RoomTypeFull[]>('rooms/types/') });
  const [adding, setAdding] = useState(false);
  const remove = useSave((id: number) => api(`rates/restrictions/${id}/`, { method: 'DELETE' }), ['restrictions']);
  const upcoming = restrictions.data?.results.filter((r) => r.end_date >= todayISO()) ?? [];

  return (
    <>
      <Section title="Selling restrictions" action={<button onClick={() => setAdding(true)}>Add restriction</button>}>
        <p className="muted" style={{ marginTop: 0 }}>Apply to website and channel bookings. Staff can still book, and see why the rule applies.</p>
        <ErrorAlert error={restrictions.error ?? remove.error} />
        {!restrictions.data ? <Loading /> : !upcoming.length ? <div className="muted">No current or upcoming restrictions.</div> : (
          <table>
            <thead><tr><th>Dates</th><th>Applies to</th><th>Rule</th><th>Note</th><th /></tr></thead>
            <tbody>{upcoming.map((r) => (
              <tr key={r.id}>
                <td>{formatDate(r.start_date)} – {formatDate(r.end_date)}</td>
                <td>{[types.data?.find((t) => t.id === r.room_type)?.name ?? 'All rooms', plans.data?.results.find((p) => p.id === r.rate_plan)?.name ?? 'all rates'].join(' · ')}</td>
                <td>{[r.stop_sell && 'Stop sell', r.closed_to_arrival && 'No arrivals', r.closed_to_departure && 'No departures',
                  r.min_stay && `Min ${r.min_stay} nights`].filter(Boolean).join(', ')}</td>
                <td className="muted">{r.note || '—'}</td>
                <td className="row-actions"><button className="small danger" onClick={() => remove.mutate(r.id)}>Remove</button></td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </Section>
      {adding && <RestrictionDialog plans={plans.data?.results ?? []} types={types.data ?? []} onClose={() => setAdding(false)} />}
    </>
  );
}

function RestrictionDialog({ plans, types, onClose }: { plans: RatePlan[]; types: RoomTypeFull[]; onClose: () => void }) {
  const [form, setForm] = useState({ start_date: todayISO(), end_date: todayISO(), rate_plan: '', room_type: '', stop_sell: false,
    closed_to_arrival: false, closed_to_departure: false, min_stay: '', note: '' });
  const save = useSave(() => post('rates/restrictions/', {
    ...form, rate_plan: form.rate_plan ? Number(form.rate_plan) : null, room_type: form.room_type ? Number(form.room_type) : null,
    min_stay: form.min_stay ? Number(form.min_stay) : null,
  }), ['restrictions'], onClose);
  return (
    <Modal title="Add a selling restriction" onClose={onClose}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); save.mutate(undefined); }}>
        <ErrorAlert error={save.error} />
        <div className="form-grid">
          <Field label="From"><input type="date" required value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} /></Field>
          <Field label="To (inclusive)" error={fieldError(save.error, 'end_date')}><input type="date" required value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} /></Field>
          <Field label="Room type"><select value={form.room_type} onChange={(e) => setForm({ ...form, room_type: e.target.value })}>
            <option value="">All room types</option>{types.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select></Field>
          <Field label="Rate plan"><select value={form.rate_plan} onChange={(e) => setForm({ ...form, rate_plan: e.target.value })}>
            <option value="">All rate plans</option>{plans.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>
          <Field label="Minimum nights for arrivals"><input type="number" min="1" value={form.min_stay} onChange={(e) => setForm({ ...form, min_stay: e.target.value })} /></Field>
        </div>
        <div className="row">
          <label className="checkbox"><input type="checkbox" checked={form.stop_sell} onChange={(e) => setForm({ ...form, stop_sell: e.target.checked })} /> Stop sell</label>
          <label className="checkbox"><input type="checkbox" checked={form.closed_to_arrival} onChange={(e) => setForm({ ...form, closed_to_arrival: e.target.checked })} /> Closed to arrival</label>
          <label className="checkbox"><input type="checkbox" checked={form.closed_to_departure} onChange={(e) => setForm({ ...form, closed_to_departure: e.target.checked })} /> Closed to departure</label>
        </div>
        <Field label="Note" hint="e.g. Detty December: minimum 3 nights"><input value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} /></Field>
        <DialogActions busy={save.isPending} onClose={onClose} label="Add" />
      </form>
    </Modal>
  );
}

// --- Menus ---------------------------------------------------------------------------

interface Outlet { id: number; name: string }
interface Product {
  id: number; outlet: number; name: string; section: string; price: string; charge_category: string; is_available: boolean;
  track_stock: boolean; stock_quantity: number; low_stock_threshold: number; is_low_on_stock: boolean;
}
const SELL_CATEGORIES = ['FOOD', 'BEVERAGE', 'MINIBAR', 'LAUNDRY', 'SPA', 'TRANSPORT', 'TELEPHONE', 'MISC'];

function MenuSettings() {
  const outlets = useQuery({ queryKey: ['pos-outlets'], queryFn: () => api<Outlet[]>('pos/outlets/') });
  const [outlet, setOutlet] = useState('');
  const outletId = outlet || String(outlets.data?.[0]?.id ?? '');
  const products = useQuery({
    queryKey: ['pos-products', Number(outletId)], queryFn: () => api<Product[]>('pos/products/', { query: { outlet: outletId } }), enabled: !!outletId,
  });
  const [editing, setEditing] = useState<Product | 'new' | null>(null);
  const toggle = useSave((p: Product) => patch(`pos/products/${p.id}/`, { is_available: !p.is_available }), ['pos-products']);

  return (
    <>
      <Section title="Menu items" action={<>
        <select value={outletId} onChange={(e) => setOutlet(e.target.value)} aria-label="Outlet" style={{ width: 'auto' }}>
          {outlets.data?.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
        </select>
        <button onClick={() => setEditing('new')} disabled={!outletId}>Add item</button>
      </>}>
        <ErrorAlert error={products.error ?? toggle.error} />
        {!products.data ? <Loading /> : !products.data.length ? <div className="muted">No items on this menu yet.</div> : (
          <table>
            <thead><tr><th>Item</th><th>Section</th><th>Category</th><th className="num">Price</th><th>Stock</th><th>On sale</th><th /></tr></thead>
            <tbody>{products.data.map((p) => (
              <tr key={p.id} className={p.is_available ? '' : 'void'}>
                <td>{p.name}</td><td>{p.section || '—'}</td><td>{humanize(p.charge_category)}</td>
                <td className="num">{formatMoney(p.price)}</td>
                <td>{p.track_stock ? <span style={{ color: p.is_low_on_stock ? 'var(--danger)' : undefined }}>{p.stock_quantity}{p.is_low_on_stock && ' (low)'}</span> : '—'}</td>
                <td><label className="checkbox"><input type="checkbox" checked={p.is_available} onChange={() => toggle.mutate(p)} aria-label={`${p.name} on sale`} /></label></td>
                <td className="row-actions"><button className="small" onClick={() => setEditing(p)}>Edit</button></td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </Section>
      {editing && <ProductDialog product={editing === 'new' ? null : editing} outletId={Number(outletId)} onClose={() => setEditing(null)} />}
    </>
  );
}

function ProductDialog({ product, outletId, onClose }: { product: Product | null; outletId: number; onClose: () => void }) {
  const [form, setForm] = useState({
    name: product?.name ?? '', section: product?.section ?? '', price: product?.price ?? '', charge_category: product?.charge_category ?? 'FOOD',
    is_available: product?.is_available ?? true, track_stock: product?.track_stock ?? false,
    stock_quantity: product?.stock_quantity ?? 0, low_stock_threshold: product?.low_stock_threshold ?? 0,
  });
  const save = useSave(() => (product ? patch(`pos/products/${product.id}/`, form) : post('pos/products/', { ...form, outlet: outletId })), ['pos-products'], onClose);
  return (
    <Modal title={product ? `Edit ${product.name}` : 'Add a menu item'} onClose={onClose}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); save.mutate(undefined); }}>
        <ErrorAlert error={save.error} />
        <div className="form-grid">
          <Field label="Name" error={fieldError(save.error, 'name') ?? fieldError(save.error, 'non_field_errors')}>
            <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label="Menu section" hint="e.g. Mains, Cocktails"><input value={form.section} onChange={(e) => setForm({ ...form, section: e.target.value })} /></Field>
          <Field label="Price (₦, before tax)" error={fieldError(save.error, 'price')}>
            <input type="number" min="0" step="50" required value={form.price} onChange={(e) => setForm({ ...form, price: e.target.value })} /></Field>
          <Field label="Category" hint="Decides which taxes apply">
            <select value={form.charge_category} onChange={(e) => setForm({ ...form, charge_category: e.target.value })}>
              {SELL_CATEGORIES.map((c) => <option key={c} value={c}>{humanize(c)}</option>)}</select></Field>
        </div>
        <label className="checkbox"><input type="checkbox" checked={form.track_stock} onChange={(e) => setForm({ ...form, track_stock: e.target.checked })} /> Track stock</label>
        {form.track_stock && (
          <div className="form-grid">
            <Field label="In stock"><input type="number" value={form.stock_quantity} onChange={(e) => setForm({ ...form, stock_quantity: Number(e.target.value) })} /></Field>
            <Field label="Warn when at or below"><input type="number" min="0" value={form.low_stock_threshold} onChange={(e) => setForm({ ...form, low_stock_threshold: Number(e.target.value) })} /></Field>
          </div>
        )}
        <label className="checkbox"><input type="checkbox" checked={form.is_available} onChange={(e) => setForm({ ...form, is_available: e.target.checked })} /> On sale</label>
        <DialogActions busy={save.isPending} onClose={onClose} />
      </form>
    </Modal>
  );
}

// --- Taxes & currency ---------------------------------------------------------------

interface TaxRule { id: number; code: string; name: string; rate: string; categories: string[]; is_active: boolean }
interface ExchangeRate { id: number; currency: string; rate: string; effective_from: string }

function TaxSettings() {
  const rules = useQuery({ queryKey: ['tax-rules'], queryFn: () => api<Paginated<TaxRule>>('billing/tax-rules/') });
  const rates = useQuery({ queryKey: ['exchange-rates'], queryFn: () => api<Paginated<ExchangeRate>>('billing/exchange-rates/') });
  const [editing, setEditing] = useState<TaxRule | null>(null);
  const [rate, setRate] = useState({ currency: 'USD', rate: '' });
  const setFx = useSave(() => post('billing/exchange-rates/', rate), ['exchange-rates'], () => setRate({ ...rate, rate: '' }));
  // Latest rate per currency first, then history
  const latest = new Map<string, ExchangeRate>();
  for (const r of rates.data?.results ?? []) if (!latest.has(r.currency)) latest.set(r.currency, r);

  return (
    <>
      <Section title="Taxes and levies">
        <ErrorAlert error={rules.error} />
        {!rules.data ? <Loading /> : (
          <table>
            <thead><tr><th>Tax</th><th className="num">Rate</th><th>Applies to</th><th>Status</th><th /></tr></thead>
            <tbody>{rules.data.results.map((t) => (
              <tr key={t.id} className={t.is_active ? '' : 'void'}>
                <td><strong>{t.name}</strong></td><td className="num">{(Number(t.rate) * 100).toFixed(2)}%</td>
                <td className="muted" style={{ fontSize: 13 }}>{t.categories.map(humanize).join(', ')}</td>
                <td>{t.is_active ? <span className="badge ok">Charged</span> : <span className="badge">Off</span>}</td>
                <td className="row-actions"><button className="small" onClick={() => setEditing(t)}>Edit</button></td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </Section>
      <Section title="Exchange rates">
        <p className="muted" style={{ marginTop: 0 }}>Used when guests pay in foreign currency. Setting a new rate keeps the history for past payments.</p>
        <ErrorAlert error={rates.error ?? setFx.error} />
        <table>
          <tbody>{[...latest.values()].map((r) => (
            <tr key={r.id}><td><strong>1 {r.currency}</strong></td><td>= {formatMoney(r.rate)}</td><td className="muted">since {formatDateTime(r.effective_from)}</td></tr>
          ))}</tbody>
        </table>
        <form className="row" style={{ marginTop: 12 }} onSubmit={(e) => { e.preventDefault(); setFx.mutate(undefined); }}>
          <select value={rate.currency} onChange={(e) => setRate({ ...rate, currency: e.target.value })} aria-label="Currency" style={{ width: 'auto' }}>
            {['USD', 'GBP', 'EUR', 'GHS', 'XOF', 'ZAR'].map((c) => <option key={c}>{c}</option>)}
          </select>
          <input type="number" min="0.01" step="0.01" required placeholder="₦ per unit" value={rate.rate} onChange={(e) => setRate({ ...rate, rate: e.target.value })}
                 aria-label="Rate in naira" style={{ width: 160 }} />
          <button className="primary" disabled={setFx.isPending}>Set rate</button>
        </form>
      </Section>
      {editing && <TaxDialog rule={editing} onClose={() => setEditing(null)} />}
    </>
  );
}

function TaxDialog({ rule, onClose }: { rule: TaxRule; onClose: () => void }) {
  const [percent, setPercent] = useState((Number(rule.rate) * 100).toFixed(2));
  const [active, setActive] = useState(rule.is_active);
  const save = useSave(() => patch(`billing/tax-rules/${rule.id}/`, { rate: (Number(percent) / 100).toFixed(4), is_active: active }), ['tax-rules'], onClose);
  return (
    <Modal title={`Edit ${rule.name}`} onClose={onClose}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); save.mutate(undefined); }}>
        <ErrorAlert error={save.error} />
        <Field label="Rate (%)" hint="Applies to charges posted from now on; past charges keep their tax" error={fieldError(save.error, 'rate')}>
          <input type="number" min="0" max="100" step="0.01" required value={percent} onChange={(e) => setPercent(e.target.value)} style={{ maxWidth: 160 }} />
        </Field>
        <label className="checkbox"><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} /> Charge this tax</label>
        <DialogActions busy={save.isPending} onClose={onClose} />
      </form>
    </Modal>
  );
}
