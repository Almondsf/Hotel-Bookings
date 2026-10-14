"""Front-desk operations that span several steps."""
from django.db import transaction

from booking import lifecycle
from booking.models import Booking
from booking.services import create_staff_reservation
from hotel.clock import business_date
from rooms.models import Room

Status = Booking.Status


def walk_in(*, guest, room, check_out_date, identification=None, request=None):
    """
    Book and check in an arriving guest in one step. All-or-nothing: if the
    check-in fails (no ID, room not ready) the booking isn't kept either.
    `room` is a dict like a reservation room: {room_type, room?, number_of_adults, number_of_children}.
    """
    with transaction.atomic():
        booking, = create_staff_reservation(
            guest=guest, rooms=[room], check_in_date=business_date(), check_out_date=check_out_date,
            source=Booking.Source.WALK_IN, request=request,
        )
        return lifecycle.check_in(booking, identification=identification, request=request)


def room_board(day=None):
    """
    One row per room with what's happening in it on `day`: who is in it,
    who arrives, who departs. Three queries regardless of hotel size.
    """
    day = day or business_date()
    rooms = list(Room.objects.select_related('room_type').order_by('floor_number', 'room_number'))

    related = (
        Booking.objects
        .select_related('guest')
        .filter(room__in=rooms)
        .filter(
            # in house now, arriving that day, or departing that day
            status__in=[Status.CHECKED_IN, Status.CONFIRMED, Status.PENDING],
        )
        .filter(check_in_date__lte=day, check_out_date__gte=day)
    )
    in_house, arriving, departing = {}, {}, {}
    for booking in related:
        if booking.status == Status.CHECKED_IN:
            in_house[booking.room_id] = booking
            if booking.check_out_date == day:
                departing[booking.room_id] = booking
        elif booking.check_in_date == day:
            arriving[booking.room_id] = booking

    def brief(booking):
        if booking is None:
            return None
        return {
            'id': booking.pk,
            'confirmation_number': booking.confirmation_number,
            'guest_name': str(booking.guest),
            'is_vip': booking.guest.is_vip,
            'check_in_date': booking.check_in_date,
            'check_out_date': booking.check_out_date,
            'number_of_adults': booking.number_of_adults,
            'number_of_children': booking.number_of_children,
        }

    board = []
    for room in rooms:
        board.append({
            'room_id': room.pk,
            'room_number': room.room_number,
            'floor_number': room.floor_number,
            'room_type': room.room_type.name,
            'status': room.status,
            'housekeeping_status': room.housekeeping_status,
            'in_house': brief(in_house.get(room.pk)),
            'arriving': brief(arriving.get(room.pk)),
            'departing_today': room.pk in departing,
        })
    return board
