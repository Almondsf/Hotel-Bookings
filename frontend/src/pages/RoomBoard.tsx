import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { api } from '../api/client';
import type { BoardRoom } from '../api/types';
import { ErrorAlert, Loading, PageHeader, StatusBadge } from '../components/ui';
import { formatDate, todayISO } from '../lib/format';

function tileClass(room: BoardRoom) {
  if (room.status === 'OUT_OF_SERVICE' || room.status === 'MAINTENANCE') return 'blocked';
  if (room.departing_today) return 'departing';
  if (room.in_house) return 'occupied';
  if (room.arriving) return 'arriving';
  return '';
}

export function RoomBoard() {
  const [date, setDate] = useState(todayISO());
  const board = useQuery({
    queryKey: ['room-board', date],
    queryFn: () => api<BoardRoom[]>('front-desk/room-board/', { query: { date } }),
    refetchInterval: 60_000,
  });

  const floors = new Map<number, BoardRoom[]>();
  for (const room of board.data ?? []) {
    floors.set(room.floor_number, [...(floors.get(room.floor_number) ?? []), room]);
  }

  return (
    <div>
      <PageHeader
        title="Room board"
        subtitle={<span className="legend">
          <span style={{ color: 'var(--info)' }}>▌In house</span><span style={{ color: 'var(--ok)' }}>▌Arriving</span>
          <span style={{ color: 'var(--warn)' }}>▌Departing</span><span style={{ color: 'var(--danger)' }}>▌Out of order</span>
        </span>}
        actions={<input type="date" value={date} onChange={(e) => setDate(e.target.value)} aria-label="Date" />}
      />
      <ErrorAlert error={board.error} />
      {board.isLoading ? <Loading /> : [...floors.entries()].map(([floor, rooms]) => (
        <section className="floor" key={floor}>
          <h3>Floor {floor}</h3>
          <div className="rooms">
            {rooms.map((room) => {
              const booking = room.in_house ?? room.arriving;
              return (
                <div className={`room-tile ${tileClass(room)}`} key={room.room_id}>
                  <div className="row">
                    <span className="number">{room.room_number}</span>
                    <span className="spacer" />
                    {room.housekeeping_status && <StatusBadge status={room.housekeeping_status} />}
                  </div>
                  <div className="type">{room.room_type}</div>
                  {booking ? (
                    <div className="guest">
                      <Link to={`/reservations/${booking.id}`}>{booking.guest_name}</Link>
                      {booking.is_vip && <span className="badge warn" style={{ marginLeft: 4 }}>VIP</span>}
                      <div className="muted" style={{ fontSize: 12 }}>
                        {room.in_house ? (room.departing_today ? 'Departs today' : `Until ${formatDate(booking.check_out_date)}`) : 'Arriving'}
                      </div>
                    </div>
                  ) : room.status !== 'AVAILABLE' && room.status !== 'OCCUPIED' ? (
                    <div className="guest"><StatusBadge status={room.status} /></div>
                  ) : <div className="guest muted">Vacant</div>}
                </div>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}
