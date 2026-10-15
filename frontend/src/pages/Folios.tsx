import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { api, openFile, post } from '../api/client';
import type { Folio, Paginated } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { Empty, ErrorAlert, Field, fieldError, Loading, Modal, PageHeader, StatusBadge } from '../components/ui';
import { formatDate, formatDateTime, formatMoney, humanize } from '../lib/format';

export interface Account {
  id: number; code: string; name: string; contact_name: string; email: string; phone: string; address: string;
  tax_id: string; credit_limit: string; payment_terms_days: number; is_active: boolean; notes: string; balance: string;
}

const CATEGORIES = ['FOOD', 'BEVERAGE', 'MINIBAR', 'LAUNDRY', 'SPA', 'TRANSPORT', 'TELEPHONE', 'MISC'];

export function Folios() {
  const { can } = useAuth();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const status = params.get('status') ?? 'OPEN';
  const q = params.get('q') ?? '';
  const [search, setSearch] = useState(q);
  const [creating, setCreating] = useState(false);
  const list = useQuery({
    queryKey: ['folios', status, q],
    queryFn: () => api<Paginated<Folio>>('billing/folios/', { query: { status, q } }),
    placeholderData: keepPreviousData,
  });
  const create = useMutation({
    mutationFn: (name: string) => post<Folio>('billing/folios/', { name }),
    onSuccess: (folio) => navigate(`/folios/${folio.id}`),
  });

  return (
    <div className="stack">
      <PageHeader title="Folios" actions={<>
        <form className="row" onSubmit={(e) => { e.preventDefault(); setParams({ status, ...(search ? { q: search } : {}) }); }}>
          <input placeholder="Guest, company or folio" value={search} onChange={(e) => setSearch(e.target.value)}
                 aria-label="Search folios" style={{ width: 220 }} />
        </form>
        <select value={status} onChange={(e) => setParams({ status: e.target.value, ...(q ? { q } : {}) })} aria-label="Status" style={{ width: 'auto' }}>
          <option value="OPEN">Open</option><option value="SETTLED">Settled</option><option value="TRANSFERRED">City ledger</option>
        </select>
        {can('folios.post') && <button className="primary" onClick={() => setCreating(true)}>New bill</button>}
      </>} />
      <ErrorAlert error={list.error} />
      <div className="card table-wrap">
        {list.isLoading ? <Loading /> : !list.data?.results.length ? <Empty>No folios.</Empty> : (
          <table>
            <thead><tr><th>Folio</th><th>Bill to</th><th>Booking</th><th>Status</th><th className="num">Charges</th><th className="num">Balance</th></tr></thead>
            <tbody>
              {list.data.results.map((f) => (
                <tr key={f.id}>
                  <td><Link to={`/folios/${f.id}`}>{f.number}</Link></td>
                  <td>{f.display_name}{f.account && <div className="muted" style={{ fontSize: 12 }}>{f.account}</div>}</td>
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
      {creating && (
        <Modal title="New bill for a non-resident" onClose={() => setCreating(false)}>
          <form className="stack" onSubmit={(e) => { e.preventDefault(); create.mutate(String(new FormData(e.currentTarget).get('name'))); }}>
            <ErrorAlert error={create.error} />
            <p className="muted" style={{ margin: 0 }}>For customers who aren't staying: an event client, a restaurant guest on account, a day-pass visitor.</p>
            <Field label="Bill to"><input name="name" required placeholder="e.g. Adebayo wedding reception" /></Field>
            <div className="actions">
              <button type="button" onClick={() => setCreating(false)}>Cancel</button>
              <button className="primary" disabled={create.isPending}>Open bill</button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}

type Dialog = 'charge' | 'payment' | 'refund' | 'company' | 'link' | 'discount'
  | { voidCharge: number } | { voidPayment: number } | { moveCharge: number }
  | { cardRefund: { transactionId: number; gateway: string; refundable: number } } | null;

export function FolioDetail() {
  const { id } = useParams();
  const { can } = useAuth();
  const queryClient = useQueryClient();
  const [dialog, setDialog] = useState<Dialog>(null);
  const folio = useQuery({ queryKey: ['folio', id], queryFn: () => api<Folio>(`billing/folios/${id}/`) });
  const hotel = useQuery({ queryKey: ['hotel'], queryFn: () => api<{ payment_gateways: string[] }>('hotel/'), staleTime: 3_600_000 });
  const online = !!hotel.data?.payment_gateways.length;

  const mutate = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: unknown }) => post(`billing/folios/${id}/${path}`, body),
    onSuccess: () => {
      for (const key of ['folio', 'folios', 'reservation', 'reservations', 'accounts']) void queryClient.invalidateQueries({ queryKey: [key] });
      setDialog(null);
    },
  });

  if (folio.isLoading) return <Loading />;
  if (!folio.data) return <ErrorAlert error={folio.error} />;
  const f = folio.data;
  const open = f.status === 'OPEN';
  const balance = Number(f.balance);
  const close = () => setDialog(null);
  const run = (path: string) => (body: unknown) => mutate.mutate({ path, body });

  return (
    <div className="stack">
      <PageHeader
        title={`Folio ${f.number}`}
        subtitle={<>{f.display_name} · <StatusBadge status={f.status} />
          {f.booking && <> · <Link to={`/reservations/${f.booking}`}>{f.confirmation_number}</Link></>}
          {f.account && <> · billed to {f.account}</>}</>}
        actions={<>
          {open && can('folios.post') && <button onClick={() => setDialog('charge')}>Post charge</button>}
          {open && can('folios.adjust') && <button onClick={() => setDialog('discount')}>Discount</button>}
          {open && balance > 0 && online && can('payments.take') && <button onClick={() => setDialog('link')}>Payment link</button>}
          {open && balance > 0 && can('accounts.manage') && <button onClick={() => setDialog('company')}>Bill to company</button>}
          {open && balance < 0 && can('payments.refund') && <button onClick={() => setDialog('refund')}>Refund {formatMoney(-balance)}</button>}
          {open && balance === 0 && can('payments.take') && <button onClick={() => mutate.mutate({ path: 'settle/' })}>Settle & invoice</button>}
          {open && can('payments.take') && <button className="primary" onClick={() => setDialog('payment')}>Take payment</button>}
          <button onClick={() => window.print()}>Print</button>
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
                  <td className="row-actions">{open && !c.is_void && can('folios.adjust') && <>
                    <button className="small" onClick={() => setDialog({ moveCharge: c.id })}>Move</button>
                    <button className="small" onClick={() => setDialog({ voidCharge: c.id })}>Void</button>
                  </>}</td>
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
            <thead><tr><th>Received</th><th>Method</th><th>Reference</th><th>By</th><th className="num">Amount</th><th /></tr></thead>
            <tbody>
              {f.payments.map((p) => (
                <tr key={p.id} className={p.is_void ? 'void' : ''}>
                  <td>{formatDateTime(p.received_at)}</td>
                  <td>{humanize(p.method)}{p.kind === 'REFUND' && <span className="badge warn" style={{ marginLeft: 6 }}>Refund</span>}
                    {p.tendered_currency && <div className="muted" style={{ fontSize: 12 }}>{p.tendered_amount} {p.tendered_currency}</div>}</td>
                  <td>{p.reference || '—'}</td><td>{p.received_by ?? 'Online'}</td>
                  <td className="num">{p.kind === 'REFUND' ? '−' : ''}{formatMoney(p.amount)}</td>
                  <td className="row-actions">
                    {open && !p.is_void && p.kind === 'PAYMENT' && p.online && Number(p.online.refundable) > 0 && balance < 0 && can('payments.refund') &&
                      <button className="small" onClick={() => setDialog({ cardRefund: {
                        transactionId: p.online!.transaction_id, gateway: p.online!.gateway, refundable: Number(p.online!.refundable) } })}>Refund to card</button>}
                    {open && !p.is_void && !p.online && can('folios.adjust') &&
                      <button className="small" onClick={() => setDialog({ voidPayment: p.id })}>Void</button>}
                  </td>
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

      {dialog === 'charge' && <ChargeDialog busy={mutate.isPending} error={mutate.error} onClose={close} onSubmit={run('charges/')} />}
      {dialog === 'payment' && <PaymentDialog balance={balance} busy={mutate.isPending} error={mutate.error} onClose={close} onSubmit={run('payments/')} />}
      {dialog === 'refund' && <RefundDialog credit={-balance} busy={mutate.isPending} error={mutate.error} onClose={close} onSubmit={run('refunds/')} />}
      {dialog === 'company' && <CompanyDialog balance={balance} busy={mutate.isPending} error={mutate.error} onClose={close} onSubmit={run('transfer-to-account/')} />}
      {dialog === 'link' && <PaymentLinkDialog folio={f} onClose={close} />}
      {dialog === 'discount' && <DiscountDialog busy={mutate.isPending} error={mutate.error} onClose={close} onSubmit={run('charges/')} />}
      {dialog && typeof dialog === 'object' && 'cardRefund' in dialog && (
        <CardRefundDialog {...dialog.cardRefund} credit={-balance} onClose={close} />
      )}
      {dialog && typeof dialog === 'object' && 'voidCharge' in dialog && (
        <ReasonDialog title="Void charge" busy={mutate.isPending} error={mutate.error} onClose={close}
                      onSubmit={(reason) => mutate.mutate({ path: `charges/${dialog.voidCharge}/void/`, body: { reason } })} />
      )}
      {dialog && typeof dialog === 'object' && 'voidPayment' in dialog && (
        <ReasonDialog title="Void payment" busy={mutate.isPending} error={mutate.error} onClose={close}
                      onSubmit={(reason) => mutate.mutate({ path: `payments/${dialog.voidPayment}/void/`, body: { reason } })} />
      )}
      {dialog && typeof dialog === 'object' && 'moveCharge' in dialog && (
        <MoveChargeDialog folioId={f.id} busy={mutate.isPending} error={mutate.error} onClose={close}
                          onSubmit={run(`charges/${dialog.moveCharge}/transfer/`)} />
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

function RefundDialog({ credit, busy, error, onClose, onSubmit }: DialogProps & { credit: number }) {
  const [form, setForm] = useState({ amount: credit.toFixed(2), method: 'BANK_TRANSFER', reference: '', reason: '' });
  return (
    <Modal title="Refund the guest" onClose={onClose}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); onSubmit(form); }}>
        <ErrorAlert error={error} />
        <p className="muted" style={{ margin: 0 }}>The guest is owed {formatMoney(credit)}, for example an unused deposit.</p>
        <div className="form-grid">
          <Field label="Amount (₦)" error={fieldError(error, 'amount')}>
            <input type="number" step="0.01" min="0.01" max={credit} required value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} />
          </Field>
          <Field label="Paid back by">
            <select value={form.method} onChange={(e) => setForm({ ...form, method: e.target.value })}>
              <option value="BANK_TRANSFER">Bank transfer</option><option value="CASH">Cash</option><option value="CARD_TERMINAL">Card reversal</option>
            </select>
          </Field>
        </div>
        <Field label="Reference" hint="Transfer ID or reversal RRN"><input value={form.reference} onChange={(e) => setForm({ ...form, reference: e.target.value })} /></Field>
        <Field label="Reason" hint="Recorded in the audit log"><input required value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} /></Field>
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy}>Record refund</button></div>
      </form>
    </Modal>
  );
}

function CompanyDialog({ balance, busy, error, onClose, onSubmit }: DialogProps & { balance: number }) {
  const accounts = useQuery({ queryKey: ['accounts'], queryFn: () => api<Paginated<Account>>('billing/accounts/') });
  const [account, setAccount] = useState('');
  const chosen = accounts.data?.results.find((a) => String(a.id) === account);
  const headroom = chosen ? Number(chosen.credit_limit) - Number(chosen.balance) : null;
  return (
    <Modal title="Bill to a company account" onClose={onClose}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); onSubmit({ account: Number(account) }); }}>
        <ErrorAlert error={error} />
        <p className="muted" style={{ margin: 0 }}>Moves the {formatMoney(balance)} balance to the company's city-ledger account and closes this bill with an invoice.</p>
        <Field label="Company" error={fieldError(error, 'account')}>
          <select required value={account} onChange={(e) => setAccount(e.target.value)}>
            <option value="">Select a company</option>
            {accounts.data?.results.filter((a) => a.is_active).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </Field>
        {chosen && headroom !== null && (
          <p style={{ margin: 0 }} className={headroom < balance ? '' : 'muted'}>
            Owes {formatMoney(chosen.balance)} of a {formatMoney(chosen.credit_limit)} limit
            {headroom < balance && <strong style={{ color: 'var(--danger)' }}> · not enough credit left</strong>}
          </p>
        )}
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy}>Bill to company</button></div>
      </form>
    </Modal>
  );
}

function MoveChargeDialog({ folioId, busy, error, onClose, onSubmit }: DialogProps & { folioId: number }) {
  const openFolios = useQuery({
    queryKey: ['folios', 'OPEN', ''],
    queryFn: () => api<Paginated<Folio>>('billing/folios/', { query: { status: 'OPEN' } }),
  });
  const [target, setTarget] = useState('');
  const [reason, setReason] = useState('');
  return (
    <Modal title="Move charge to another bill" onClose={onClose}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); onSubmit({ to_folio: Number(target), reason }); }}>
        <ErrorAlert error={error} />
        <Field label="Move to" hint="e.g. a guest paying for a friend's dinner">
          <select required value={target} onChange={(e) => setTarget(e.target.value)}>
            <option value="">Select an open bill</option>
            {openFolios.data?.results.filter((x) => x.id !== folioId).map((x) => (
              <option key={x.id} value={x.id}>{x.number} · {x.display_name}{x.confirmation_number ? ` (${x.confirmation_number})` : ''}</option>
            ))}
          </select>
        </Field>
        <Field label="Reason"><input value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy}>Move charge</button></div>
      </form>
    </Modal>
  );
}

function PaymentLinkDialog({ folio, onClose }: { folio: Folio; onClose: () => void }) {
  const hotel = useQuery({ queryKey: ['hotel'], queryFn: () => api<{ payment_gateways: string[] }>('hotel/') });
  const [form, setForm] = useState({ gateway: '', email: '', amount: Number(folio.balance).toFixed(2) });
  const [copied, setCopied] = useState(false);
  const create = useMutation({
    mutationFn: () => post<{ authorization_url: string; reference: string }>('payments/transactions/payment-link/', {
      folio: folio.id, gateway: form.gateway || hotel.data?.payment_gateways[0], email: form.email, amount: form.amount,
    }),
  });
  const url = create.data?.authorization_url;
  return (
    <Modal title="Send a payment link" onClose={onClose}>
      {url ? (
        <div className="stack">
          <p style={{ margin: 0 }}>Send this secure link to the guest. The payment is added to folio {folio.number} automatically once it succeeds.</p>
          <input readOnly value={url} onFocus={(e) => e.currentTarget.select()} aria-label="Payment link" />
          <div className="actions">
            <a className="button" href={`mailto:${form.email}?subject=${encodeURIComponent(`Payment for folio ${folio.number}`)}&body=${encodeURIComponent(url)}`}>Email it</a>
            <button className="primary" onClick={() => void navigator.clipboard.writeText(url).then(() => setCopied(true))}>{copied ? 'Copied' : 'Copy link'}</button>
          </div>
        </div>
      ) : (
        <form className="stack" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
          <ErrorAlert error={create.error} />
          <div className="form-grid">
            <Field label="Guest email" error={fieldError(create.error, 'email')}>
              <input type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
            </Field>
            <Field label="Amount (₦)" error={fieldError(create.error, 'amount')}>
              <input type="number" step="0.01" min="1" required value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} />
            </Field>
            <Field label="Gateway">
              <select value={form.gateway} onChange={(e) => setForm({ ...form, gateway: e.target.value })}>
                {hotel.data?.payment_gateways.map((g) => <option key={g} value={g}>{humanize(g)}</option>)}
              </select>
            </Field>
          </div>
          <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={create.isPending}>Create link</button></div>
        </form>
      )}
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

/** A reduction on the bill (allowance): posted as a negative charge, taxes reduced to match. */
function DiscountDialog({ busy, error, onClose, onSubmit }: DialogProps) {
  const [amount, setAmount] = useState('');
  const [reason, setReason] = useState('');
  return (
    <Modal title="Give a discount" onClose={onClose}>
      <form className="stack" onSubmit={(e) => {
        e.preventDefault();
        onSubmit({ category: 'ALLOWANCE', description: `Discount: ${reason}`, unit_price: (-Math.abs(Number(amount))).toFixed(2), quantity: '1' });
      }}>
        <ErrorAlert error={error} />
        <p className="muted" style={{ margin: 0 }}>Taken off the bill before tax; the VAT and levies on it are reduced too. Recorded in the audit log.</p>
        <Field label="Amount off (₦, before tax)" error={fieldError(error, 'unit_price')}>
          <input type="number" step="0.01" min="0.01" required value={amount} onChange={(e) => setAmount(e.target.value)} />
        </Field>
        <Field label="Reason" hint="e.g. AC fault in room, loyal guest, manager's goodwill"><input required value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={busy}>Apply discount</button></div>
      </form>
    </Modal>
  );
}

/** Send money back to the card or account an online payment came from (needs the guest to be in credit). */
function CardRefundDialog({ transactionId, gateway, refundable, credit, onClose }: {
  transactionId: number; gateway: string; refundable: number; credit: number; onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const max = Math.min(refundable, credit);
  const [amount, setAmount] = useState(max.toFixed(2));
  const [reason, setReason] = useState('');
  const refund = useMutation({
    mutationFn: () => post(`payments/transactions/${transactionId}/refund/`, { amount, reason }),
    onSuccess: () => { for (const key of ['folio', 'folios', 'reservation']) void queryClient.invalidateQueries({ queryKey: [key] }); onClose(); },
  });
  return (
    <Modal title={`Refund to card via ${humanize(gateway)}`} onClose={onClose}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); refund.mutate(); }}>
        <ErrorAlert error={refund.error} />
        <p className="muted" style={{ margin: 0 }}>The money goes back to the card or account the guest paid with. It usually reaches them in a few working days.</p>
        <Field label="Amount (₦)" hint={`Up to ${formatMoney(max)}`} error={fieldError(refund.error, 'amount')}>
          <input type="number" step="0.01" min="0.01" max={max} required value={amount} onChange={(e) => setAmount(e.target.value)} />
        </Field>
        <Field label="Reason" hint="Recorded in the audit log"><input required value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={refund.isPending}>Refund {formatMoney(Number(amount) || 0)}</button></div>
      </form>
    </Modal>
  );
}
