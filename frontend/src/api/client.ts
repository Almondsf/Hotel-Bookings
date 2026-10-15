/**
 * API client. The access token lives only in memory; the refresh token is an
 * httpOnly cookie the browser sends to /api/auth/ (JavaScript can't read it).
 * A 401 triggers one silent refresh and a retry.
 */
let accessToken: string | null = null;
let refreshing: Promise<boolean> | null = null;
let onSessionExpired: () => void = () => {};

export function setAccessToken(token: string | null) {
  accessToken = token;
}

export function setSessionExpiredHandler(handler: () => void) {
  onSessionExpired = handler;
}

export class ApiError extends Error {
  status: number;
  data: unknown;

  constructor(status: number, data: unknown) {
    super(describeError(data) || `Request failed (${status})`);
    this.status = status;
    this.data = data;
  }

  /** Field-level messages from DRF validation errors. */
  fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {};
    if (this.data && typeof this.data === 'object') {
      for (const [key, value] of Object.entries(this.data as Record<string, unknown>)) {
        if (key !== 'error' && key !== 'detail') out[key] = flatten(value);
      }
    }
    return out;
  }
}

function flatten(value: unknown): string {
  if (Array.isArray(value)) return value.map(flatten).join(' ');
  if (value && typeof value === 'object') return Object.entries(value).map(([k, v]) => `${k}: ${flatten(v)}`).join('; ');
  return String(value ?? '');
}

function describeError(data: unknown): string {
  if (!data || typeof data !== 'object') return '';
  const record = data as Record<string, unknown>;
  if (record.error) return flatten(record.error);
  if (record.detail) return flatten(record.detail);
  if (record.non_field_errors) return flatten(record.non_field_errors);
  return Object.entries(record).map(([k, v]) => `${k.replace(/_/g, ' ')}: ${flatten(v)}`).join(' · ');
}

export async function refreshSession(): Promise<boolean> {
  if (!refreshing) {
    refreshing = fetch('/api/auth/refresh/', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    })
      .then(async (response) => {
        if (!response.ok) return false;
        setAccessToken((await response.json()).access);
        return true;
      })
      .catch(() => false)
      .finally(() => {
        refreshing = null;
      });
  }
  return refreshing;
}

type Options = { method?: string; body?: unknown; query?: Record<string, string | number | boolean | undefined | null> };

function buildUrl(path: string, query?: Options['query']) {
  const url = new URL(path.startsWith('/') ? path : `/api/${path}`, window.location.origin);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== '') url.searchParams.set(key, String(value));
  }
  return url.pathname + url.search;
}

async function send(path: string, options: Options, raw: boolean): Promise<Response> {
  const headers: Record<string, string> = { Accept: raw ? '*/*' : 'application/json', 'X-Auth-Mode': 'cookie' };
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  return fetch(buildUrl(path, options.query), {
    method: options.method ?? 'GET',
    headers,
    credentials: 'same-origin',
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
}

async function request(path: string, options: Options = {}, raw = false): Promise<Response> {
  let response = await send(path, options, raw);
  if (response.status === 401 && !path.includes('/auth/login')) {
    if (await refreshSession()) {
      response = await send(path, options, raw);
    } else {
      setAccessToken(null);
      onSessionExpired();
    }
  }
  if (!response.ok) {
    let data: unknown = null;
    try {
      data = await response.json();
    } catch {
      /* not JSON */
    }
    throw new ApiError(response.status, data);
  }
  return response;
}

export async function api<T>(path: string, options: Options = {}): Promise<T> {
  const response = await request(path, options);
  if (response.status === 204 || response.status === 205) return undefined as T;
  return response.json() as Promise<T>;
}

/**
 * Fetch a file (e.g. an invoice PDF) with auth and show it in a new tab.
 * The tab is opened straight away, while still handling the click: browsers
 * block pop-ups opened after waiting for a download.
 */
export async function openFile(path: string) {
  const tab = window.open('', '_blank');
  try {
    const response = await request(path, {}, true);
    const url = URL.createObjectURL(await response.blob());
    if (tab) {
      tab.location.href = url;
      tab.opener = null;
    } else {
      saveBlobUrl(url, fileName(response, 'document'));  // pop-ups blocked anyway: download instead
    }
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  } catch (error) {
    tab?.close();
    throw error;
  }
}

/** Fetch a file (CSV or JSON export) with auth and save it under the server's file name. */
export async function downloadFile(path: string, fallbackName: string) {
  const response = await request(path, {}, true);
  const url = URL.createObjectURL(await response.blob());
  saveBlobUrl(url, fileName(response, fallbackName));
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

function fileName(response: Response, fallback: string) {
  const disposition = response.headers.get('Content-Disposition') ?? '';
  return /filename="?([^";]+)"?/.exec(disposition)?.[1] ?? fallback;
}

function saveBlobUrl(url: string, name: string) {
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
}

export const post = <T>(path: string, body: unknown = {}) => api<T>(path, { method: 'POST', body });
export const patch = <T>(path: string, body: unknown) => api<T>(path, { method: 'PATCH', body });
