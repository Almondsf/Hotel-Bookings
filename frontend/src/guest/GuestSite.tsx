import { useMutation, useQuery } from '@tanstack/react-query';
import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';

import { api, ApiError, post } from '../api/client';
import { ErrorAlert, Field, fieldError, Loading } from '../components/ui';
import { setMonogramFavicon } from '../lib/favicon';
import { addDays, formatDate, formatDateTime, formatMoney, todayISO } from '../lib/format';
import './guest.css';
import './home.css';

interface HotelInfo {
  name: string; address: string; phone: string; email: string; check_in_time: string; check_out_time: string;
  cancellation_policy: string; payment_gateways: string[];
}

interface RatePlanOffer {
  code: string; name: string; description: string; meal_plan_name: string; is_refundable: boolean;
  total_price: string; taxes: string; total_with_taxes: string;
  free_cancellation_until: string | null; free_cancellation_passed: boolean;
}

interface RoomOffer {
  id: number; name: string; description: string; max_adults: number; max_children: number; bed_type: string;
  size: number; primary_image: string | null; rate_plans: RatePlanOffer[];
}

interface GroupPlan {
  label: string;
  rooms: { room_type_id: number; room_type_name: string; primary_image: string | null; number_of_adults: number; number_of_children: number }[];
  total_price: string; taxes: string; total_with_taxes: string; price_per_night: string;
  free_cancellation_until: string | null; free_cancellation_passed: boolean;
}

interface SearchResults { room_types: RoomOffer[]; group_plans: GroupPlan[] | null; other_room_types: RoomOffer[] | null }

/** A group plan travels to checkout in the URL as "roomTypeId:adults:children,…". */
const encodePlan = (plan: GroupPlan) => plan.rooms.map((r) => `${r.room_type_id}:${r.number_of_adults}:${r.number_of_children}`).join(',');
function decodePlan(value: string | null) {
  if (!value) return null;
  const rooms = value.split(',').map((part) => part.split(':').map(Number))
    .filter((n) => n.length === 3 && n.every(Number.isFinite))
    .map(([room_type, number_of_adults, number_of_children]) => ({ room_type, number_of_adults, number_of_children }));
  return rooms.length >= 2 ? rooms : null;
}

/** How a rate's cancellation terms read for the dates searched. */
function cancellationNote(terms: { free_cancellation_until: string | null; free_cancellation_passed: boolean }) {
  if (terms.free_cancellation_until === null) return 'Non-refundable';
  if (terms.free_cancellation_passed) return 'No free cancellation for these dates';
  return `Free cancellation until ${formatDateTime(terms.free_cancellation_until)}`;
}

/** Carried to checkout so the guest is warned before paying ("none" = non-refundable). */
const termsParam = (terms: { free_cancellation_until: string | null }) => terms.free_cancellation_until ?? 'none';

const party = (adults: number | string, children: number | string) =>
  `${adults} adult${Number(adults) === 1 ? '' : 's'}${Number(children) ? `, ${children} child${Number(children) === 1 ? '' : 'ren'}` : ''}`;

interface Confirmation {
  refunded?: string;
  group_reference?: string | null;
  number_of_adults: number; number_of_children: number;
  confirmation_number: string; status: string; room_type_name: string; check_in_date: string; check_out_date: string;
  total_with_taxes: string; cancellation_policy: string; cancellation_fee_if_cancelled_now: string | null;
  rate_plan: { name: string; is_refundable: boolean };
  guest: { first_name: string; last_name: string; email: string };
}

export function useHotel() {
  return useQuery({ queryKey: ['hotel'], queryFn: () => api<HotelInfo>('hotel/'), staleTime: 3_600_000 });
}

/** `wide` lets a page (the home page) run edge to edge instead of in the centred booking column. */
export function GuestLayout({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  const hotel = useHotel();
  useEffect(() => {
    if (!hotel.data) return;
    document.title = hotel.data.name;
    setMonogramFavicon(hotel.data.name);
  }, [hotel.data]);
  // On the home page the header floats over the hero photo and turns solid once you scroll
  const [scrolled, setScrolled] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 40);
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);
  const city = hotel.data?.address?.split(',').slice(-2).join(',').trim();

  return (
    <div className={`guest${wide ? ' guest--home' : ''}`}>
      <header className={`guest-header${wide && !scrolled && !menuOpen ? ' overlay' : ''}${menuOpen ? ' open' : ''}`}>
        <Link to="/" className="guest-brand" onClick={() => setMenuOpen(false)}>
          <span className="guest-monogram" aria-hidden="true">{(hotel.data?.name ?? 'H').charAt(0)}</span>
          <span>{hotel.data?.name ?? 'Hotel'}{city && <small>{city}</small>}</span>
        </Link>
        <button type="button" className="guest-menu-toggle" aria-expanded={menuOpen} aria-controls="site-nav"
                onClick={() => setMenuOpen(!menuOpen)}>{menuOpen ? 'Close' : 'Menu'}</button>
        <nav className="guest-nav" aria-label="Site" id="site-nav" onClick={() => setMenuOpen(false)}>
          <a href="/#rooms">Rooms</a>
          <a href="/#offers">Offers</a>
          <a href="/#dining">Dining</a>
          <a href="/#facilities">Facilities</a>
          <a href="/#events">Events</a>
          <a href="/#contact">Contact</a>
          <Link to="/book" className="button guest-book">Book now</Link>
        </nav>
      </header>
      <main className={wide ? 'guest-wide' : 'guest-main'}>{children}</main>
      <section className="guest-closing" aria-label="Book your stay">
        <span className="home-kicker">Your stay begins here</span>
        <h2>Come and stay with us</h2>
        <Link to="/book" className="button primary guest-cta">Check availability</Link>
      </section>
      <footer className="guest-footer">
        <div className="guest-footer-grid">
          <div>
            <h4>{hotel.data?.name ?? 'Hotel'}</h4>
            {hotel.data?.address && <p>{hotel.data.address}</p>}
            {hotel.data && <p>{[hotel.data.phone, hotel.data.email].filter(Boolean).join(' · ')}</p>}
            {hotel.data && <p>Check-in from {hotel.data.check_in_time} · Check-out by {hotel.data.check_out_time}</p>}
          </div>
          <div>
            <h4>Explore</h4>
            <ul>
              <li><a href="/#rooms">Rooms & suites</a></li>
              <li><a href="/#dining">Dining</a></li>
              <li><a href="/#facilities">Facilities</a></li>
              <li><a href="/#gallery">Gallery</a></li>
            </ul>
          </div>
          <div>
            <h4>Your stay</h4>
            <ul>
              <li><Link to="/book">Book a room</Link></li>
              <li><Link to="/booking/manage">Manage my booking</Link></li>
              <li><a href="/#contact">Contact & policies</a></li>
            </ul>
          </div>
        </div>
        <div className="guest-footer-legal">
          <span>© {new Date().getFullYear()} {hotel.data?.name ?? 'Hotel'}. All rights reserved.</span>
          <Link to="/login">Staff sign in</Link>
        </div>
      </footer>
    </div>
  );
}

function nights(from: string, to: string) {
  return Math.round((new Date(to).getTime() - new Date(from).getTime()) / 86_400_000);
}

export function SearchPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [form, setForm] = useState({
    check_in: params.get('check_in') ?? todayISO(),
    check_out: params.get('check_out') ?? addDays(todayISO(), 1),
    adults: params.get('adults') ?? '2',
    children: params.get('children') ?? '0',
    promo_code: params.get('promo_code') ?? '',
  });
  const searched = params.has('check_in');
  const query = Object.fromEntries(params.entries());
  const results = useQuery({
    queryKey: ['guest-search', query],
    queryFn: () => api<SearchResults>('rooms/search/', { query }),
    enabled: searched,
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    setParams(Object.fromEntries(Object.entries(form).filter(([, v]) => v !== '')));
  }

  const stay = nights(params.get('check_in') ?? '', params.get('check_out') ?? '');
  return (
    <GuestLayout>
      <section className="guest-hero">
        <h1>Book your stay</h1>
        <form className="guest-search" onSubmit={submit}>
          <Field label="Arrival"><input type="date" required min={todayISO()} value={form.check_in}
                                        onChange={(e) => setForm({ ...form, check_in: e.target.value, check_out: e.target.value >= form.check_out ? addDays(e.target.value, 1) : form.check_out })} /></Field>
          <Field label="Departure"><input type="date" required min={addDays(form.check_in, 1)} value={form.check_out}
                                          onChange={(e) => setForm({ ...form, check_out: e.target.value })} /></Field>
          <Field label="Adults"><input type="number" min={1} max={30} value={form.adults} onChange={(e) => setForm({ ...form, adults: e.target.value })} /></Field>
          <Field label="Children"><input type="number" min={0} max={10} value={form.children} onChange={(e) => setForm({ ...form, children: e.target.value })} /></Field>
          <Field label="Promo code"><input value={form.promo_code} onChange={(e) => setForm({ ...form, promo_code: e.target.value })} /></Field>
          <button className="primary guest-cta">Check availability</button>
        </form>
      </section>
      {searched && (
        <section className="stack">
          <ErrorAlert error={results.error} />
          {results.isLoading && <Loading />}
          {results.data && !results.data.room_types.length && !results.data.group_plans?.length && (
            <div className="card guest-empty">
              No single room fits {party(params.get('adults') ?? 1, params.get('children') ?? 0)} on these dates, and there aren't
              enough rooms free to put the group together. Try different dates, or contact us.
            </div>
          )}
          {!!results.data?.group_plans?.length && (
            <section className="stack" aria-label="Plans for your group">
              <div>
                <h2 style={{ margin: 0 }}>Plans for your group</h2>
                <p className="muted" style={{ margin: '4px 0 0' }}>
                  {party(params.get('adults') ?? 1, params.get('children') ?? 0)} is more than one room sleeps, so here are rooms that
                  fit everyone, booked together in one go. Split the rooms however you like.
                </p>
              </div>
              <div className="guest-plans">
                {results.data.group_plans.map((plan) => (
                  <article className="card guest-plan" key={plan.label}>
                    <span className="home-badge">{plan.label}</span>
                    <strong>{plan.rooms.length} rooms</strong>
                    <ul>{plan.rooms.map((r, i) => <li key={i}>{r.room_type_name} <span className="muted">· {party(r.number_of_adults, r.number_of_children)}</span></li>)}</ul>
                    <div className="guest-price" style={{ alignItems: 'flex-start' }}>
                      <strong>{formatMoney(plan.total_with_taxes)}</strong>
                      <span className="muted">{stay} night{stay === 1 ? '' : 's'} for everyone, incl. taxes</span>
                    </div>
                    <span className="muted" style={{ fontSize: 13 }}>{cancellationNote(plan)}</span>
                    <button className="primary" onClick={() => navigate(`/book/checkout?${new URLSearchParams({ ...query, plan: encodePlan(plan), free_until: termsParam(plan) })}`)}>
                      Book this plan</button>
                  </article>
                ))}
              </div>
            </section>
          )}
          {results.data && results.data.room_types.length > 1 && (
            <p className="muted" style={{ margin: 0 }}>Best fit for your party first, then the lowest price.</p>
          )}
          {results.data?.room_types.map((room, index) => (
            <RoomOfferCard key={room.id} room={room} stay={stay} best={index === 0 && results.data!.room_types.length > 1}
                           onSelect={(plan, freeUntil) => navigate(`/book/checkout?${new URLSearchParams({ ...query, room_type: String(room.id), rate_plan: plan, free_until: freeUntil })}`)} />
          ))}
          {!!results.data?.other_room_types?.length && (
            <section className="stack" aria-label="All rooms">
              <div>
                <h2 style={{ margin: 0 }}>Or browse our rooms</h2>
                <p className="muted" style={{ margin: '4px 0 0' }}>Each of these sleeps part of your group. Book one on its own, or ask us to arrange a different mix.</p>
              </div>
              {results.data.other_room_types.map((room) => (
                <RoomOfferCard key={room.id} room={room} stay={stay}
                               onSelect={(plan, freeUntil) => navigate(`/book/checkout?${new URLSearchParams({
                                 ...query, room_type: String(room.id), rate_plan: plan, free_until: freeUntil,
                                 adults: String(Math.min(Number(params.get('adults') ?? 1), room.max_adults)),
                                 children: String(Math.min(Number(params.get('children') ?? 0), room.max_children)) })}`)} />
              ))}
            </section>
          )}
        </section>
      )}
    </GuestLayout>
  );
}

function RoomOfferCard({ room, stay, best = false, onSelect }: { room: RoomOffer; stay: number; best?: boolean; onSelect: (ratePlan: string, freeUntil: string) => void }) {
  return (
    <article className="card guest-room">
      {room.primary_image ? <img src={room.primary_image} alt={room.name} loading="lazy" />
        : <div className="guest-room-placeholder" aria-hidden="true" />}
      <div className="stack" style={{ gap: 10 }}>
        <div>
          <h2 style={{ margin: 0 }}>{room.name}{best && <span className="home-badge">Best match</span>}</h2>
          <div className="muted">{room.size} sq ft · {room.bed_type.toLowerCase()} bed · up to {room.max_adults} adults{room.max_children ? `, ${room.max_children} children` : ''}</div>
        </div>
        <p style={{ margin: 0 }}>{room.description}</p>
        {room.rate_plans.length === 0 && <div className="muted">Not available to book online for these dates.</div>}
        {room.rate_plans.map((plan) => (
          <div className="guest-rate" key={plan.code}>
            <div>
              <strong>{plan.name}</strong>
              <div className="muted" style={{ fontSize: 13 }}>{plan.meal_plan_name} · {cancellationNote(plan)}</div>
            </div>
            <div className="guest-price">
              <strong>{formatMoney(plan.total_with_taxes)}</strong>
              <span className="muted">{stay} night{stay === 1 ? '' : 's'}, incl. taxes</span>
            </div>
            <button className="primary" onClick={() => onSelect(plan.code, termsParam(plan))}>Select</button>
          </div>
        ))}
      </div>
    </article>
  );
}

/**
 * Before paying, say plainly when free cancellation ends for these dates: a last-minute booking is
 * already past it. (Display only; the server applies the real policy when a booking is cancelled.)
 */
function CheckoutCancellationNote({ freeUntil }: { freeUntil: string | null }) {
  if (!freeUntil) return null;
  if (freeUntil === 'none') {
    return <div className="alert error" role="note">Non-refundable: the full stay is charged if you cancel.</div>;
  }
  if (new Date(freeUntil).getTime() <= Date.now()) {
    return <div className="alert error" role="note">Free cancellation has already passed for these dates. If you cancel, the cancellation fee in the policy above applies.</div>;
  }
  return <div className="alert success" role="note">Free cancellation until {formatDateTime(freeUntil)}.</div>;
}

export function CheckoutPage() {
  const [params] = useSearchParams();
  const hotel = useHotel();
  const [guest, setGuest] = useState({ first_name: '', last_name: '', email: '', phone_number: '', accepts_marketing: false });
  const [requests, setRequests] = useState('');
  const [gateway, setGateway] = useState('');
  const [agreed, setAgreed] = useState(false);
  useEffect(() => { if (hotel.data && !gateway) setGateway(hotel.data.payment_gateways[0] ?? ''); }, [hotel.data, gateway]);

  const plan = decodePlan(params.get('plan'));
  const roomTypes = useQuery({ queryKey: ['room-types'], queryFn: () => api<{ id: number; name: string }[]>('rooms/types/'), enabled: !!plan });
  const typeName = (id: number) => roomTypes.data?.find((t) => t.id === id)?.name ?? 'Room';
  const book = useMutation({
    mutationFn: () => plan ? post<{ payment: { authorization_url: string } }>('bookings/create-group/', {
      guest, check_in_date: params.get('check_in'), check_out_date: params.get('check_out'),
      rooms: plan, special_requests: requests, gateway,
    }) : post<Confirmation & { payment: { authorization_url: string } }>('bookings/create/', {
      guest, room_type: Number(params.get('room_type')), check_in_date: params.get('check_in'),
      check_out_date: params.get('check_out'), number_of_adults: Number(params.get('adults') ?? 1),
      number_of_children: Number(params.get('children') ?? 0), special_requests: requests,
      rate_plan: params.get('rate_plan'), promo_code: params.get('promo_code') ?? '', gateway,
    }),
    // Off to the payment provider's secure page
    onSuccess: (data) => window.location.assign(data.payment.authorization_url),
  });

  return (
    <GuestLayout>
      <form className="guest-checkout" onSubmit={(e) => { e.preventDefault(); book.mutate(); }}>
        <div className="stack">
          <h1>Your details</h1>
          <ErrorAlert error={book.error} />
          <div className="card form-grid">
            <Field label="First name"><input required autoComplete="given-name" value={guest.first_name} onChange={(e) => setGuest({ ...guest, first_name: e.target.value })} /></Field>
            <Field label="Last name"><input required autoComplete="family-name" value={guest.last_name} onChange={(e) => setGuest({ ...guest, last_name: e.target.value })} /></Field>
            <Field label="Email" hint="Your confirmation is sent here" error={fieldError(book.error, 'guest')}>
              <input type="email" required autoComplete="email" value={guest.email} onChange={(e) => setGuest({ ...guest, email: e.target.value })} /></Field>
            <Field label="Mobile number" hint="For booking updates by SMS">
              <input type="tel" autoComplete="tel" value={guest.phone_number} onChange={(e) => setGuest({ ...guest, phone_number: e.target.value })} /></Field>
          </div>
          <div className="card">
            <Field label="Special requests (optional)" hint="Airport pickup, early check-in, dietary needs…">
              <textarea value={requests} onChange={(e) => setRequests(e.target.value)} /></Field>
          </div>
          <div className="card stack">
            <strong>Payment</strong>
            <div className="row">
              {hotel.data?.payment_gateways.map((code) => (
                <label key={code} className="checkbox"><input type="radio" name="gateway" checked={gateway === code} onChange={() => setGateway(code)} />
                  {code === 'PAYSTACK' ? 'Paystack (card, bank, USSD)' : 'Flutterwave (card, bank, USSD)'}</label>
              ))}
            </div>
            {hotel.data && !hotel.data.payment_gateways.length ? (
              <div className="alert error" role="alert">
                Online payment isn't available right now. Please book by phone{hotel.data.phone && <> on <a href={`tel:${hotel.data.phone.replace(/\s/g, '')}`}>{hotel.data.phone}</a></>}
                {hotel.data.email && <> or email <a href={`mailto:${hotel.data.email}`}>{hotel.data.email}</a></>}.
              </div>
            ) : <span className="muted" style={{ fontSize: 13 }}>You'll pay securely on the provider's page. We never see or store your card details.</span>}
            <label className="checkbox"><input type="checkbox" checked={guest.accepts_marketing} onChange={(e) => setGuest({ ...guest, accepts_marketing: e.target.checked })} />
              Send me offers and news (optional)</label>
            <label className="checkbox"><input type="checkbox" required checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />
              I accept the cancellation policy and the hotel's privacy notice</label>
          </div>
        </div>
        <aside className="card stack guest-summary">
          <strong>Your stay</strong>
          <div>{formatDate(params.get('check_in'))} → {formatDate(params.get('check_out'))}</div>
          <div className="muted">{party(params.get('adults') ?? 1, params.get('children') ?? 0)}</div>
          {plan && <ul className="guest-plan-rooms">{plan.map((r, i) => <li key={i}>{typeName(r.room_type)} <span className="muted">· {party(r.number_of_adults, r.number_of_children)}</span></li>)}</ul>}
          <div className="muted" style={{ fontSize: 13 }}>{hotel.data?.cancellation_policy}</div>
          <CheckoutCancellationNote freeUntil={params.get('free_until')} />
          <button className="primary guest-cta" disabled={book.isPending || !gateway}>{book.isPending ? (plan ? 'Reserving your rooms…' : 'Reserving your room…') : 'Continue to payment'}</button>
          <span className="muted" style={{ fontSize: 12 }}>{plan ? `All ${plan.length} rooms are held` : 'Your room is held'} for 15 minutes while you pay.</span>
        </aside>
      </form>
    </GuestLayout>
  );
}

export function PaymentCompletePage() {
  const [params] = useSearchParams();
  // Paystack returns ?reference=, Flutterwave ?tx_ref=
  const reference = params.get('reference') ?? params.get('tx_ref') ?? '';
  const [attempt, setAttempt] = useState(0);
  const verify = useQuery({
    queryKey: ['verify', reference, attempt],
    queryFn: () => post<{ status: string; booking: { confirmation_number: string; status: string } | null; group: { reference: string; bookings: { confirmation_number: string; status: string; room_type_name: string; number_of_adults: number; number_of_children: number }[] } | null }>('payments/verify/', { reference }),
    enabled: !!reference,
    retry: false,
  });
  const status = verify.data?.status;
  useEffect(() => {
    // The provider may take a few seconds to settle; check again a few times
    if (status === 'INITIALIZED' && attempt < 5) {
      const timer = setTimeout(() => setAttempt(attempt + 1), 3000);
      return () => clearTimeout(timer);
    }
  }, [status, attempt]);

  const booking = verify.data?.booking;
  return (
    <GuestLayout>
      <div className="card guest-result">
        {!reference && <p>We couldn't find a payment reference. If you were charged, please contact the hotel.</p>}
        {(verify.isLoading || (status === 'INITIALIZED' && attempt < 5)) && reference && <><h1>Confirming your payment…</h1><Loading /></>}
        {verify.error instanceof ApiError && <ErrorAlert error={verify.error} />}
        {status === 'SUCCEEDED' && booking?.status === 'CONFIRMED' && <>
          <h1>You're booked!</h1>
          {verify.data?.group ? <>
            <p>Your group reference is <strong className="guest-ref">{verify.data.group.reference}</strong>. Each room has its own confirmation number:</p>
            <ul className="guest-plan-rooms" style={{ textAlign: 'left' }}>{verify.data.group.bookings.map((b) => (
              <li key={b.confirmation_number}><strong>{b.confirmation_number}</strong> · {b.room_type_name} <span className="muted">· {party(b.number_of_adults, b.number_of_children)}</span></li>
            ))}</ul>
            <p>We've emailed you the details.</p>
          </> : <p>Your confirmation number is <strong className="guest-ref">{booking.confirmation_number}</strong>. We've emailed you the details.</p>}
          <Link className="button" to="/booking/manage">View my booking</Link>
        </>}
        {status === 'SUCCEEDED' && booking && booking.status !== 'CONFIRMED' && <>
          <h1>Sorry, {verify.data?.group ? 'some of those rooms were' : 'that room was'} taken</h1>
          <p>Your payment arrived after the room hold expired and the room was booked by someone else. Your payment is being refunded in full.</p>
        </>}
        {status === 'FAILED' && <><h1>Payment not completed</h1><p>No money was taken. <Link to="/book">Try again</Link>.</p></>}
        {status === 'NEEDS_REVIEW' && <><h1>We're checking your payment</h1><p>Our team will confirm your booking shortly by email.</p></>}
        {status === 'INITIALIZED' && attempt >= 5 && <><h1>Payment still processing</h1>
          <p>We haven't received confirmation yet. You'll get an email as soon as it arrives.</p></>}
      </div>
    </GuestLayout>
  );
}

interface GuestGroup {
  reference: string;
  bookings: Confirmation[];
  totals: { rooms: number; total_with_taxes: string; cancellation_fee_if_cancelled_now: string | null; cancellable_rooms: number; refunded: string };
}
type Found = { kind: 'booking'; booking: Confirmation } | { kind: 'group'; group: GuestGroup };
interface Access { reference: string; email: string }

/** Group references (GR-…) open the whole group; confirmation numbers (BK-…) open one room. */
const isGroupReference = (reference: string) => /^GR-/i.test(reference.trim());

async function findBooking({ reference, email }: Access): Promise<Found> {
  if (isGroupReference(reference)) return { kind: 'group', group: await post<GuestGroup>('bookings/group/lookup/', { reference, email }) };
  return { kind: 'booking', booking: await post<Confirmation>('bookings/lookup/', { confirmation_number: reference, email }) };
}

async function cancelBooking({ reference, email }: Access, reason: string): Promise<Found> {
  if (isGroupReference(reference)) return { kind: 'group', group: await post<GuestGroup>('bookings/group/cancel/', { reference, email, reason }) };
  return { kind: 'booking', booking: await post<Confirmation>('bookings/cancel/', { confirmation_number: reference, email, reason }) };
}

const statusLabel = (status: string) => status.replace('_', ' ').toLowerCase();
const statusBadge = (status: string) => `badge ${status === 'CANCELLED' ? 'danger' : 'info'}`;
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

export function ManageBookingPage() {
  const [form, setForm] = useState<Access>({ reference: '', email: '' });
  const [reason, setReason] = useState('');
  const lookup = useMutation({ mutationFn: findBooking });
  // Cancelling returns the updated booking (or group), which then replaces the looked-up one
  const cancel = useMutation({ mutationFn: (access: Access) => cancelBooking(access, reason) });
  const found = cancel.data ?? lookup.data;
  const access = lookup.variables;

  function open(next: Access) {
    setForm(next);
    cancel.reset();
    lookup.mutate(next);
  }

  return (
    <GuestLayout>
      <div className="stack" style={{ maxWidth: 680, margin: '0 auto', width: '100%' }}>
        <h1>Manage my booking</h1>
        <form className="card form-grid" onSubmit={(e) => { e.preventDefault(); open(form); }}>
          <Field label="Confirmation number" hint="Or your group reference (GR-…) to manage every room">
            <input required value={form.reference} placeholder="BK-XXXXXX"
                   onChange={(e) => setForm({ ...form, reference: e.target.value })} />
          </Field>
          <Field label="Email used to book"><input type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
          <button className="primary" style={{ alignSelf: 'end' }} disabled={lookup.isPending}>Find booking</button>
        </form>
        <ErrorAlert error={lookup.error || cancel.error} />

        {found?.kind === 'booking' && access && (
          <BookingCard booking={found.booking} reason={reason} onReason={setReason} busy={cancel.isPending}
                       onCancel={() => cancel.mutate(access)}
                       onOpenGroup={(reference) => open({ reference, email: access.email })} />
        )}
        {found?.kind === 'group' && access && (
          <GroupCard group={found.group} reason={reason} onReason={setReason} busy={cancel.isPending}
                     onCancel={() => cancel.mutate(access)} />
        )}
      </div>
    </GuestLayout>
  );
}

interface CancelProps { reason: string; onReason: (reason: string) => void; busy: boolean; onCancel: () => void }

function BookingCard({ booking, onOpenGroup, ...cancel }: CancelProps & { booking: Confirmation; onOpenGroup: (reference: string) => void }) {
  return (
    <div className="card stack">
      <div className="row"><h2 style={{ margin: 0 }}>{booking.confirmation_number}</h2><span className="spacer" />
        <span className={statusBadge(booking.status)}>{statusLabel(booking.status)}</span></div>
      <dl className="details">
        <dt>Guest</dt><dd>{booking.guest.first_name} {booking.guest.last_name}</dd>
        <dt>Room</dt><dd>{booking.room_type_name} · {booking.rate_plan.name}</dd>
        <dt>Stay</dt><dd>{formatDate(booking.check_in_date)} → {formatDate(booking.check_out_date)}</dd>
        <dt>Total</dt><dd>{formatMoney(booking.total_with_taxes)}</dd>
      </dl>
      {booking.group_reference && (
        <div className="alert success row">
          <span>This room is part of group {booking.group_reference}.</span><span className="spacer" />
          <button type="button" onClick={() => onOpenGroup(booking.group_reference!)}>Manage the whole group</button>
        </div>
      )}
      <Refunded amount={booking.status === 'CANCELLED' ? booking.refunded : undefined} />
      <p className="muted" style={{ margin: 0 }}>{booking.cancellation_policy}</p>
      {booking.cancellation_fee_if_cancelled_now !== null && (
        <CancelBlock title="Cancel this booking" button="Cancel booking" fee={booking.cancellation_fee_if_cancelled_now} {...cancel} />
      )}
    </div>
  );
}

function GroupCard({ group, ...cancel }: CancelProps & { group: GuestGroup }) {
  const first = group.bookings[0];
  const { totals } = group;
  const everyRoom = totals.cancellable_rooms === group.bookings.length;
  return (
    <div className="card stack">
      <div className="row"><h2 style={{ margin: 0 }}>Group {group.reference}</h2><span className="spacer" />
        <span className="badge info">{plural(totals.rooms, 'room')}</span></div>
      {first && (
        <dl className="details">
          <dt>Booked by</dt><dd>{first.guest.first_name} {first.guest.last_name}</dd>
          <dt>Stay</dt><dd>{formatDate(first.check_in_date)} → {formatDate(first.check_out_date)}</dd>
          <dt>Total</dt><dd>{formatMoney(totals.total_with_taxes)}</dd>
        </dl>
      )}
      <ul className="guest-group-rooms">
        {group.bookings.map((b) => (
          <li key={b.confirmation_number}>
            <div>
              <strong>{b.room_type_name}</strong>
              <span className="muted"> · {plural(b.number_of_adults, 'adult')}
                {b.number_of_children > 0 && `, ${plural(b.number_of_children, 'child', 'children')}`} · {b.confirmation_number}</span>
            </div>
            <span className={statusBadge(b.status)}>{statusLabel(b.status)}</span>
          </li>
        ))}
      </ul>
      <Refunded amount={totals.refunded} />
      {first && <p className="muted" style={{ margin: 0 }}>{first.cancellation_policy}</p>}
      {totals.cancellation_fee_if_cancelled_now !== null && (
        <CancelBlock title={everyRoom ? 'Cancel the whole group' : `Cancel the ${plural(totals.cancellable_rooms, 'remaining room')}`}
                     button="Cancel group" fee={totals.cancellation_fee_if_cancelled_now} {...cancel} />
      )}
    </div>
  );
}

function Refunded({ amount }: { amount?: string }) {
  if (!amount || Number(amount) <= 0) return null;
  return (
    <div className="alert success">
      {formatMoney(amount)} has been refunded to the card you paid with. It usually reaches you within a few working days.
    </div>
  );
}

function CancelBlock({ title, button, fee, reason, onReason, busy, onCancel }: CancelProps & { title: string; button: string; fee: string }) {
  return (
    <div className="stack">
      <strong>{title}</strong>
      <span>Cancelling now costs <strong>{formatMoney(fee)}</strong>; anything you paid above that is refunded.</span>
      <Field label="Reason (optional)"><input value={reason} onChange={(e) => onReason(e.target.value)} /></Field>
      <div><button className="danger" disabled={busy} onClick={onCancel}>{button}</button></div>
    </div>
  );
}
