"""Hotel policies (times, cancellation), configured in settings."""
from datetime import datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.utils import timezone


def _parse_time(value):
    return time.fromisoformat(value) if isinstance(value, str) else value


def arrival_datetime(booking):
    """When the guest is due, as an aware datetime in the hotel's timezone."""
    return timezone.make_aware(datetime.combine(booking.check_in_date, _parse_time(settings.HOTEL_CHECK_IN_TIME)))


def _free_hours(booking):
    plan = getattr(booking, 'rate_plan', None)
    if plan is not None and plan.free_cancellation_hours is not None:
        return plan.free_cancellation_hours
    return settings.FREE_CANCELLATION_HOURS


def is_refundable(booking):
    plan = getattr(booking, 'rate_plan', None)
    return plan is None or plan.is_refundable


def free_cancellation_deadline(booking):
    if not is_refundable(booking):
        return None
    return arrival_datetime(booking) - timedelta(hours=_free_hours(booking))


def penalty_for(booking):
    """Charge for a late cancellation or no-show: N nights at the booked rate, capped at the stay."""
    nights = min(settings.CANCELLATION_PENALTY_NIGHTS, booking.nights)
    return (booking.price_per_night * nights).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def cancellation_penalty(booking, at=None):
    """What cancelling `booking` at `at` (default: now) would cost the guest."""
    at = at or timezone.now()
    if not is_refundable(booking):
        return booking.total_price  # non-refundable: the whole stay
    if at <= free_cancellation_deadline(booking):
        return Decimal('0.00')
    return penalty_for(booking)


def describe_cancellation_policy(booking=None):
    if booking is not None and not is_refundable(booking):
        return "Non-refundable: the full stay is charged if cancelled or not used."
    nights = settings.CANCELLATION_PENALTY_NIGHTS
    hours = _free_hours(booking) if booking is not None else settings.FREE_CANCELLATION_HOURS
    return (
        f"Free cancellation until {hours} hours before check-in "
        f"({settings.HOTEL_CHECK_IN_TIME}). Later cancellations and no-shows are charged "
        f"{nights} night{'s' if nights != 1 else ''}."
    )
