from datetime import date, timedelta
from decimal import Decimal
from rooms.models import Room, RoomAvailabilityOverride
from booking.models import Booking

def check_date_overlap(check_in_date_1: date, check_out_date_1: date, check_in_date_2: date, check_out_date_2: date) -> bool:
    return check_in_date_1 < check_out_date_2 and check_out_date_1 > check_in_date_2

def is_room_available(room, search_check_in_date, search_check_out_date) -> bool:
    
    # 1. Room status check
    if room.status != 'AVAILABLE':
        return False

    # 2. Availability overrides (maintenance, blocked, etc.)
    if room.availability_overrides.filter(
        start_date__lt=search_check_out_date,
        end_date__gt=search_check_in_date
    ).exists():
        return False

    # 3. Active bookings
    if room.bookings.filter(
        status__in=['CONFIRMED', 'CHECKED_IN'],
        check_in_date__lt=search_check_out_date,
        check_out_date__gt=search_check_in_date
    ).exists():
        return False

    return True

def get_available_rooms_for_type(room_type, check_in_date, check_out_date):
    return Room.objects.filter(
        room_type=room_type,
        status='AVAILABLE'
    ).exclude(
        id__in=Booking.objects.filter(
            status__in=['CONFIRMED', 'CHECKED_IN'],
            check_in_date__lt=check_out_date,
            check_out_date__gt=check_in_date
        ).values("room_id")
    ).exclude(
        id__in=RoomAvailabilityOverride.objects.filter(
            start_date__lt=check_out_date,
            end_date__gt=check_in_date
        ).values("room_id")
    )
    
    
def calculate_price_per_night(room_type, target_date: date) -> Decimal:
    pricing = room_type.pricings.filter(
        start_date__lte=target_date,
        end_date__gte=target_date
    ).first()

    if pricing:
        return pricing.price_per_night

    return room_type.base_price

def calculate_total_price(room_type, check_in_date, check_out_date) -> Decimal:
    total_price = Decimal("0.00")
    current_date = check_in_date

    number_of_nights = (check_out_date - check_in_date).days

    for _ in range(number_of_nights):
        nightly_price = calculate_price_per_night(room_type, current_date)
        total_price += nightly_price
        current_date += timedelta(days=1)

    return total_price