"""Nightly rates of a booking: the price agreed for each night."""
from decimal import ROUND_HALF_UP, Decimal

from booking.models import BookingNight

CENT = Decimal('0.01')


def summarize(rates):
    total = sum((rate for _, rate in rates), Decimal('0.00'))
    average = (total / len(rates)).quantize(CENT, rounding=ROUND_HALF_UP) if rates else Decimal('0.00')
    return total, average


def create_nights(booking, rates):
    BookingNight.objects.bulk_create(BookingNight(booking=booking, date=d, rate=r) for d, r in rates)


def reprice(booking, room_type, *, reprice_from=None):
    """
    Bring the booking's nights in line with its current dates.

    Nights that already have an agreed rate keep it; new nights are priced
    at current rates. Nights on or after `reprice_from` are re-priced even if
    they had a rate (e.g. after a room-type change). Updates and saves the
    booking's totals.
    """
    nights = {night.date: night for night in booking.nightly_rates.all()}
    final = []
    for date, quote in stay_rates(booking, room_type):
        keep = date in nights and (reprice_from is None or date < reprice_from)
        final.append((date, nights[date].rate if keep else quote))

    # Nights dropped, changed and added: one query each, not one per night
    booking.nightly_rates.exclude(date__in=[d for d, _ in final]).delete()
    changed = []
    for date, rate in final:
        if date in nights and nights[date].rate != rate:
            nights[date].rate = rate
            changed.append(nights[date])
    BookingNight.objects.bulk_update(changed, ['rate'])
    BookingNight.objects.bulk_create(BookingNight(booking=booking, date=date, rate=rate)
                                     for date, rate in final if date not in nights)

    booking.total_price, booking.price_per_night = summarize(final)
    booking.save(update_fields=['total_price', 'price_per_night', 'updated_at'])


def stay_rates(booking, room_type):
    """Current prices for the booking's dates under its rate plan (or its manager override)."""
    from rates.engine import plan_nightly_rates
    from rooms.services import nightly_rates

    if booking.nightly_rate_override is not None:
        return [(date, booking.nightly_rate_override) for date, _ in
                nightly_rates(room_type, booking.check_in_date, booking.check_out_date)]
    return plan_nightly_rates(booking.rate_plan, room_type, booking.check_in_date, booking.check_out_date)
