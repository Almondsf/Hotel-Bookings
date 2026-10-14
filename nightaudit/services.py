"""
Night audit: close the business day.

  1. Check nothing is left undone (arrivals still expected, departures not
     checked out). Pending arrivals can be marked no-show in the same run.
  2. Post the night's room charges to every in-house folio.
  3. Release lapsed online payment holds.
  4. Freeze the day's statistics and open the next business day.

Each step is idempotent, so a failed run can simply be repeated.
"""
import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from audit.models import AuditLog
from audit.services import record
from billing.services import post_room_charges
from booking import lifecycle
from booking.models import Booking
from hotel.clock import business_date
from hotel.errors import ConflictError

from . import reports
from .models import BusinessDay

logger = logging.getLogger(__name__)


def current_day():
    """The open business day, creating it from the calendar date before the first audit."""
    day = BusinessDay.objects.filter(status=BusinessDay.Status.OPEN).first()
    if day is None:
        day, _ = BusinessDay.objects.get_or_create(date=business_date(), defaults={'status': BusinessDay.Status.OPEN})
    return day


def exceptions(day):
    """What stops the day being closed."""
    pending_arrivals = Booking.objects.filter(check_in_date__lte=day, status=Booking.Status.CONFIRMED)
    unchecked_departures = Booking.objects.filter(check_out_date__lte=day, status=Booking.Status.CHECKED_IN)
    brief = lambda b: {'id': b.pk, 'confirmation_number': b.confirmation_number,  # noqa: E731
                       'guest_name': str(b.guest), 'room': b.room.room_number}
    return {
        'pending_arrivals': [brief(b) for b in pending_arrivals.select_related('guest', 'room')],
        'departures_not_checked_out': [brief(b) for b in unchecked_departures.select_related('guest', 'room')],
    }


def run(*, request, auto_no_show=False):
    with transaction.atomic():
        business_day = BusinessDay.objects.select_for_update().get(pk=current_day().pk)
        if business_day.status != BusinessDay.Status.OPEN:
            raise ConflictError("This business day is already closed.")
        day = business_day.date

        problems = exceptions(day)
        if problems['departures_not_checked_out']:
            raise ConflictError("Check out or extend the stays of guests due to leave before closing the day.")
        if problems['pending_arrivals'] and not auto_no_show:
            raise ConflictError("Some arrivals are still expected. Check them in, cancel them, or run the audit "
                                "with no-shows marked automatically.")

        no_shows = 0
        for booking in Booking.objects.filter(check_in_date__lte=day, status=Booking.Status.CONFIRMED):
            lifecycle.mark_no_show(booking, reason="Marked by night audit", request=request)
            no_shows += 1

        posted = 0
        for booking in Booking.objects.filter(status=Booking.Status.CHECKED_IN).select_related('room'):
            posted += len(post_room_charges(booking, through_date=day, request=request))

        expired = lifecycle.expire_holds()

        business_day.status = BusinessDay.Status.CLOSED
        business_day.closed_at = timezone.now()
        business_day.closed_by = request.user
        business_day.save()
        next_day = BusinessDay.objects.create(date=day + timedelta(days=1), status=BusinessDay.Status.OPEN)

        # With the day closed, its figures come from what was actually posted
        statistics = reports.flash(day)
        statistics['in_house'] = Booking.objects.filter(status=Booking.Status.CHECKED_IN).count()
        business_day.statistics = _jsonable(statistics)
        business_day.save(update_fields=['statistics'])

    summary = {'closed': str(day), 'opened': str(next_day.date), 'room_charges_posted': posted,
               'no_shows': no_shows, 'holds_expired': expired}
    record(AuditLog.Action.NIGHT_AUDIT_RUN, request=request, target=business_day, changes=summary)
    logger.info("Night audit closed %s: %s", day, summary)
    return business_day, summary


def _jsonable(value):
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, (int, float, bool, str)) or value is None:
        return value
    return str(value)  # Decimal, date
