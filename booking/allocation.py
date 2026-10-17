"""Choosing and locking rooms. Callers must run inside transaction.atomic()."""
from booking.exceptions import BookingError, RoomUnavailableError
from rooms.models import Room
from rooms.services import free_rooms, get_available_rooms_for_type


def lock_room_types(room_types):
    """
    Lock every room of the given types until the transaction ends, which
    serializes concurrent bookings for them so two requests can't pick the
    same free room. Types are locked in id order so that two multi-room
    requests can't deadlock each other.
    """
    ids = sorted({room_type.pk for room_type in room_types})
    list(Room.objects.select_for_update().filter(room_type_id__in=ids).order_by('room_type_id', 'pk'))


def allocate_rooms(requests, check_in_date, check_out_date):
    """
    A free room for each (room_type, preferred_room or None) request, all from
    one availability query. Must run inside a transaction after
    lock_room_types(). Rooms come back in request order; requested rooms are
    reserved first so automatic picks never take them.
    """
    free = list(free_rooms(check_in_date, check_out_date)
                .filter(room_type_id__in={room_type.pk for room_type, _ in requests}))  # Meta ordering: room number
    free_ids = {room.pk for room in free}
    rooms, taken = [None] * len(requests), set()
    for index, (room_type, preferred) in enumerate(requests):
        if preferred is None:
            continue
        if preferred.room_type_id != room_type.pk:
            raise BookingError(f"Room {preferred.room_number} is not a {room_type.name}.", field='room')
        if preferred.pk not in free_ids or preferred.pk in taken:
            raise RoomUnavailableError(f"Room {preferred.room_number} is not available for these dates.")
        rooms[index] = preferred
        taken.add(preferred.pk)
    for index, (room_type, preferred) in enumerate(requests):
        if preferred is not None:
            continue
        room = next((r for r in free if r.room_type_id == room_type.pk and r.pk not in taken), None)
        if room is None:
            raise RoomUnavailableError(f"No {room_type.name} rooms are available for the selected dates.")
        rooms[index] = room
        taken.add(room.pk)
    return rooms


def allocate_room(room_type, check_in_date, check_out_date, *, preferred_room=None, exclude_booking=None, taken=()):
    """
    Pick a free room of `room_type`. Must run inside a transaction after
    lock_room_types(). `taken` are room ids already allocated in this request.
    """
    available = get_available_rooms_for_type(
        room_type, check_in_date, check_out_date, exclude_booking=exclude_booking,
    ).exclude(pk__in=taken)

    if preferred_room is not None:
        if preferred_room.room_type_id != room_type.pk:
            raise BookingError(f"Room {preferred_room.room_number} is not a {room_type.name}.", field='room')
        if not available.filter(pk=preferred_room.pk).exists():
            raise RoomUnavailableError(f"Room {preferred_room.room_number} is not available for these dates.")
        return preferred_room

    room = available.first()
    if room is None:
        raise RoomUnavailableError(f"No {room_type.name} rooms are available for the selected dates.")
    return room
