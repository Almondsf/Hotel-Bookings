# Security controls

## Identity & access
- No public sign-up: managers invite staff by email; people set their own passwords (Django's strength validators).
- Role-based **capabilities** (`authentication/permissions.py`): every endpoint checks a capability, never a role name. Managers can't create or manage managers/admins; nobody can change their own role or deactivate themselves.
- **Two-factor sign-in (TOTP)** with single-use recovery codes and replay protection; required for admin/manager/accountant roles once `ENFORCE_MFA=True`.
- Access tokens last 15 minutes; refresh tokens rotate and are blacklisted. In the browser the refresh token is an **httpOnly, SameSite=Strict cookie** scoped to `/api/auth/`; the access token is kept only in memory.
- Password change/reset, deactivation, role change and MFA reset revoke all of a user's sessions.
- Sign-in, password reset, MFA, booking lookup and payment verification are **rate limited** per IP and per account.

## Data
- Guest ID numbers, MFA secrets and integration credentials are **encrypted at rest** (Fernet; `FIELD_ENCRYPTION_KEYS`, rotatable). ID numbers are masked everywhere except a manager-only, audited reveal.
- Card data never touches the system (hosted checkout pages); stored gateway responses are stripped of card/customer details.
- Money records are never deleted: charges and payments are voided with a reason; invoices are immutable and gaplessly numbered.
- Business rules are also enforced by database constraints (dates, amounts, one posting per night, one open business day).

## Integrations
- Payment outcomes are always verified server-side with the gateway; webhook signatures (Paystack HMAC-SHA512, Flutterwave hash) are checked in constant time; amount and currency must match; settlement is idempotent under a row lock.
- Channel-manager and lock-bridge webhooks/requests use shared secrets / HMAC; inbound OTA payloads are treated as untrusted.
- Payment redirect URLs are fixed server-side (no open redirects). CSV exports neutralise spreadsheet formulas. PDF text is escaped.

## Platform
- `DEBUG=False` enables HTTPS redirect, HSTS (1 year, preload), secure cookies, `nosniff`, `DENY` framing and a strict referrer policy; `manage.py check --deploy` runs clean in CI.
- Content-Security-Policy on Django pages (admin, API docs) and on the web app via nginx.
- Proxy client IPs are only trusted for `NUM_PROXIES` hops (no spoofed `X-Forwarded-For`).
- The API is JSON-only in production; the browsable API and session auth exist only in development.
- Append-only **audit log** of sign-ins (including failures), staff changes, money movements, ID reveals, rate changes, night audits and privacy actions, with actor and IP.
- API docs are restricted to Django-admin staff.

## Before go-live
- Independent penetration test of the deployed system.
- Confirm backups and a restore; store the encryption key safely.
- Enrol privileged staff in two-factor sign-in and set `ENFORCE_MFA=True`.
- Change `DJANGO_ADMIN_URL` from the default.
