# User stories

What each person who uses the Hotel PMS needs to do, and how we know it works. Each story follows the usual form, **As a … I want … so that …**, followed by acceptance criteria: the conditions that must hold for the story to count as done.

These describe the system as built. Stories marked **(planned)** are not finished yet. For how the system works underneath, see [SYSTEM_OVERVIEW.md](SYSTEM_OVERVIEW.md).

**People**

| Persona | Who they are | Role in the system |
|---|---|---|
| [Guest](#guest) | Someone looking at or booking the hotel online | No account |
| [Receptionist](#receptionist) | Front-desk staff, day and night shift | `receptionist` |
| [Housekeeper](#housekeeper) | Cleans rooms | `housekeeping` |
| [Maintenance technician](#maintenance-technician) | Fixes faults | `maintenance` |
| [Outlet staff](#outlet-staff) | Waiters, bartenders, laundry attendants | `restaurant`, `bar`, `laundry` |
| [Accountant](#accountant) | Runs billing, company accounts and reports | `accountant` |
| [Manager](#manager) | Runs the hotel; configures prices and staff | `manager` |
| [Administrator](#administrator) | Technical owner of the installation | `admin` |
| [Any staff member](#any-staff-member) | Applies to everyone who signs in | any |

Story IDs (e.g. `G-3`) are stable, so they can be referenced in tickets and commits.

---

## Guest

**G-1 · Explore the hotel**
As a guest, I want to see what the hotel offers before booking, so that I can decide if it suits me.
- The home page shows the hotel's name, photos, rooms and suites with "rates from" prices, offers, dining, facilities, events, guest reviews, a photo gallery, contact details and policies.
- Each room type has its own page with a photo gallery, size, beds, capacity and the full list of amenities.
- The site works on a phone.

**G-2 · Check availability**
As a guest, I want to search by dates and number of guests, so that I only see rooms I can actually book.
- Arrival can't be in the past; departure must be after arrival.
- Only room types that fit the party and are free for every night are shown.
- Each room shows every rate I can book (e.g. room only, bed & breakfast, non-refundable saver) with the total for the stay **including taxes**, the meals included and whether it is refundable.
- Rates closed by the hotel for those dates (stop-sell, minimum stay…) are not offered.
- If nothing fits, I'm told so and invited to try other dates or contact the hotel.

**G-3 · Use a promo code**
As a guest with a promo code, I want to enter it when searching, so that I get the special rate.
- A valid code reveals its rate plan alongside the public rates; an invalid code shows only public rates.

**G-4 · Book and pay online**
As a guest, I want to book and pay in one go, so that my room is guaranteed.
- I enter my name, email and phone, can add special requests, and must accept the cancellation policy.
- Marketing consent is a separate, unticked box.
- I pay on Paystack's or Flutterwave's secure page; the hotel never sees my card.
- My room is held for 15 minutes while I pay. If I don't pay in time, the hold is released.
- When I return, I see my confirmation number once the payment is **verified with the gateway**, and I receive a confirmation email (and SMS if enabled).
- If my payment arrives too late and the room has gone, my money is refunded automatically and I'm told so.
- If online payment isn't available, I'm told how to book by phone or email instead of being shown a button that does nothing.

**G-5 · Manage my booking**
As a guest, I want to look up and cancel my booking myself, so that I don't have to call the hotel.
- I find it with my confirmation number and email; a wrong combination gives the same answer as a missing booking (no information leak), and repeated attempts are rate-limited.
- Before cancelling I see the policy and the exact fee if I cancel now.
- Cancelling within the free period costs nothing; later, the policy fee applies. I receive a cancellation email.

**G-6 · Be reminded before arrival**
As a guest, I want a reminder the day before I arrive, so that I have the hotel's details to hand.
- One reminder per booking, by email (and WhatsApp if enabled), never twice.

**G-7 · Control my data**
As a guest, I want my data handled lawfully, so that I can trust the hotel.
- I can ask for a copy of my data, or for it to be erased, and the hotel can do so from my profile (see M-14).
- I can opt out of SMS and marketing at any time.

---

## Receptionist

**R-1 · See today at a glance**
As a receptionist, I want a dashboard of today's work, so that I know what's coming.
- Shows occupancy tonight, arrivals expected and checked in, departures due, guests in house and unpaid online holds; each figure opens the matching filtered list.
- Lists today's arrivals (with status) and today's departures (with what each guest still owes).
- I can check guests in and out directly from these lists.

**R-2 · Use the room board**
As a receptionist, I want to see every room's state on one screen, so that I can place guests quickly.
- Rooms are grouped by floor, showing the guest in house, the arriving guest, departures today, cleaning status and out-of-order rooms; I can look at any date.
- Each room offers the next sensible action: **Check in** an arrival, **Check out** a departure, **Walk-in** or **Reserve** a vacant clean room, **Mark clean** (supervisors).

**R-3 · Take a reservation**
As a receptionist, I want to book rooms for callers and walk-ups, so that the hotel sells its rooms.
- I can pick a returning guest by name, email or phone, or enter a new one.
- I choose dates, one or several rooms (several rooms make a group), the source (phone, email, corporate, travel agent…), a rate plan, a company account and optionally a specific room.
- The system never double-books a room and tells me plainly if a room type is full.
- Company bookings get the company's negotiated rate when one exists.
- The booking is confirmed immediately and the guest is emailed.

**R-4 · Change a reservation**
As a receptionist, I want to change dates, room type, party size or requests, so that the booking matches what the guest wants.
- Prices are recalculated and availability re-checked; I'm told clearly if the change isn't possible.
- For in-house guests I can extend or shorten the stay, but not change the arrival date.

**R-5 · Check a guest in**
As a receptionist, I want to check guests in quickly and correctly, so that they get their room and the hotel meets its legal duties.
- I must record a valid ID document if none is on file (type, number, issuing country, expiry). The number is stored encrypted and shown masked afterwards.
- Check-in is refused, with the reason, if the room is dirty, out of order or still occupied, or if the arrival date hasn't come.
- The guest's bill (folio) opens automatically.

**R-6 · Walk-in**
As a receptionist, I want to book and check in an arriving guest in one step, so that they aren't kept waiting.
- From the dashboard or a vacant room on the room board: guest, departure date, party and ID in one form.
- If the check-in can't happen (no ID, room not ready), nothing is booked.

**R-7 · Check a guest out**
As a receptionist, I want to settle the bill and check out in one place, so that departures are quick.
- Tonight's room charges are posted first, so the balance shown is what's really owed.
- I can take the payment (card terminal, transfer or cash with a reference) and check out in one step, or bill the balance to the guest's company.
- Check-out is refused while money is owed and no company is billed.
- On check-out the bill closes with an invoice, the room is marked dirty for housekeeping, and the guest is emailed.

**R-8 · Move a guest**
As a receptionist, I want to move a guest to another room, so that I can handle complaints or faults.
- A reason is required; I can choose whether the new room type's rate applies to the remaining nights.

**R-9 · Cancel or mark a no-show**
As a receptionist, I want to cancel bookings and record no-shows, so that rooms go back on sale and the policy is applied.
- The policy fee is shown before confirming and posted to the guest's bill.
- Only managers and accountants can waive the fee, and a reason is then required and audited.

**R-10 · Handle money on a bill**
As a receptionist, I want to post charges and take payments, so that the bill is always right.
- Payments in Naira, or in USD/GBP/EUR converted at the current exchange rate.
- Card and transfer payments need a reference.
- I can send the guest a secure payment link for the balance (when online payment is set up).
- I can open a bill for someone not staying (an event client, a restaurant guest on account).
- I can print the bill and open the PDF invoice once issued.

**R-11 · Issue key cards**
As a receptionist, I want to encode key cards and cancel lost ones, so that only the guest can enter the room.
- Cards are valid until check-out time; "revoke all" cancels every active card for the stay.

**R-12 · Close the day (night shift)**
As the night receptionist, I want to run the night audit, so that the day's accounts are closed correctly.
- I see what blocks closing: guests due out still in house, arrivals not yet checked in.
- I can mark the remaining arrivals as no-shows in the same run.
- The run posts tonight's room charges, releases lapsed holds, freezes the day's figures and opens the next business day. Running it twice does no harm.

**R-13 · Know my guests**
As a receptionist, I want guest profiles with history and preferences, so that I can give personal service.
- Past and upcoming stays, notes (e.g. allergies, pillow preferences), VIP flag; VIPs are highlighted on the dashboard and room board.

---

## Housekeeper

**H-1 · Know which rooms to clean**
As a housekeeper, I want today's cleaning list, so that I clean the right rooms in the right order.
- The list is generated automatically: departure cleans for rooms guests leave, stay-over service for occupied rooms.
- Rooms with a guest arriving today are flagged **Rush** and sorted first.
- I can filter to my own tasks.

**H-2 · Record my work**
As a housekeeper, I want to start, finish or skip tasks, so that the front desk knows when rooms are ready.
- Finishing a task marks the room Clean, which makes it available for check-in.
- Skipping requires a reason (e.g. Do Not Disturb).

**H-3 · Report a fault**
As a housekeeper, I want to report broken things I find, so that they get fixed (see S-5).

---

## Maintenance technician

**T-1 · See and work tickets**
As a technician, I want a list of open faults by priority, so that I fix the most urgent first.
- I can start a ticket, put it on hold (waiting for parts or a vendor), and resolve it with notes on what was done.
- Resolving a ticket that took a room out of order puts the room back on sale and marks it dirty for cleaning.

**T-2 · Take a room out of order**
As a technician or manager, I want to block a room while it's repaired, so that nobody is sold a broken room.
- I set the date it will be ready; the room is off sale until then.
- I'm shown any bookings in that period so the desk can move them.

---

## Outlet staff

**O-1 · Take an order**
As a waiter or bartender, I want to ring up orders quickly, so that I can serve guests without delay.
- I only see the outlets my role is allowed to sell at.
- Tapping an item starts an order if none is open; I can name it by table, seat or room.
- Several orders can be open at once and I can switch between them.
- Sold-out items (tracked stock at zero) can't be added.

**O-2 · Charge to a room**
As a waiter, I want to charge an in-house guest's order to their room, so that they pay at check-out.
- I must enter the room number **and** the guest's surname; it must match an in-house guest, so nobody can charge a random room.
- The items appear on the guest's bill with the right taxes.

**O-3 · Take payment at the table**
As a waiter, I want to take cash, card or transfer on the spot, so that non-residents can pay.
- Cash shows the change due; card and transfer need a reference.
- A receipt (invoice) is issued.

**O-4 · Void an order**
As a manager, I want to void an order before it's paid, with a reason, so that mistakes don't become revenue.

---

## Accountant

**A-1 · Correct bills safely**
As an accountant, I want to void charges and payments, move charges between bills and give allowances, so that bills are right without hiding anything.
- Every correction needs a reason and is recorded in the audit log; nothing is ever deleted.
- A **Discount** takes an amount off the bill before tax; the VAT and levies on it are reduced to match. It needs a reason and only managers and accountants can give one.

**A-2 · Refund guests**
As an accountant, I want to refund a guest who is in credit (e.g. an unused deposit), so that they get their money back.
- Refund amount, method, reference and reason are recorded.
- For an online payment I can **Refund to card**: the money goes back through Paystack or Flutterwave to the card or account the guest paid with. This is offered only while the guest is in credit, for no more than they're owed or than is left of that payment.
- Online payments can't be voided (the card would stay charged); they're corrected with a refund to the card instead.

**A-3 · Run company (city-ledger) accounts**
As an accountant, I want to manage companies that pay on credit, so that corporate business is billed and collected.
- I can add and edit companies (contact, TIN, credit limit, payment terms) and deactivate them.
- Billing a guest's bill to a company is refused if it would exceed the credit limit.
- Each company has a statement of bills charged and payments received, which I can print.
- I record company payments against their balance.
- The city-ledger report ages what each company owes.

**A-4 · Report on the business**
As an accountant or manager, I want standard hotel reports, so that I can manage revenue and reconcile cash.
- Occupancy, ADR and RevPAR per day, actual for past days and "on the books" for future days.
- Revenue by department with taxes collected (for VAT returns).
- Payments by method and by staff member (cashier reconciliation).
- Guest ledger (open bills) and city ledger.
- POS sales by outlet and best sellers.
- Every table can be exported to CSV.

**A-5 · Configure taxes and currencies**
As an accountant, I want to set tax rates and exchange rates, so that bills follow the law and today's rates.
- Tax changes apply to charges posted from then on; past charges keep the tax they were charged.
- Setting an exchange rate keeps the history used by past payments.

**A-6 · Invoices that satisfy the tax authority**
As an accountant, I want gapless, immutable invoices, so that the hotel's records pass an audit.
- Invoice numbers run without gaps per year (`INV-2026-000123`); an issued invoice can't be changed or deleted and has a PDF.

---

## Manager

**M-1 · Set room prices and rooms**
As a manager, I want to edit room types and rooms, so that what we sell matches the building.
- I can change a room type's name, description, base price, capacity, beds and size, and add new room types.
- I can add rooms, change a room's type, floor and notes, and take a room out of service (e.g. renovation) or back.
- Occupancy and maintenance status can't be changed by hand: they follow check-in/out and tickets.
- Existing bookings keep the prices agreed when they were made.

**M-2 · Create rate plans**
As a manager, I want packages and special rates, so that we sell to different kinds of guest.
- A plan is a percentage of the best available rate or has its own prices per room type and dates.
- I choose meals included, who can book it (everyone, staff only, a promo code, one company), minimum/maximum stay, how far ahead it must be booked, on-sale dates, and whether it's refundable.

**M-3 · Control selling by date**
As a manager, I want stop-sells and minimum stays for busy dates, so that I protect revenue at peak times.
- Restrictions by date range, room type and rate plan: stop sell, closed to arrival, closed to departure, minimum stay. They apply to the website and channels; staff can still book and see why.

**M-4 · Agree a special rate**
As a manager, I want to set a custom nightly rate on a booking, so that I can close a deal.
- Only managers can do it, a reason is required, and it is audited.

**M-5 · Manage menus**
As a manager, I want to edit outlet menus, so that what staff sell is current.
- Add and edit items with section, price, tax category and availability; track stock with a low-stock warning; take items off sale with one click.

**M-6 · Manage staff**
As a manager, I want to control who can use the system, so that access matches people's jobs.
- I invite staff by email; they set their own password. There is no public sign-up.
- I can change a person's name, phone and role, resend an invite, reset their two-factor sign-in, and deactivate or reactivate them.
- I can't create or manage managers or administrators, or change my own role.
- Deactivating someone or changing their role signs them out everywhere.

**M-7 · See who did what**
As a manager, I want an audit log, so that I can investigate mistakes and fraud.
- Sign-ins (including failures), staff changes, bookings, money movements, ID reveals, price changes, night audits and privacy actions are recorded with who, when and from which IP. Entries can't be edited or deleted.

**M-8 · Reveal a guest's ID**
As a manager, I want to see a guest's full ID number when there's a legitimate need, so that I can help the police or verify identity.
- Only managers can reveal it; each reveal is audited.

**M-9 · Read the daily flash report**
As a manager, I want each closed day's key figures frozen, so that I can compare days reliably.

**M-10 · Connect online channels** *(planned: needs Channex certification)*
As a manager, I want our rooms on Booking.com and Expedia, so that we reach more guests.
- Availability, prices and restrictions are pushed automatically; OTA bookings arrive as reservations.
- OTA bookings that can't be placed (no room, unknown room mapping) are kept and flagged for staff instead of being lost.

**M-11 · Handle data-protection requests** (privacy, NDPA)
As a manager, I want to export or erase a guest's data, so that the hotel meets the NDPA.
- Export gives everything held about the guest as a file.
- Erasure anonymises the guest but keeps bookings and invoices (required by tax law). It's refused while the guest has a current or upcoming stay or an open bill.
- Old guests and old ID documents are anonymised or deleted automatically after the retention periods.

---

## Administrator

**X-1 · Full control**
As an administrator, I want every permission, including managing managers, so that someone can always fix access.

**X-2 · Configure the installation**
As an administrator, I want hotel details, policies and integrations set by configuration, so that the same software fits this hotel without code changes.
- Hotel name and contacts, check-in/out times, cancellation policy, hold time, ID and clean-room requirements, payment gateways, SMS/WhatsApp, door locks, retention periods: all environment settings (see the system overview).
- A payment gateway only appears to guests and staff once its keys are configured.

**X-3 · Enforce two-factor sign-in**
As an administrator, I want privileged roles to use two-factor sign-in, so that a stolen password isn't enough.
- With `ENFORCE_MFA` on, admins, managers and accountants must enrol before using the system.

**X-4 · Demo and test data**
As a developer or salesperson, I want a realistic demo hotel, so that I can show and test the system.
- `manage.py seed_demo` builds a hotel with two weeks of consistent history and accounts for every role; `--reset` starts again. It refuses to run outside development.

---

## Any staff member

**S-1 · Sign in securely**
As a staff member, I want to sign in with my email and password (and an authenticator code if I've turned it on), so that only I can use my account.
- Wrong passwords are rate-limited per IP and per account; failures are audited.
- Reloading pages doesn't sign me out, even when several desk computers share one internet connection.

**S-2 · Reset a forgotten password**
As a staff member, I want to reset my password by email, so that I'm not locked out.
- The answer is the same whether or not the email exists; the link expires.

**S-3 · Manage my own account**
As a staff member, I want to change my password and set up two-factor sign-in, so that my account stays safe.
- After changing my password I'm signed out everywhere and told why on the sign-in page.
- I can turn two-factor off only if my role doesn't require it, and only with my password.

**S-4 · Only see what I'm allowed to**
As a staff member, I want the menu to show only my tools, so that the system is simple to use.
- Each role sees only its pages and buttons; the server refuses anything else, even if called directly.

**S-5 · Report a fault**
As any staff member, I want to report a broken item in a room or public area, so that maintenance knows about it.
- Room or location, category, priority and description.
