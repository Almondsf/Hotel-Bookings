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
docker compose up -d --build
docker compose exec api python manage.py createsuperuser
```

Services: `db` (Postgres 16), `api` (gunicorn; runs migrations on start), `worker` (background jobs and schedules), `web` (nginx serving the web app and proxying `/api`).

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

## Option B: without Docker

Python 3.12, PostgreSQL 14+, nginx. Install requirements plus `gunicorn`, set the same environment variables, run `migrate` and `collectstatic`, serve `frontend/dist` with nginx using `deploy/nginx.conf`, and run two systemd services: `gunicorn hotel.wsgi` and `python manage.py run_worker`.
