import { useEffect, useRef, type ReactNode } from 'react';

import { ApiError } from '../api/client';
import { humanize } from '../lib/format';

const STATUS_TONE: Record<string, string> = {
  CONFIRMED: 'info', CHECKED_IN: 'ok', CHECKED_OUT: '', PENDING: 'warn', CANCELLED: 'danger', NO_SHOW: 'danger',
  OPEN: 'warn', SETTLED: 'ok', TRANSFERRED: 'info', SUCCEEDED: 'ok', FAILED: 'danger', NEEDS_REVIEW: 'warn',
  AVAILABLE: 'ok', OCCUPIED: 'info', MAINTENANCE: 'warn', OUT_OF_SERVICE: 'danger',
  CLEAN: 'ok', DIRTY: 'warn', INSPECTED: 'ok',
};

export function StatusBadge({ status }: { status: string }) {
  return <span className={`badge ${STATUS_TONE[status] ?? ''}`}>{humanize(status)}</span>;
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="page-header">
      <div>
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {actions && <div className="row">{actions}</div>}
    </div>
  );
}

export function ErrorAlert({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : 'Something went wrong.';
  return <div className="alert error" role="alert">{message}</div>;
}

export function Loading() {
  return <div className="empty" aria-busy="true">Loading…</div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Field({ label, hint, error, children }: { label: string; hint?: string; error?: string; children: ReactNode }) {
  return (
    <label className="field">
      {label}
      {children}
      {hint && <span className="hint">{hint}</span>}
      {error && <span className="hint" style={{ color: 'var(--danger)' }}>{error}</span>}
    </label>
  );
}

export function fieldError(error: unknown, field: string) {
  return error instanceof ApiError ? error.fieldErrors()[field] : undefined;
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const dialog = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    dialog.current?.querySelector<HTMLElement>('input, select, textarea, button')?.focus();
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title} ref={dialog}>
        <h2>{title}</h2>
        {children}
      </div>
    </div>
  );
}
