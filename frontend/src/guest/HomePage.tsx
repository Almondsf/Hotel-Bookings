import { useQuery } from '@tanstack/react-query';
import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { api } from '../api/client';
import { ErrorAlert, Field, Loading } from '../components/ui';
import { addDays, formatMoney, todayISO } from '../lib/format';
import { DINING, EVENTS, FACILITIES, GALLERY, HERO_SLIDES, HIGHLIGHTS, OFFERS, TESTIMONIALS, WELCOME } from './content';
import { GuestLayout, useHotel } from './GuestSite';

export interface RoomTypeInfo {
  id: number; name: string; slug: string; description: string; base_price: string;
  max_adults: number; max_children: number; bed_type: string; bed_count: number; size: number;
  amenities: { id: number; name: string; is_premium: boolean }[];
  images: { id: number; image_url: string; description: string }[];
  available_room_count: number;
}

/** Room photos are stored as bare image URLs; ask the image CDN for a sensible size when it supports it. */
export function sized(url: string, width: number) {
  return url.includes('images.unsplash.com') && !url.includes('?') ? `${url}?w=${width}&q=70&auto=format&fit=crop` : url;
}

export function useRoomTypes() {
  return useQuery({
    queryKey: ['room-types'],
    queryFn: async () => (await api<RoomTypeInfo[]>('rooms/types/')).sort((a, b) => Number(a.base_price) - Number(b.base_price)),
    staleTime: 600_000,
  });
}

export function bookingLink(stay: { check_in?: string; check_out?: string; adults?: number | string; children?: number | string } = {}) {
  const checkIn = stay.check_in ?? todayISO();
  return `/book?${new URLSearchParams({
    check_in: checkIn, check_out: stay.check_out ?? addDays(checkIn, 1),
    adults: String(stay.adults ?? 2), children: String(stay.children ?? 0),
  })}`;
}

export function capacity(room: RoomTypeInfo) {
  return `${room.max_adults} adult${room.max_adults === 1 ? '' : 's'}`
    + (room.max_children ? `, ${room.max_children} child${room.max_children === 1 ? '' : 'ren'}` : '');
}

/** Arrival / departure / guests bar that hands over to the booking engine. */
export function BookingBar({ defaultAdults = 2 }: { defaultAdults?: number }) {
  const navigate = useNavigate();
  const [form, setForm] = useState({ check_in: todayISO(), check_out: addDays(todayISO(), 1), adults: String(defaultAdults), children: '0' });

  function submit(event: FormEvent) {
    event.preventDefault();
    navigate(bookingLink(form));
  }

  return (
    <form className="home-booking" onSubmit={submit} aria-label="Check availability">
      <Field label="Arrival">
        <input type="date" required min={todayISO()} value={form.check_in}
               onChange={(e) => setForm({ ...form, check_in: e.target.value,
                 check_out: e.target.value >= form.check_out ? addDays(e.target.value, 1) : form.check_out })} />
      </Field>
      <Field label="Departure">
        <input type="date" required min={addDays(form.check_in, 1)} value={form.check_out}
               onChange={(e) => setForm({ ...form, check_out: e.target.value })} />
      </Field>
      <Field label="Adults">
        <select value={form.adults} onChange={(e) => setForm({ ...form, adults: e.target.value })}>
          {[1, 2, 3, 4].map((n) => <option key={n}>{n}</option>)}
        </select>
      </Field>
      <Field label="Children">
        <select value={form.children} onChange={(e) => setForm({ ...form, children: e.target.value })}>
          {[0, 1, 2, 3].map((n) => <option key={n}>{n}</option>)}
        </select>
      </Field>
      <button className="primary guest-cta">Check availability</button>
    </form>
  );
}

function SectionHead({ kicker, title, children }: { kicker: string; title: string; children?: ReactNode }) {
  return (
    <header className="home-head">
      <span className="home-kicker">{kicker}</span>
      <h2>{title}</h2>
      {children && <p className="muted">{children}</p>}
    </header>
  );
}

function HeroSlider() {
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const count = HERO_SLIDES.length;

  useEffect(() => {
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    if (paused || reduced) return;
    const timer = window.setInterval(() => setIndex((i) => (i + 1) % count), 6000);
    return () => window.clearInterval(timer);
  }, [paused, count]);

  const slide = HERO_SLIDES[index];
  return (
    <section className="home-hero" aria-roledescription="carousel" aria-label="Highlights"
             onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)}>
      {HERO_SLIDES.map((s, i) => (
        <div key={s.image} className={`home-slide${i === index ? ' active' : ''}`} style={{ backgroundImage: `url(${s.image})` }}
             aria-hidden={i !== index} />
      ))}
      <div className="home-hero-inner">
        <h1 key={slide.title}>{slide.title}</h1>
        <p className="home-tagline">{slide.text}</p>
        <div className="row">
          <a className="button primary guest-cta" href="#rooms">Explore our rooms</a>
          <Link className="button guest-cta home-ghost" to="/book">Book your stay</Link>
        </div>
      </div>
      <button type="button" className="home-arrow prev" aria-label="Previous slide"
              onClick={() => setIndex((index - 1 + count) % count)}>‹</button>
      <button type="button" className="home-arrow next" aria-label="Next slide"
              onClick={() => setIndex((index + 1) % count)}>›</button>
      <div className="home-dots">
        {HERO_SLIDES.map((s, i) => (
          <button type="button" key={s.image} aria-label={`Slide ${i + 1}`} aria-current={i === index}
                  className={i === index ? 'active' : ''} onClick={() => setIndex(i)} />
        ))}
      </div>
    </section>
  );
}

function RoomCard({ room }: { room: RoomTypeInfo }) {
  const image = room.images[0];
  return (
    <article className="card home-room">
      <Link to={`/rooms/${room.slug}`} className="home-room-media" aria-label={`${room.name} details`}>
        {image ? <img src={sized(image.image_url, 900)} alt={image.description || room.name} loading="lazy" />
          : <div className="guest-room-placeholder" aria-hidden="true" />}
        {room.images.length > 1 && <span className="home-photo-count">{room.images.length} photos</span>}
      </Link>
      <div className="home-room-body">
        <h3><Link to={`/rooms/${room.slug}`}>{room.name}</Link></h3>
        <div className="muted home-specs">
          {room.size} sq ft · {room.bed_count} {room.bed_type.toLowerCase()} bed{room.bed_count === 1 ? '' : 's'} · Sleeps {capacity(room)}
        </div>
        <p>{room.description}</p>
        <ul className="home-chips" aria-label="Amenities">
          {room.amenities.slice(0, 5).map((a) => <li key={a.id}>{a.name}</li>)}
          {room.amenities.length > 5 && <li>+{room.amenities.length - 5} more</li>}
        </ul>
        <div className="home-room-foot">
          <div className="home-rate">
            <span className="muted">Rates from</span>
            <strong>{formatMoney(room.base_price)}</strong>
            <span className="muted">per night</span>
          </div>
          <div className="row">
            <Link className="button" to={`/rooms/${room.slug}`}>View details</Link>
            <Link className="button primary" to={bookingLink({ adults: Math.min(2, room.max_adults) })}>Book now</Link>
          </div>
        </div>
      </div>
    </article>
  );
}

function Gallery() {
  const [open, setOpen] = useState<number | null>(null);
  useEffect(() => {
    if (open === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(null);
      if (e.key === 'ArrowRight') setOpen((i) => (i === null ? i : (i + 1) % GALLERY.length));
      if (e.key === 'ArrowLeft') setOpen((i) => (i === null ? i : (i - 1 + GALLERY.length) % GALLERY.length));
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  return (
    <>
      <div className="home-gallery">
        {GALLERY.map((g, i) => (
          <button type="button" key={g.thumb} onClick={() => setOpen(i)} aria-label={`Open photo ${i + 1}`}>
            <img src={g.thumb} alt="" loading="lazy" />
          </button>
        ))}
      </div>
      {open !== null && (
        <div className="home-lightbox" role="dialog" aria-modal="true" aria-label="Photo" onClick={() => setOpen(null)}>
          <img src={GALLERY[open].full} alt="" onClick={(e) => e.stopPropagation()} />
          <button type="button" className="home-lightbox-close" aria-label="Close" onClick={() => setOpen(null)}>×</button>
        </div>
      )}
    </>
  );
}

export function HomePage() {
  const hotel = useHotel();
  const rooms = useRoomTypes();
  const cheapest = rooms.data?.length ? Math.min(...rooms.data.map((r) => Number(r.base_price))) : null;
  const mapLink = hotel.data?.address
    ? `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${hotel.data.name}, ${hotel.data.address}`)}` : null;

  return (
    <GuestLayout wide>
      <HeroSlider />
      <div className="home-booking-wrap"><BookingBar /></div>

      <div className="home-content">
        <section className="home-split">
          <img src={WELCOME.image} alt="" loading="lazy" />
          <div>
            <SectionHead kicker={WELCOME.kicker} title={`${WELCOME.title}`} />
            {WELCOME.paragraphs.map((p) => <p key={p.slice(0, 20)}>{p}</p>)}
            <ul className="home-highlights">
              {HIGHLIGHTS.map((h) => <li key={h.title}><strong>{h.title}</strong><span className="muted">{h.text}</span></li>)}
            </ul>
          </div>
        </section>

        <section id="rooms" className="home-section">
          <SectionHead kicker="Stay" title="Rooms & suites">
            {cheapest !== null ? `${rooms.data?.length} room types from ${formatMoney(cheapest)} a night. Rates exclude VAT and service charge.` : null}
          </SectionHead>
          <ErrorAlert error={rooms.error} />
          {rooms.isLoading && <Loading />}
          <div className="home-rooms">{rooms.data?.map((room) => <RoomCard key={room.id} room={room} />)}</div>
        </section>

        <section id="offers" className="home-section">
          <SectionHead kicker="Offers" title="Packages & special rates">
            Choose these when you search: the booking page shows each rate with its conditions.
          </SectionHead>
          <div className="home-offers">
            {OFFERS.map((o) => (
              <article className="card home-offer" key={o.title}>
                <span className="home-badge">{o.badge}</span>
                <h3>{o.title}</h3>
                <p className="muted">{o.text}</p>
                <Link to="/book">Check rates →</Link>
              </article>
            ))}
          </div>
        </section>

        <section id="dining" className="home-section">
          <SectionHead kicker="Eat & drink" title="Dining & lounges" />
          <div className="home-cards">
            {DINING.map((d) => (
              <article className="card home-card" key={d.title}>
                <img src={d.image} alt="" loading="lazy" />
                <div>
                  <h3>{d.title}</h3>
                  <div className="muted home-hours">{d.hours}</div>
                  <p>{d.text}</p>
                </div>
              </article>
            ))}
          </div>
        </section>

        <section id="facilities" className="home-section">
          <SectionHead kicker="Relax" title="Facilities & wellness" />
          <div className="home-cards">
            {FACILITIES.map((f) => (
              <article className="card home-card" key={f.title}>
                <img src={f.image} alt="" loading="lazy" />
                <div><h3>{f.title}</h3><p>{f.text}</p></div>
              </article>
            ))}
          </div>
        </section>
      </div>

      <section id="events" className="home-banner" style={{ backgroundImage: `url(${EVENTS.image})` }}>
        <div className="home-banner-inner">
          <span className="home-kicker">Meetings & events</span>
          <h2>{EVENTS.title}</h2>
          <p>{EVENTS.text}</p>
          {hotel.data?.email && <a className="button primary guest-cta" href={`mailto:${hotel.data.email}?subject=Event%20enquiry`}>Plan your event</a>}
        </div>
      </section>

      <div className="home-content">
        <section className="home-section">
          <SectionHead kicker="Guest stories" title="What our guests say" />
          <div className="home-quotes">
            {TESTIMONIALS.map((t) => (
              <figure className="card home-quote" key={t.name}>
                <div className="home-stars" aria-label="5 out of 5">★★★★★</div>
                <blockquote>“{t.quote}”</blockquote>
                <figcaption><strong>{t.name}</strong><span className="muted">{t.from}</span></figcaption>
              </figure>
            ))}
          </div>
        </section>

        <section id="gallery" className="home-section">
          <SectionHead kicker="Gallery" title="Take a look around" />
          <Gallery />
        </section>

        <section id="contact" className="home-section home-info">
          <div className="card">
            <SectionHead kicker="Reservations" title="Get in touch" />
            {hotel.data ? (
              <dl className="home-facts">
                {hotel.data.address && <><dt>Address</dt><dd>{hotel.data.address}</dd></>}
                {hotel.data.phone && <><dt>Phone</dt><dd><a href={`tel:${hotel.data.phone.replace(/\s/g, '')}`}>{hotel.data.phone}</a></dd></>}
                {hotel.data.email && <><dt>Email</dt><dd><a href={`mailto:${hotel.data.email}`}>{hotel.data.email}</a></dd></>}
              </dl>
            ) : <Loading />}
            <div className="row" style={{ marginTop: 16 }}>
              {mapLink && <a className="button" href={mapLink} target="_blank" rel="noreferrer">Open in Google Maps</a>}
              <Link className="button" to="/booking/manage">Manage my booking</Link>
            </div>
          </div>
          <div className="card">
            <SectionHead kicker="Before you arrive" title="Good to know" />
            {hotel.data ? (
              <dl className="home-facts">
                <dt>Check-in</dt><dd>From {hotel.data.check_in_time}</dd>
                <dt>Check-out</dt><dd>By {hotel.data.check_out_time}</dd>
                <dt>Cancellation</dt><dd>{hotel.data.cancellation_policy}</dd>
                <dt>Payment</dt><dd>Secure online payment when you book; card, transfer or cash at the hotel.</dd>
                <dt>ID</dt><dd>Please bring a valid ID (NIN slip, driver’s licence or passport) for check-in.</dd>
              </dl>
            ) : <Loading />}
          </div>
        </section>
      </div>
    </GuestLayout>
  );
}
