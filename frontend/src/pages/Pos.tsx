import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';

import { api, post } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { Empty, ErrorAlert, Field, fieldError, Modal, PageHeader } from '../components/ui';
import { formatMoney } from '../lib/format';

interface Outlet { id: number; code: string; name: string }
interface Product { id: number; name: string; section: string; price: string; is_available: boolean; track_stock: boolean; stock_quantity: number }
interface Order {
  id: number; number: string; table_label: string; status: string;
  items: { id: number; name: string; unit_price: string; quantity: number; notes: string }[];
  totals: { net: string; tax: string; total: string };
  change_due?: string;
}

export function Pos() {
  const { can } = useAuth();
  const queryClient = useQueryClient();
  const outlets = useQuery({ queryKey: ['pos-outlets'], queryFn: () => api<Outlet[]>('pos/outlets/') });
  const [outletId, setOutletId] = useState<number | null>(null);
  const [orderId, setOrderId] = useState<number | null>(null);
  const [dialog, setDialog] = useState<'pay' | 'room' | 'void' | null>(null);
  const [notice, setNotice] = useState('');
  const [table, setTable] = useState('');

  useEffect(() => {
    if (!outletId && outlets.data?.length) setOutletId(outlets.data[0].id);
  }, [outlets.data, outletId]);

  const products = useQuery({
    queryKey: ['pos-products', outletId],
    queryFn: () => api<Product[]>('pos/products/', { query: { outlet: outletId } }),
    enabled: !!outletId,
  });
  const openOrders = useQuery({
    queryKey: ['pos-orders', outletId],
    queryFn: () => api<{ results: Order[] }>('pos/orders/', { query: { outlet: outletId, status: 'OPEN' } }),
    enabled: !!outletId,
  });
  const order = useQuery({
    queryKey: ['pos-order', orderId], queryFn: () => api<Order>(`pos/orders/${orderId}/`), enabled: !!orderId,
  });

  const refresh = (data?: Order) => {
    if (data) queryClient.setQueryData(['pos-order', data.id], data);
    void queryClient.invalidateQueries({ queryKey: ['pos-orders'] });
  };
  const call = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: unknown }) => post<Order>(path, body),
    onSuccess: (data) => {
      refresh(data);
      if (data.status !== 'OPEN') {
        setNotice(data.status === 'SETTLED'
          ? `${data.number} settled${data.change_due && Number(data.change_due) > 0 ? ` · change due ${formatMoney(data.change_due)}` : ''}.`
          : `${data.number} voided.`);
        setOrderId(null);
        setDialog(null);
      }
    },
  });

  async function newOrder() {
    const created = await post<Order>('pos/orders/', { outlet: outletId, table_label: table });
    setTable('');
    setNotice('');
    setOrderId(created.id);
    refresh(created);
  }

  const sections = new Map<string, Product[]>();
  for (const p of products.data ?? []) sections.set(p.section || 'Menu', [...(sections.get(p.section || 'Menu') ?? []), p]);
  const current = order.data;

  return (
    <div className="stack">
      <PageHeader title="Point of sale" actions={<>
        <select value={outletId ?? ''} onChange={(e) => { setOutletId(Number(e.target.value)); setOrderId(null); }}
                aria-label="Outlet" style={{ width: 'auto' }}>
          {outlets.data?.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
        </select>
        <input placeholder="Table / seat / room" value={table} onChange={(e) => setTable(e.target.value)}
               aria-label="Table" style={{ width: 160 }} />
        <button className="primary" disabled={!outletId} onClick={() => void newOrder()}>New order</button>
      </>} />
      {notice && <div className="alert success">{notice}</div>}
      <ErrorAlert error={outlets.error || call.error} />
      {outlets.data && !outlets.data.length && <Empty>You haven't been given access to any outlet.</Empty>}
      <div className="pos-layout">
        <div className="stack">
          <div className="row">
            {openOrders.data?.results.map((o) => (
              <button key={o.id} className={o.id === orderId ? 'primary' : ''} onClick={() => setOrderId(o.id)}>
                {o.table_label || o.number} · {formatMoney(o.totals.total)}
              </button>
            ))}
          </div>
          {[...sections.entries()].map(([section, items]) => (
            <div key={section}>
              <h3 className="muted" style={{ fontSize: 13, textTransform: 'uppercase', margin: '4px 0 8px' }}>{section}</h3>
              <div className="pos-products">
                {items.map((p) => (
                  <button key={p.id} className="pos-product" disabled={!current || !p.is_available || (p.track_stock && p.stock_quantity <= 0)}
                          onClick={() => call.mutate({ path: `pos/orders/${orderId}/items/`, body: { product: p.id, quantity: 1 } })}>
                    <span>{p.name}</span>
                    <strong>{formatMoney(p.price)}</strong>
                    {p.track_stock && <small className="muted">{p.stock_quantity} left</small>}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
        <aside className="card pos-ticket">
          {!current ? <div className="muted">Select or start an order.</div> : (
            <div className="stack">
              <div><h2 style={{ margin: 0 }}>{current.table_label || 'Order'}</h2><span className="muted">{current.number}</span></div>
              {!current.items.length ? <div className="muted">Tap items to add them.</div> : (
                <table>
                  <tbody>{current.items.map((i) => (
                    <tr key={i.id}>
                      <td>{i.quantity} × {i.name}</td>
                      <td className="num">{formatMoney(Number(i.unit_price) * i.quantity)}</td>
                      <td><button aria-label={`Remove ${i.name}`} onClick={() => call.mutate({ path: `pos/orders/${current.id}/items/${i.id}/remove/` })}>✕</button></td>
                    </tr>
                  ))}</tbody>
                </table>
              )}
              <dl className="details">
                <dt>Subtotal</dt><dd className="num">{formatMoney(current.totals.net)}</dd>
                <dt>Tax</dt><dd className="num">{formatMoney(current.totals.tax)}</dd>
                <dt><strong>Total</strong></dt><dd className="num"><strong>{formatMoney(current.totals.total)}</strong></dd>
              </dl>
              <div className="row">
                <button className="primary" disabled={!current.items.length} onClick={() => setDialog('pay')}>Pay</button>
                <button disabled={!current.items.length} onClick={() => setDialog('room')}>Charge to room</button>
                {can('pos.void') && <button className="danger" onClick={() => setDialog('void')}>Void</button>}
              </div>
            </div>
          )}
        </aside>
      </div>
      {current && dialog === 'pay' && <PayDialog total={current.totals.total} busy={call.isPending} error={call.error}
        onClose={() => setDialog(null)} onSubmit={(body) => call.mutate({ path: `pos/orders/${current.id}/pay/`, body })} />}
      {current && dialog === 'room' && <RoomChargeDialog busy={call.isPending} error={call.error}
        onClose={() => setDialog(null)} onSubmit={(body) => call.mutate({ path: `pos/orders/${current.id}/charge-to-room/`, body })} />}
      {current && dialog === 'void' && (
        <Modal title={`Void ${current.number}`} onClose={() => setDialog(null)}>
          <VoidForm busy={call.isPending} error={call.error} onCancel={() => setDialog(null)}
                    onSubmit={(reason) => call.mutate({ path: `pos/orders/${current.id}/void/`, body: { reason } })} />
        </Modal>
      )}
    </div>
  );
}

function VoidForm({ busy, error, onCancel, onSubmit }: { busy: boolean; error: unknown; onCancel: () => void; onSubmit: (reason: string) => void }) {
  const [reason, setReason] = useState('');
  return (
    <form className="stack" onSubmit={(e) => { e.preventDefault(); onSubmit(reason); }}>
      <ErrorAlert error={error} />
      <Field label="Reason"><input required value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      <div className="actions"><button type="button" onClick={onCancel}>Back</button><button className="danger" disabled={busy}>Void order</button></div>
    </form>
  );
}

function PayDialog({ total, busy, error, onClose, onSubmit }: { total: string; busy: boolean; error: unknown; onClose: () => void; onSubmit: (body: unknown) => void }) {
  const [method, setMethod] = useState('CASH');
  const [tendered, setTendered] = useState(total);
  const [reference, setReference] = useState('');
  const change = Number(tendered) - Number(total);
  return (
    <Modal title={`Take payment · ${formatMoney(total)}`} onClose={onClose}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); onSubmit(method === 'CASH' ? { method, tendered_amount: tendered } : { method, reference }); }}>
        <ErrorAlert error={error} />
        <div className="row">
          {[['CASH', 'Cash'], ['CARD_TERMINAL', 'Card'], ['BANK_TRANSFER', 'Transfer']].map(([value, label]) => (
            <button type="button" key={value} className={method === value ? 'primary' : ''} onClick={() => setMethod(value)}>{label}</button>
          ))}
        </div>
        {method === 'CASH' ? (
          <Field label="Cash received (₦)" hint={change >= 0 ? `Change: ${formatMoney(change)}` : 'Not enough'} error={fieldError(error, 'tendered_amount')}>
            <input type="number" step="0.01" value={tendered} onChange={(e) => setTendered(e.target.value)} />
          </Field>
        ) : (
          <Field label="Reference (RRN / transfer ID)" error={fieldError(error, 'reference')}>
            <input required value={reference} onChange={(e) => setReference(e.target.value)} />
          </Field>
        )}
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy}>Complete sale</button></div>
      </form>
    </Modal>
  );
}

function RoomChargeDialog({ busy, error, onClose, onSubmit }: { busy: boolean; error: unknown; onClose: () => void; onSubmit: (body: unknown) => void }) {
  const [room, setRoom] = useState('');
  const [surname, setSurname] = useState('');
  return (
    <Modal title="Charge to room" onClose={onClose}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); onSubmit({ room_number: room, guest_last_name: surname }); }}>
        <ErrorAlert error={error} />
        <p className="muted" style={{ margin: 0 }}>Ask the guest for their room number and surname.</p>
        <div className="form-grid">
          <Field label="Room number"><input required value={room} onChange={(e) => setRoom(e.target.value)} /></Field>
          <Field label="Guest surname" error={fieldError(error, 'guest_last_name')}>
            <input required value={surname} onChange={(e) => setSurname(e.target.value)} autoComplete="off" />
          </Field>
        </div>
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy}>Charge</button></div>
      </form>
    </Modal>
  );
}
