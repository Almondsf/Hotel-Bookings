import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { api, post } from '../api/client';
import type { BoardRoom, Room } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { ReservationActionDialog, WalkInDialog, type RoomChoice } from '../components/frontDesk';
import { ErrorAlert, Loading, PageHeader, StatusBadge } from '../components/ui';
import { addDays, formatDate, todayISO } from '../lib/format';

function tileClass(room: BoardRoom) {
  if (room.status === 'OUT_OF_SERVICE' || room.status === 'MAINTENANCE') return 'blocked';
  if (room.departing_today) return 'departing';
  if (room.in_house) return 'occupied';
  if (room.arriving) return 'arriving';
  return '';
}

type Pending = { kind: 'check-in' | 'check-out'; bookingId: number } | { kind: 'walk-in'; room: RoomChoice } | null;

export function RoomBoard() {
  const { can } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [date, setDate] = useState(todayISO());
  const [pending, setPending] = useState<Pending>(null);
  const isToday = date === todayISO();
  const manage = can('bookings.manage');

  const board = useQuery({
    queryKey: ['room-board', date],
    queryFn: () => api<BoardRoom[]>('front-desk/room-board/', { query: { date } }),
    refetchInterval: 60_000,
  });
  // The board names room types; booking needs their ids
  const rooms = useQuery({ queryKey: ['rooms'], queryFn: () => api<Room[]>('rooms/all/'), staleTime: 300_000 });
  const typeOf = (roomId: number) => rooms.data?.find((r) => r.id === roomId)?.room_type;

  const markClean = useMutation({
    mutationFn: (roomId: number) => post(`housekeeping/rooms/${roomId}/status/`, { housekeeping_status: 'CLEAN', reason: 'Marked clean from the room board' }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['room-board'] });
      void queryClient.invalidateQueries({ queryKey: ['housekeeping'] });
    },
  });

  const floors = new Map<number, BoardRoom[]>();
  for (const room of board.data ?? []) {
    floors.set(room.floor_number, [...(floors.get(room.floor_number) ?? []), room]);
  }

  function actions(room: BoardRoom) {
    const sellable = room.status === 'AVAILABLE' || room.status === 'OCCUPIED';
    const ready = room.housekeeping_status !== 'DIRTY';
    const roomType = typeOf(room.room_id);
    const buttons = [];
    if (manage && isToday && room.arriving && !room.in_house) {
      buttons.push(<button key="in" className="primary small" onClick={() => setPending({ kind: 'check-in', bookingId: room.arriving!.id })}>Check in</button>);
    }
    if (manage && isToday && room.in_house && room.departing_today) {
      buttons.push(<button key="out" className="small" onClick={() => setPending({ kind: 'check-out', bookingId: room.in_house!.id })}>Check out</button>);
    }
    if (manage && sellable && !room.in_house && !room.arriving && roomType) {
      if (isToday && ready) {
        buttons.push(<button key="walk" className="small" onClick={() => setPending({ kind: 'walk-in', room: { id: room.room_id, room_number: room.room_number, room_type: roomType } })}>Walk-in</button>);
      }
      buttons.push(<button key="reserve" className="small" onClick={() => navigate(`/reservations/new?${new URLSearchParams({
        check_in: date, check_out: addDays(date, 1), room_type: String(roomType), room: String(room.room_id) })}`)}>Reserve</button>);
    }
    if (can('housekeeping.manage') && isToday && !ready && !room.in_house) {
      buttons.push(<button key="clean" className="small" disabled={markClean.isPending} onClick={() => markClean.mutate(room.room_id)}>Mark clean</button>);
    }
    return buttons.length ? <div className="tile-actions">{buttons}</div> : null;
  }

  return (
    <div>
      <PageHeader
        title="Room board"
        subtitle={<span className="legend">
          <span style={{ color: 'var(--info)' }}>▌In house</span><span style={{ color: 'var(--ok)' }}>▌Arriving</span>
          <span style={{ color: 'var(--warn)' }}>▌Departing</span><span style={{ color: 'var(--danger)' }}>▌Out of order</span>
        </span>}
        actions={<>
          {!isToday && <button onClick={() => setDate(todayISO())}>Today</button>}
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} aria-label="Date" />
        </>}
      />
      <ErrorAlert error={board.error ?? markClean.error} />
      {board.isLoading ? <Loading /> : [...floors.entries()].map(([floor, floorRooms]) => (
        <section className="floor" key={floor}>
          <h3>Floor {floor}</h3>
          <div className="rooms">
            {floorRooms.map((room) => {
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
                  {actions(room)}
                </div>
              );
            })}
          </div>
        </section>
      ))}

      {pending && pending.kind !== 'walk-in' && <ReservationActionDialog bookingId={pending.bookingId} action={pending.kind} onClose={() => setPending(null)} />}
      {pending?.kind === 'walk-in' && <WalkInDialog room={pending.room} onClose={() => setPending(null)} />}
    </div>
  );
}
