import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { api } from '../api/client';
import { ErrorAlert, Loading } from '../components/ui';
import { formatMoney } from '../lib/format';
import { GuestLayout, useHotel } from './GuestSite';
import { BookingBar, capacity, sized, useRoomTypes, type RoomTypeInfo } from './HomePage';

export function RoomPage() {
  const { slug = '' } = useParams();
  const hotel = useHotel();
  const room = useQuery({ queryKey: ['room-type', slug], queryFn: () => api<RoomTypeInfo>(`rooms/${slug}/`) });
  const others = useRoomTypes();
  const [shown, setShown] = useState(0);

  useEffect(() => setShown(0), [slug]);
  useEffect(() => { if (room.data && hotel.data) document.title = `${room.data.name} · ${hotel.data.name}`; }, [room.data, hotel.data]);

  if (room.isLoading) return <GuestLayout><Loading /></GuestLayout>;
  if (!room.data) {
    return (
      <GuestLayout>
        <ErrorAlert error={room.error} />
        <p>We couldn't find that room. <Link to="/#rooms">See all rooms</Link></p>
      </GuestLayout>
    );
  }

  const r = room.data;
  const image = r.images[shown] ?? r.images[0];
  return (
    <GuestLayout>
      <nav className="muted room-crumbs" aria-label="Breadcrumb"><Link to="/">Home</Link> / <a href="/#rooms">Rooms</a> / {r.name}</nav>
      <div className="room-layout">
        <div className="stack" style={{ gap: 20 }}>
          <div className="room-gallery">
            {image ? <img className="room-main" src={sized(image.image_url, 1400)} alt={image.description || r.name} />
              : <div className="guest-room-placeholder room-main" aria-hidden="true" />}
            {r.images.length > 1 && (
              <div className="home-thumbs" role="group" aria-label="Photos">
                {r.images.map((img, i) => (
                  <button key={img.id} type="button" aria-label={`Photo ${i + 1}`} aria-pressed={i === shown}
                          className={i === shown ? 'active' : ''} onClick={() => setShown(i)}>
                    <img src={sized(img.image_url, 200)} alt="" loading="lazy" />
                  </button>
                ))}
              </div>
            )}
          </div>

          <div>
            <h1 className="room-title">{r.name}</h1>
            <p className="room-lead">{r.description}</p>
          </div>

          <dl className="room-specs">
            <div><dt>Size</dt><dd>{r.size} sq ft</dd></div>
            <div><dt>Beds</dt><dd>{r.bed_count} × {r.bed_type.toLowerCase().replace('_', ' ')}</dd></div>
            <div><dt>Sleeps</dt><dd>{capacity(r)}</dd></div>
            <div><dt>Rooms</dt><dd>{r.available_room_count} of this type</dd></div>
          </dl>

          <section>
            <h2 className="room-h2">In your room</h2>
            <ul className="room-amenities">
              {r.amenities.map((a) => <li key={a.id}>{a.name}{a.is_premium && <span className="home-badge">Premium</span>}</li>)}
            </ul>
          </section>

          {hotel.data && (
            <section>
              <h2 className="room-h2">Policies</h2>
              <dl className="home-facts">
                <dt>Check-in</dt><dd>From {hotel.data.check_in_time}</dd>
                <dt>Check-out</dt><dd>By {hotel.data.check_out_time}</dd>
                <dt>Cancellation</dt><dd>{hotel.data.cancellation_policy}</dd>
              </dl>
            </section>
          )}
        </div>

        <aside className="card room-book">
          <div className="home-rate">
            <span className="muted">Rates from</span>
            <strong>{formatMoney(r.base_price)}</strong>
            <span className="muted">per night, before taxes</span>
          </div>
          <BookingBar defaultAdults={Math.min(2, r.max_adults)} />
          <p className="muted" style={{ fontSize: 13, margin: 0 }}>You'll see every available rate, including breakfast and saver options, on the next page.</p>
        </aside>
      </div>

      {others.data && others.data.length > 1 && (
        <section>
          <h2 className="room-h2">Other rooms</h2>
          <div className="room-others">
            {others.data.filter((o) => o.slug !== r.slug).map((o) => (
              <Link key={o.id} to={`/rooms/${o.slug}`} className="card room-other">
                {o.images[0] && <img src={sized(o.images[0].image_url, 500)} alt="" loading="lazy" />}
                <div><strong>{o.name}</strong><span className="muted">From {formatMoney(o.base_price)}</span></div>
              </Link>
            ))}
          </div>
        </section>
      )}
    </GuestLayout>
  );
}
