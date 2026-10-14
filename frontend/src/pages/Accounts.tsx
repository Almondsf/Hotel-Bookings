import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { api, patch, post } from '../api/client';
import type { Folio, Paginated } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { Empty, ErrorAlert, Field, fieldError, Loading, Modal, PageHeader } from '../components/ui';
import { formatDate, formatDateTime, formatMoney, humanize } from '../lib/format';
import type { Account } from './Folios';

interface AccountPayment { id: number; amount: string; method: string; reference: string; received_at: string; is_void: boolean }
interface Statement { account: Account; folios: (Folio & { transferred_at?: string })[]; payments: AccountPayment[] }

/** Company (city-ledger) accounts: who owes what, and how close they are to their limit. */
export function Accounts() {
  const { can } = useAuth();
  const [editing, setEditing] = useState<Account | 'new' | null>(null);
  const accounts = useQuery({ queryKey: ['accounts'], queryFn: () => api<Paginated<Account>>('billing/accounts/') });
  const rows = accounts.data?.results ?? [];
  const owed = rows.reduce((sum, a) => sum + Number(a.balance), 0);

  return (
    <div className="stack">
      <PageHeader
        title="Company accounts"
        subtitle={accounts.data ? `${rows.length} companies · ${formatMoney(owed)} outstanding` : undefined}
        actions={can('accounts.manage') && <button className="primary" onClick={() => setEditing('new')}>Add company</button>}
      />
      <ErrorAlert error={accounts.error} />
      <div className="card table-wrap">
        {accounts.isLoading ? <Loading /> : !rows.length ? <Empty>No company accounts yet.</Empty> : (
          <table>
            <thead><tr><th>Company</th><th>Contact</th><th className="num">Owes</th><th className="num">Credit limit</th><th>Terms</th><th /></tr></thead>
            <tbody>
              {rows.map((a) => {
                const used = Number(a.credit_limit) ? Number(a.balance) / Number(a.credit_limit) : 0;
                return (
                  <tr key={a.id} className={a.is_active ? '' : 'void'}>
                    <td><Link to={`/companies/${a.id}`}>{a.name}</Link>{!a.is_active && <span className="badge" style={{ marginLeft: 6 }}>Inactive</span>}</td>
                    <td>{a.contact_name || '—'}<div className="muted" style={{ fontSize: 12 }}>{a.email}</div></td>
                    <td className="num"><strong>{formatMoney(a.balance)}</strong></td>
                    <td className="num">{formatMoney(a.credit_limit)}
                      {used >= 0.8 && <div style={{ fontSize: 12, color: 'var(--danger)' }}>{Math.round(used * 100)}% used</div>}</td>
                    <td>{a.payment_terms_days} days</td>
                    <td className="row-actions">{can('accounts.manage') && <button className="small" onClick={() => setEditing(a)}>Edit</button>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
      {editing && <AccountDialog account={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

export function AccountDetail() {
  const { id } = useParams();
  const { can } = useAuth();
  const [dialog, setDialog] = useState<'payment' | 'edit' | null>(null);
  const statement = useQuery({ queryKey: ['accounts', 'statement', id], queryFn: () => api<Statement>(`billing/accounts/${id}/statement/`) });

  if (statement.isLoading) return <Loading />;
  if (!statement.data) return <ErrorAlert error={statement.error} />;
  const { account: a, folios, payments } = statement.data;
  const billed = folios.reduce((sum, f) => sum + Number(f.balance), 0);
  const paid = payments.reduce((sum, p) => sum + Number(p.amount), 0);

  return (
    <div className="stack">
      <PageHeader
        title={a.name}
        subtitle={<>{a.code}{a.tax_id && <> · TIN {a.tax_id}</>} · {a.payment_terms_days}-day terms</>}
        actions={can('accounts.manage') && <>
          <button onClick={() => setDialog('edit')}>Edit</button>
          <button onClick={() => window.print()}>Print statement</button>
          {Number(a.balance) > 0 && <button className="primary" onClick={() => setDialog('payment')}>Record payment</button>}
        </>}
      />
      <div className="grid stats">
        <div className="card stat"><div className="label">Billed to account</div><div className="value">{formatMoney(billed)}</div></div>
        <div className="card stat"><div className="label">Paid</div><div className="value">{formatMoney(paid)}</div></div>
        <div className="card stat"><div className="label">Outstanding</div>
          <div className="value" style={{ color: Number(a.balance) > 0 ? 'var(--danger)' : undefined }}>{formatMoney(a.balance)}</div></div>
        <div className="card stat"><div className="label">Credit left</div><div className="value">{formatMoney(Number(a.credit_limit) - Number(a.balance))}</div></div>
      </div>
      <div className="grid cols-2">
        <div className="card">
          <h2>Contact</h2>
          <dl className="details">
            <dt>Name</dt><dd>{a.contact_name || '—'}</dd>
            <dt>Email</dt><dd>{a.email ? <a href={`mailto:${a.email}`}>{a.email}</a> : '—'}</dd>
            <dt>Phone</dt><dd>{a.phone || '—'}</dd>
            <dt>Address</dt><dd>{a.address || '—'}</dd>
            {a.notes && <><dt>Notes</dt><dd>{a.notes}</dd></>}
          </dl>
        </div>
        <div className="card table-wrap">
          <h2>Payments received</h2>
          {!payments.length ? <div className="muted">None yet.</div> : (
            <table>
              <tbody>{payments.map((p) => (
                <tr key={p.id}><td>{formatDateTime(p.received_at)}</td><td>{humanize(p.method)}</td><td>{p.reference || '—'}</td>
                  <td className="num">{formatMoney(p.amount)}</td></tr>
              ))}</tbody>
            </table>
          )}
        </div>
      </div>
      <div className="card table-wrap">
        <h2>Bills charged to the account</h2>
        {!folios.length ? <div className="muted">Nothing billed to this company yet.</div> : (
          <table>
            <thead><tr><th>Folio</th><th>Guest</th><th>Booking</th><th>Billed</th><th className="num">Amount</th></tr></thead>
            <tbody>{folios.map((f) => (
              <tr key={f.id}>
                <td><Link to={`/folios/${f.id}`}>{f.number}</Link></td>
                <td>{f.display_name}</td>
                <td>{f.booking ? <Link to={`/reservations/${f.booking}`}>{f.confirmation_number}</Link> : '—'}</td>
                <td>{formatDate(f.transferred_at ?? null)}</td>
                <td className="num">{formatMoney(f.balance)}</td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </div>
      {dialog === 'payment' && <AccountPaymentDialog account={a} onClose={() => setDialog(null)} />}
      {dialog === 'edit' && <AccountDialog account={a} onClose={() => setDialog(null)} />}
    </div>
  );
}

function AccountPaymentDialog({ account, onClose }: { account: Account; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({ amount: Number(account.balance).toFixed(2), method: 'BANK_TRANSFER', reference: '' });
  const save = useMutation({
    mutationFn: () => post(`billing/accounts/${account.id}/payments/`, form),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['accounts'] }); onClose(); },
  });
  return (
    <Modal title={`Payment from ${account.name}`} onClose={onClose}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        <ErrorAlert error={save.error} />
        <div className="form-grid">
          <Field label="Amount (₦)" error={fieldError(save.error, 'amount')}>
            <input type="number" step="0.01" min="0.01" required value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} />
          </Field>
          <Field label="Method">
            <select value={form.method} onChange={(e) => setForm({ ...form, method: e.target.value })}>
              <option value="BANK_TRANSFER">Bank transfer</option><option value="CARD_TERMINAL">Card</option><option value="CASH">Cash</option>
            </select>
          </Field>
        </div>
        <Field label="Reference" hint="Transfer ID or cheque number"><input value={form.reference} onChange={(e) => setForm({ ...form, reference: e.target.value })} /></Field>
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={save.isPending}>Record payment</button></div>
      </form>
    </Modal>
  );
}

function AccountDialog({ account, onClose }: { account: Account | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
    code: account?.code ?? '', name: account?.name ?? '', contact_name: account?.contact_name ?? '', email: account?.email ?? '',
    phone: account?.phone ?? '', address: account?.address ?? '', tax_id: account?.tax_id ?? '',
    credit_limit: account?.credit_limit ?? '1000000', payment_terms_days: account?.payment_terms_days ?? 30,
    is_active: account?.is_active ?? true, notes: account?.notes ?? '',
  });
  const save = useMutation({
    mutationFn: () => (account ? patch(`billing/accounts/${account.id}/`, form) : post('billing/accounts/', form)),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['accounts'] }); onClose(); },
  });
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });
  return (
    <Modal title={account ? `Edit ${account.name}` : 'Add a company account'} onClose={onClose}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        <ErrorAlert error={save.error} />
        <div className="form-grid">
          <Field label="Company name" error={fieldError(save.error, 'name')}><input required value={form.name} onChange={set('name')} /></Field>
          <Field label="Code" hint="Short id, e.g. dangote" error={fieldError(save.error, 'code')}>
            <input required pattern="[a-z0-9-]+" value={form.code} onChange={set('code')} disabled={!!account} />
          </Field>
          <Field label="Contact person"><input value={form.contact_name} onChange={set('contact_name')} /></Field>
          <Field label="Email" error={fieldError(save.error, 'email')}><input type="email" value={form.email} onChange={set('email')} /></Field>
          <Field label="Phone"><input value={form.phone} onChange={set('phone')} /></Field>
          <Field label="TIN" hint="Printed on invoices"><input value={form.tax_id} onChange={set('tax_id')} /></Field>
          <Field label="Credit limit (₦)" error={fieldError(save.error, 'credit_limit')}>
            <input type="number" min="0" step="1000" required value={form.credit_limit} onChange={set('credit_limit')} />
          </Field>
          <Field label="Payment terms (days)"><input type="number" min="0" value={form.payment_terms_days} onChange={set('payment_terms_days')} /></Field>
        </div>
        <Field label="Address"><textarea value={form.address} onChange={set('address')} /></Field>
        <Field label="Notes"><textarea value={form.notes} onChange={set('notes')} /></Field>
        {account && <label className="checkbox"><input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
          Active (inactive companies can't be billed)</label>}
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" disabled={save.isPending}>Save</button></div>
      </form>
    </Modal>
  );
}
