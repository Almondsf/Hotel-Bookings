# Deployment

## Option A: Docker Compose (single server)

Requires Docker and a domain with TLS in front (Cloudflare, a load balancer, or certbot on the host).

```bash
cp .env.example .env
# Required in .env:
#   DJANGO_SECRET_KEY            long random string
#   FIELD_ENCRYPTION_KEYS        python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
#   POSTGRES_PASSWORD
#   DJANGO_ALLOWED_HOSTS         e.g. pms.yourhotel.com
#   DJANGO_CSRF_TRUSTED_ORIGINS  e.g. https://pms.yourhotel.com
#   FRONTEND_URL                 e.g. https://pms.yourhotel.com
#   HOTEL_NAME, HOTEL_ADDRESS, HOTEL_PHONE, HOTEL_EMAIL, HOTEL_TAX_ID
#   EMAIL_BACKEND + SMTP settings (or a provider such as Mailgun/SES)
#   PAYSTACK_SECRET_KEY / FLUTTERWAVE_SECRET_KEY / FLUTTERWAVE_WEBHOOK_HASH
# CACHE_URL is set by docker-compose (its Redis); outside Docker set it yourself (see Scaling)
docker compose up -d --build
docker compose exec api python manage.py createsuperuser
```

Services: `db` (Postgres 16), `redis` (shared cache), `api` (gunicorn; runs migrations on start), `worker` (background jobs and schedules), `web` (nginx serving the web app and proxying `/api`).

### Back up the encryption key

`FIELD_ENCRYPTION_KEYS` encrypts guest ID numbers, two-factor secrets and channel-manager credentials. **Without it that data is unrecoverable.** Store it in your password manager and with the database backups (separately from them).

To rotate: put a new key first (`NEW,OLD`), restart, re-save the affected rows, then remove the old key.

## After the first deploy

1. **Admin user:** sign in to `/admin/` (or the path set in `DJANGO_ADMIN_URL`) and create your room types, rooms and rate plans, or import them.
2. **Staff:** invite staff from the web app (Staff page). They set their own passwords.
3. **Two-factor sign-in:** managers, accountants and admins enrol under *My account*. When all have, set `ENFORCE_MFA=True`.
4. **Taxes:** VAT 7.5% is on. Enable service charge / consumption tax under Tax rules if the hotel charges them.
5. **Payments:** in the Paystack/Flutterwave dashboards set the webhook URLs:
   - `https://<host>/api/payments/webhooks/paystack/`
   - `https://<host>/api/payments/webhooks/flutterwave/` (and the secret hash = `FLUTTERWAVE_WEBHOOK_HASH`)
6. **Channel manager (optional):** add the Channex connection and room/rate mappings in the admin, and point Channex's booking webhook to `https://<host>/api/distribution/webhooks/channex/` with header `X-Webhook-Secret`. Certify against Channex staging before switching `CHANNEX_BASE_URL` to production.
7. **Door locks (optional):** `LOCK_SYSTEM=bridge` with the URL and shared secret from your lock vendor's integration bridge.
8. **Night audit:** run it nightly from the web app (Night audit page). It posts room charges and rolls the business date.

## Backups

```bash
# Daily, kept 30+ days, copied off the server
docker compose exec -T db pg_dump -U hotel -Fc hotel > backup-$(date +%F).dump
# Restore
docker compose exec -T db pg_restore -U hotel -d hotel --clean < backup-YYYY-MM-DD.dump
```

Test a restore at least quarterly.

## Monitoring

- `GET /api/health/` returns 200 when the app can reach its database (used by the container health check; point an uptime monitor at it too).
- Logs are JSON lines on stdout with a `request_id`; responses carry `X-Request-ID` so staff can quote it when reporting problems.
- Watch the `jobs_backgroundjob` table for `FAILED` jobs (failed emails/SMS/syncs), and the Online channels page for OTA bookings needing attention.

## Scaling for traffic

What the stack already does, and the knobs (all in `.env`):

- **Shared cache (Redis).** Rate limits, the sign-in grace window and cached public pages live in Redis (`CACHE_URL=redis://redis:6379/0`, set by docker-compose), so every server process and every extra server sees the same counters. `manage.py check --deploy` warns (`hotel.W001`) if production runs on a per-process cache.
- **Database connection pool.** PostgreSQL connections are pooled per server process instead of opened per request (`DB_POOL=True`, `DB_POOL_MIN_SIZE=2`, `DB_POOL_MAX_SIZE=10`). Keep `DB_POOL_MAX_SIZE` at least `GUNICORN_THREADS`, and workers × pool size × API containers under PostgreSQL's `max_connections` (100 by default). With a connection pooler such as PgBouncer in front, set `DB_POOL=False` (connections are then kept for `DB_CONN_MAX_AGE` seconds).
- **Gunicorn** (`deploy/gunicorn.conf.py`): threaded workers, so requests waiting on a payment gateway don't block the rest. `GUNICORN_WORKERS` (default 2 × CPUs + 1, at most 9), `GUNICORN_THREADS` (4), `GUNICORN_TIMEOUT` (60 s). Each container serves workers × threads requests at once.
- **nginx** (`deploy/nginx.conf`): gzip for scripts, styles and API JSON; keep-alive connections to the API; hashed assets cached for a year; a per-address limit of 30 API requests a second (burst 60) that answers 429 before the app is touched. **Behind Cloudflare or a load balancer**, uncomment `set_real_ip_from` / `real_ip_header` in `nginx.conf`, or every guest shares the proxy's address and one limit. The security headers live in `deploy/security-headers.conf`, included in every location.
- **Cached public pages.** Room types (list and detail), loaded by every page of the guest site, are cached for `PUBLIC_CACHE_SECONDS` (300). Any change to a room type, room, photo or amenity clears them at once. Availability search is never cached.
- **More servers.** Sign-in is by token and all shared state is in PostgreSQL and Redis, so you can run several `api` containers (`docker compose up -d --scale api=3`) and nginx spreads requests across them. Run one `worker` per server or more; jobs are claimed with row locks, so workers never run the same job twice.

**Load test before a big promotion** (staging, never the live hotel):

```bash
python deploy/loadtest.py --base-url https://staging.yourhotel.com --users 50 --duration 120
```

Simulated guests browse, open rooms and search (some as large groups). It prints requests per second and p50/p95/p99 response times per endpoint, and exits non-zero when the slowest p95 is over `--p95-ms` (800) or more than 1% of requests fail. Rate limits are per address, so on staging raise nginx's limit and `THROTTLE_ANON` for the test (or run it from several machines); 429s are counted separately.

## Option B: without Docker

Python 3.12, PostgreSQL 14+, Redis 7, nginx. Install requirements plus `gunicorn`, set the same environment variables (including `CACHE_URL=redis://localhost:6379/0`), run `migrate` and `collectstatic`, serve `frontend/dist` with nginx using `deploy/nginx.conf` (with `deploy/security-headers.conf` at `/etc/nginx/snippets/`, and the `api` upstream pointed at your gunicorn address), and run two systemd services: `gunicorn hotel.wsgi --config deploy/gunicorn.conf.py` and `python manage.py run_worker`.
