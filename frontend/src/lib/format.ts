const money = new Intl.NumberFormat('en-NG', { style: 'currency', currency: 'NGN', minimumFractionDigits: 2 });
const dateFormat = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
const dateTimeFormat = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
});

export function formatMoney(value: string | number | null | undefined, currency = 'NGN') {
  if (value === null || value === undefined || value === '') return '—';
  const amount = Number(value);
  if (currency === 'NGN') return money.format(amount);
  return new Intl.NumberFormat('en-NG', { style: 'currency', currency }).format(amount);
}

export function formatDate(value: string | null | undefined) {
  if (!value) return '—';
  // Dates without a time are calendar dates; don't shift them across timezones
  const date = value.length === 10 ? new Date(`${value}T00:00:00`) : new Date(value);
  return dateFormat.format(date);
}

export function formatDateTime(value: string | null | undefined) {
  return value ? dateTimeFormat.format(new Date(value)) : '—';
}

export function todayISO() {
  const now = new Date();
  const offset = now.getTimezoneOffset() * 60_000;
  return new Date(now.getTime() - offset).toISOString().slice(0, 10);
}

export function addDays(iso: string, days: number) {
  const date = new Date(`${iso}T00:00:00`);
  date.setDate(date.getDate() + days);
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 10);
}

export function humanize(value: string) {
  return value.replace(/_/g, ' ').toLowerCase().replace(/^\w/, (c) => c.toUpperCase());
}
