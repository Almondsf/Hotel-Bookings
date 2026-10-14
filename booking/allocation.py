"""Choosing and locking rooms. Callers must run inside transaction.atomic()."""
from booking.exceptions import BookingError, RoomUnavailableError
from rooms.models import Room
from rooms.services import get_available_rooms_for_type


def lock_room_types(room_types):
    """
    Lock every room of the given types until the transaction ends, which
    serializes concurrent bookings for them so two requests can't pick the
    same free room. Types are locked in id order so that two multi-room
    requests can't deadlock each other.
    """
    ids = sorted({room_type.pk for room_type in room_types})
    list(Room.objects.select_for_update().filter(room_type_id__in=ids).order_by('room_type_id', 'pk'))


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
