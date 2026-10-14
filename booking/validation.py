from django.conf import settings

from booking.exceptions import BookingError
from hotel.clock import business_date


def validate_stay(room_type, check_in_date, check_out_date, adults, children, *, allow_past_check_in=False):
    """Business rules every booking must satisfy, wherever it's created or modified from."""
    if not allow_past_check_in and check_in_date < business_date():
        raise BookingError("Check-in date cannot be in the past.", field='check_in_date')
    if check_in_date >= check_out_date:
        raise BookingError("Check-out date must be after check-in date.", field='check_out_date')
    if (check_out_date - check_in_date).days > settings.MAX_STAY_NIGHTS:
        raise BookingError(
            f"Stays longer than {settings.MAX_STAY_NIGHTS} nights must be arranged with management.",
            field='check_out_date',
        )
    if adults < 1:
        raise BookingError("At least one adult is required for a booking.", field='number_of_adults')
    if adults > room_type.max_adults:
        raise BookingError("Number of adults exceeds room capacity.", field='number_of_adults')
    if children > room_type.max_children:
        raise BookingError("Number of children exceeds room capacity.", field='number_of_children')
