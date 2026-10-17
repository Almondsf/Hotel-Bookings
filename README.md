# Hotel PMS

A property management system for a full-service hotel, built for Nigerian operations: Naira-first billing with VAT, Paystack and Flutterwave payments, guest ID capture at check-in, NDPA 2023 data-protection tooling and SMS/WhatsApp via Termii.

## What it does

| Area | Highlights |
|---|---|
| Reservations | Online and staff bookings, group/multi-room (one email per group; check in, check out or cancel the whole group, by staff or, for cancelling, the guest online), rate plans (BAR, packages, corporate, promo codes), modifications with re-pricing, configurable cancellation & no-show policy, expiring payment holds |
| Front desk | Room board, walk-ins, check-in with encrypted ID capture, room moves, key cards, check-out |
| Billing | Guest folios, nightly room posting, extras, voids & allowances with reasons, split bills, NGN + foreign-currency payments, refunds, city ledger (corporate accounts), gapless invoice numbering, PDF invoices |
| Payments | Paystack & Flutterwave checkout, signed webhooks, server-side verification, automatic refund when a late payment can't get a room |
| Operations | Housekeeping tasks and room status, maintenance tickets with out-of-order blocking, POS for restaurant / bar / room service / laundry |
| Management | Night audit with business date, occupancy / ADR / RevPAR, revenue & VAT, cashier and ledger reports (CSV export), audit log of every sensitive action |
| Distribution | Channel manager (Channex) two-way sync, door-lock adapter |
| Guests | Public booking site, booking lookup and self-cancellation, email + SMS/WhatsApp notifications |
| Security & compliance | Role-based capabilities, short-lived JWT + httpOnly refresh cookie, TOTP two-factor sign-in, throttling, encrypted PII, NDPA export / erasure / retention |

## Architecture

- **API:** Django 6 + Django REST Framework (`/api/...`), PostgreSQL in production.
- **Web app:** React + TypeScript (Vite) in `frontend/`: the public website (`/`), the guest booking engine (`/book`) and the staff portal (`/login`, then `/dashboard`).
- **Background jobs:** Django's task framework with a database-backed queue (`jobs` app); run `python manage.py run_worker`.
- One Django app per domain: `booking`, `billing`, `payments`, `rates`, `rooms`, `housekeeping`, `maintenance`, `pos`, `nightaudit`, `notifications`, `distribution`, `locks`, `privacy`, `audit`, `authentication`, `jobs`. Business rules live in each app's `services.py` / `lifecycle.py`, not in views.

## Local development

```bash
python -m venv venv && venv\Scripts\activate     # Windows (source venv/bin/activate elsewhere)
pip install -r requirements.txt
copy .env.example .env                           # then set DJANGO_SECRET_KEY etc.
python manage.py migrate
python manage.py seed_demo                       # demo hotel with two weeks of history (DEBUG only)
python manage.py runserver

cd frontend && npm install && npm run dev        # http://localhost:3000 (proxies /api to :8000)
```

`seed_demo` creates an administrator `admin@demo.hotel` and an account for every role (password `DemoPass#2026` for all). The public site is at http://localhost:3000/ and the staff portal at http://localhost:3000/login.

Tests: `python manage.py test` (backend), `npm test` and `npm run typecheck` (frontend), `npm run e2e` (browser tests; see docs/SYSTEM_OVERVIEW.md §16). CI runs all of them on every push (`.github/workflows/ci.yml`).

## Documentation

- [docs/SYSTEM_OVERVIEW.md](docs/SYSTEM_OVERVIEW.md): what the system does and how it's built (features, architecture, data model, key flows, roles, API, jobs, integrations, configuration). Start here if you're new.
- [docs/USER_STORIES.md](docs/USER_STORIES.md): what each kind of user needs to do, with acceptance criteria.

## Production

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). Security controls are summarised in [docs/SECURITY.md](docs/SECURITY.md) and personal-data handling in [docs/PRIVACY.md](docs/PRIVACY.md).

API reference (staff with Django admin access): `/api/docs/`.
