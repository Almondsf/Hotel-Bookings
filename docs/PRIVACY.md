# Personal data & the Nigeria Data Protection Act 2023

This is the record of processing for the PMS, for the hotel's Data Protection Officer. The hotel is the data controller; the hotel must publish its own privacy notice to guests and decide the retention periods below with its legal adviser.

## What is held, why, and for how long

| Data | Purpose (lawful basis) | Where | Retention |
|---|---|---|---|
| Guest name, email, phone, address, nationality, date of birth, company | Performing the booking contract; legal obligations (guest register) | `booking_guest` | Anonymised `GUEST_RETENTION_DAYS` after the last stay (default 6 years) |
| ID document type, number, expiry | Legal obligation / security (guest registration at check-in) | `booking_guestidentification`, number **encrypted** | Deleted `GUEST_ID_RETENTION_DAYS` after capture (default 365 days) |
| Stays, special requests | Contract | `booking_booking` | Kept for accounting; requests cleared on anonymisation |
| Bills, payments, invoices | Legal obligation (tax, FIRS: 6 years) | `billing_*` | Retained; invoice snapshots are a legal record |
| Card details | **Not held.** Guests pay on Paystack/Flutterwave pages | n/a | n/a |
| Messages sent (email/SMS/WhatsApp) | Contract (confirmations, reminders) | `notifications_notification` | Recipient cleared on anonymisation |
| Marketing consent | Consent (opt-in box at booking; never pre-ticked) | `accepts_marketing` | Until withdrawn |
| Staff accounts, sign-in history | Legitimate interest (security) | `authentication_user`, `audit_auditlog` | For employment + audit period |
| Audit log (who did what, IP) | Legitimate interest / legal (fraud prevention) | `audit_auditlog` (append-only) | Per hotel policy |

## Processors (third parties receiving personal data)

| Processor | Data | Purpose |
|---|---|---|
| Paystack / Flutterwave | Name, email, amount | Payment processing |
| Termii | Phone number, message text | SMS / WhatsApp |
| Email provider (configured SMTP) | Email, message | Confirmations, invoices |
| Channex (if enabled) and OTAs | Booking details | Distribution; OTA bookings arrive with guest data |
| Hosting provider | All (encrypted at rest per provider) | Infrastructure |

Data processing agreements should be in place with each. Transfers outside Nigeria (e.g. email or hosting providers abroad) must meet the NDPA's cross-border transfer conditions.

## Guests' rights: how staff handle requests

A manager (capability `privacy.manage`) uses the guest's profile in the web app:

- **Access / portability:** *Export data* downloads a JSON file of everything held. ID numbers are masked; if the guest wants the full number, show it in person (managers can reveal it, which is audited).
- **Erasure:** *Erase personal data* anonymises the guest. It's refused while they have a current/upcoming booking or an open bill. Bookings and invoices remain for tax law, without identifying details.
- **Rectification:** edit the profile (changes are audited by field name).
- **Withdraw consent / object:** untick marketing; set SMS opt-out.

Every export and erasure is recorded in the audit log. Respond to requests within the NDPA timelines.

## Security measures (summary)

Encryption in transit (HTTPS/HSTS) and of sensitive fields at rest, role-based least-privilege access, two-factor sign-in for privileged staff, rate-limited sign-in, append-only audit trail, no card data stored. Details: [SECURITY.md](SECURITY.md).

## Breach response

The audit log and request IDs support investigation. Under the NDPA the Commission must be notified of a breach likely to risk data subjects' rights within 72 hours, and affected guests informed where the risk is high. Keep this document, the backups, and the encryption key procedure in the incident plan.
