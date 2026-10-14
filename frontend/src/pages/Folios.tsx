import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';

import { api, openFile, post } from '../api/client';
import type { Folio, Paginated } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { Empty, ErrorAlert, Field, fieldError, Loading, Modal, PageHeader, StatusBadge } from '../components/ui';
import { formatDate, formatDateTime, formatMoney, humanize } from '../lib/format';

const CATEGORIES = ['FOOD', 'BEVERAGE', 'MINIBAR', 'LAUNDRY', 'SPA', 'TRANSPORT', 'TELEPHONE', 'MISC'];

export function Folios() {
  const [params, setParams] = useSearchParams();
  const status = params.get('status') ?? 'OPEN';
  const list = useQuery({
    queryKey: ['folios', status],
    queryFn: () => api<Paginated<Folio>>('billing/folios/', { query: { status } }),
    placeholderData: keepPreviousData,
  });
  return (
    <div className="stack">
      <PageHeader title="Folios" actions={
        <select value={status} onChange={(e) => setParams({ status: e.target.value })} aria-label="Status" style={{ width: 'auto' }}>
          <option value="OPEN">Open</option><option value="SETTLED">Settled</option><option value="TRANSFERRED">City ledger</option>
        </select>} />
      <ErrorAlert error={list.error} />
      <div className="card table-wrap">
        {list.isLoading ? <Loading /> : !list.data?.results.length ? <Empty>No folios.</Empty> : (
          <table>
            <thead><tr><th>Folio</th><th>Bill to</th><th>Booking</th><th>Status</th><th className="num">Charges</th><th className="num">Balance</th></tr></thead>
            <tbody>
              {list.data.results.map((f) => (
                <tr key={f.id}>
                  <td><Link to={`/folios/${f.id}`}>{f.number}</Link></td>
                  <td>{f.display_name}</td>
                  <td>{f.booking ? <Link to={`/reservations/${f.booking}`}>{f.confirmation_number}</Link> : '—'}</td>
                  <td><StatusBadge status={f.status} /></td>
                  <td className="num">{formatMoney(f.charges_total)}</td>
                  <td className="num"><strong>{formatMoney(f.balance)}</strong></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

type Dialog = 'charge' | 'payment' | { voidCharge: number } | null;

export function FolioDetail() {
  const { id } = useParams();
  const { can } = useAuth();
  const queryClient = useQueryClient();
  const [dialog, setDialog] = useState<Dialog>(null);
  const folio = useQuery({ queryKey: ['folio', id], queryFn: () => api<Folio>(`billing/folios/${id}/`) });

  const mutate = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: unknown }) => post(`billing/folios/${id}/${path}`, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['folio', id] });
      void queryClient.invalidateQueries({ queryKey: ['reservation'] });
      setDialog(null);
    },
  });

  if (folio.isLoading) return <Loading />;
  if (!folio.data) return <ErrorAlert error={folio.error} />;
  const f = folio.data;
  const open = f.status === 'OPEN';
  const balance = Number(f.balance);

  return (
    <div className="stack">
      <PageHeader
        title={`Folio ${f.number}`}
        subtitle={<>{f.display_name} · <StatusBadge status={f.status} />
          {f.booking && <> · <Link to={`/reservations/${f.booking}`}>{f.confirmation_number}</Link></>}</>}
        actions={<>
          {open && can('folios.post') && <button onClick={() => setDialog('charge')}>Post charge</button>}
          {open && can('payments.take') && <button className="primary" onClick={() => setDialog('payment')}>Take payment</button>}
          {open && balance === 0 && can('payments.take') && <button onClick={() => mutate.mutate({ path: 'settle/' })}>Settle & invoice</button>}
        </>}
      />
      {!dialog && <ErrorAlert error={mutate.error} />}
      <div className="grid stats">
        <div className="card stat"><div className="label">Charges</div><div className="value">{formatMoney(f.charges_total)}</div></div>
        <div className="card stat"><div className="label">Paid</div><div className="value">{formatMoney(f.payments_total)}</div></div>
        <div className="card stat"><div className="label">{balance < 0 ? 'Credit (owed to guest)' : 'Balance due'}</div>
          <div className="value" style={{ color: balance > 0 ? 'var(--danger)' : undefined }}>{formatMoney(Math.abs(balance))}</div></div>
      </div>
      <div className="card table-wrap">
        <h2>Charges</h2>
        {!f.charges.length ? <div className="muted">No charges yet.</div> : (
          <table>
            <thead><tr><th>Date</th><th>Description</th><th>Category</th><th className="num">Net</th><th className="num">Tax</th><th className="num">Total</th><th /></tr></thead>
            <tbody>
              {f.charges.map((c) => (
                <tr key={c.id} className={c.is_void ? 'void' : ''} title={c.is_void ? `Void: ${c.void_reason}` : undefined}>
                  <td>{formatDate(c.service_date)}</td><td>{c.description}</td><td>{humanize(c.category)}</td>
                  <td className="num">{formatMoney(c.net_amount)}</td><td className="num">{formatMoney(c.tax_amount)}</td>
                  <td className="num">{formatMoney(c.total_amount)}</td>
                  <td>{open && !c.is_void && can('folios.adjust') && (
                    <button onClick={() => setDialog({ voidCharge: c.id })}>Void</button>
                  )}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <div className="card table-wrap">
        <h2>Payments</h2>
        {!f.payments.length ? <div className="muted">No payments yet.</div> : (
          <table>
            <thead><tr><th>Received</th><th>Method</th><th>Reference</th><th>By</th><th className="num">Amount</th></tr></thead>
            <tbody>
              {f.payments.map((p) => (
                <tr key={p.id} className={p.is_void ? 'void' : ''}>
                  <td>{formatDateTime(p.received_at)}</td>
                  <td>{humanize(p.method)}{p.kind === 'REFUND' && <span className="badge warn" style={{ marginLeft: 6 }}>Refund</span>}
                    {p.tendered_currency && <div className="muted" style={{ fontSize: 12 }}>{p.tendered_amount} {p.tendered_currency}</div>}</td>
                  <td>{p.reference || '—'}</td><td>{p.received_by ?? 'Online'}</td>
                  <td className="num">{p.kind === 'REFUND' ? '−' : ''}{formatMoney(p.amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {f.invoices.length > 0 && (
        <div className="card">
          <h2>Invoices</h2>
          {f.invoices.map((inv) => (
            <div className="row" key={inv.id}>
              <strong>{inv.number}</strong><span className="muted">{formatDateTime(inv.issued_at)}</span>
              <span>{formatMoney(inv.total)}</span>
              <button onClick={() => void openFile(`/api/billing/invoices/${inv.id}/pdf/`)}>Open PDF</button>
            </div>
          ))}
        </div>
      )}

      {dialog === 'charge' && <ChargeDialog busy={mutate.isPending} error={mutate.error} onClose={() => setDialog(null)}
                                            onSubmit={(body) => mutate.mutate({ path: 'charges/', body })} />}
      {dialog === 'payment' && <PaymentDialog balance={balance} busy={mutate.isPending} error={mutate.error}
                                              onClose={() => setDialog(null)} onSubmit={(body) => mutate.mutate({ path: 'payments/', body })} />}
      {dialog && typeof dialog === 'object' && (
        <ReasonDialog title="Void charge" busy={mutate.isPending} error={mutate.error} onClose={() => setDialog(null)}
                      onSubmit={(reason) => mutate.mutate({ path: `charges/${dialog.voidCharge}/void/`, body: { reason } })} />
      )}
    </div>
  );
}

interface DialogProps { busy: boolean; error: unknown; onClose: () => void; onSubmit: (body: Record<string, unknown>) => void }

function ChargeDialog({ busy, error, onClose, onSubmit }: DialogProps) {
  const [form, setForm] = useState({ category: 'FOOD', description: '', unit_price: '', quantity: '1' });
  return (
    <Modal title="Post a charge" onClose={onClose}>
      <form className="stack" onSubmit={(e: FormEvent) => { e.preventDefault(); onSubmit(form); }}>
        <ErrorAlert error={error} />
        <div className="form-grid">
          <Field label="Category">
            <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
              {CATEGORIES.map((c) => <option key={c} value={c}>{humanize(c)}</option>)}
            </select>
          </Field>
          <Field label="Unit price (₦, before tax)" error={fieldError(error, 'unit_price')}>
            <input type="number" step="0.01" min="0" required value={form.unit_price} onChange={(e) => setForm({ ...form, unit_price: e.target.value })} />
          </Field>
          <Field label="Quantity"><input type="number" step="1" min="1" value={form.quantity} onChange={(e) => setForm({ ...form, quantity: e.target.value })} /></Field>
        </div>
        <Field label="Description"><input required value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy}>Post</button></div>
      </form>
    </Modal>
  );
}

function PaymentDialog({ balance, busy, error, onClose, onSubmit }: DialogProps & { balance: number }) {
  const [form, setForm] = useState({ method: 'CASH', amount: balance > 0 ? balance.toFixed(2) : '', reference: '', currency: 'NGN', tendered_amount: '' });
  const foreign = form.currency !== 'NGN';
  return (
    <Modal title="Take payment" onClose={onClose}>
      <form className="stack" onSubmit={(e: FormEvent) => {
        e.preventDefault();
        onSubmit(foreign
          ? { method: form.method, currency: form.currency, tendered_amount: form.tendered_amount, reference: form.reference }
          : { method: form.method, amount: form.amount, reference: form.reference });
      }}>
        <ErrorAlert error={error} />
        <div className="form-grid">
          <Field label="Method">
            <select value={form.method} onChange={(e) => setForm({ ...form, method: e.target.value })}>
              <option value="CASH">Cash</option><option value="CARD_TERMINAL">Card (POS terminal)</option><option value="BANK_TRANSFER">Bank transfer</option>
            </select>
          </Field>
          <Field label="Currency">
            <select value={form.currency} onChange={(e) => setForm({ ...form, currency: e.target.value })}>
              <option value="NGN">NGN</option><option value="USD">USD</option><option value="GBP">GBP</option><option value="EUR">EUR</option>
            </select>
          </Field>
          {foreign ? (
            <Field label={`Amount tendered (${form.currency})`} hint="Converted at today's rate" error={fieldError(error, 'tendered_amount') ?? fieldError(error, 'currency')}>
              <input type="number" step="0.01" min="0" required value={form.tendered_amount} onChange={(e) => setForm({ ...form, tendered_amount: e.target.value })} />
            </Field>
          ) : (
            <Field label="Amount (₦)" error={fieldError(error, 'amount')}>
              <input type="number" step="0.01" min="0" required value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} />
            </Field>
          )}
        </div>
        <Field label="Reference" hint="Required for card and transfer (RRN / transfer ID)" error={fieldError(error, 'reference')}>
          <input value={form.reference} onChange={(e) => setForm({ ...form, reference: e.target.value })} />
        </Field>
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy}>Record payment</button></div>
      </form>
    </Modal>
  );
}

export function ReasonDialog({ title, busy, error, onClose, onSubmit }: { title: string; busy: boolean; error: unknown; onClose: () => void; onSubmit: (reason: string) => void }) {
  const [reason, setReason] = useState('');
  return (
    <Modal title={title} onClose={onClose}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); onSubmit(reason); }}>
        <ErrorAlert error={error} />
        <Field label="Reason" hint="Recorded in the audit log"><input required value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="danger" disabled={busy}>{title}</button></div>
      </form>
    </Modal>
  );
}
