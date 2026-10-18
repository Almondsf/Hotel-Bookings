"""
Acting on a whole booking group at once: check everyone in, check everyone
out, or cancel the lot. Each room goes through the normal lifecycle rules on
its own, so one room that isn't ready (still being cleaned, money owed)
doesn't hold up the others; the result says what happened to every room.
The guest gets one message for the group instead of one per room.
"""
from django.db import transaction

from hotel.clock import business_date
from notifications.services import notify

from . import lifecycle
from .exceptions import InvalidTransitionError
from .models import Booking

Status = Booking.Status


def group_bookings(group):
    return list(group.bookings.select_related('guest', 'room__room_type').order_by('pk'))


def _outcome(booking, error=''):
    return {'confirmation_number': booking.confirmation_number,
            'room_number': booking.room.room_number if booking.room_id else None,
            'ok': not error, 'error': error}


def _results(bookings, done, skipped):
    """Per-room outcome of a whole-group action, in the group's room order."""
    errors = {booking.pk: error.message for booking, error in skipped}
    acted = {booking.pk for booking in done}
    return [_outcome(b, errors.get(b.pk, '' if b.pk in acted else 'Not changed.')) for b in bookings]


def check_in_group(group, *, identification=None, request=None):
    """Check in every confirmed room of the group that arrives on or before today."""
    today = business_date()
    arriving = [b for b in group_bookings(group)
                if b.status == Status.CONFIRMED and b.check_in_date <= today < b.check_out_date]
    if not arriving:
        raise InvalidTransitionError("No rooms in this group are due to check in today.")
    # The group shares one booker, so an ID document recorded now covers every room
    with transaction.atomic():
        if identification:
            lifecycle.record_identification(arriving[0].guest, identification, request=request)
        done, skipped = lifecycle.check_in_many(arriving, request=request)
    return _results(arriving, done, skipped)


def check_out_group(group, *, request=None):
    """Check out every in-house room of the group; one thank-you email carries all the invoices."""
    in_house = [b for b in group_bookings(group) if b.status == Status.CHECKED_IN]
    if not in_house:
        raise InvalidTransitionError("No rooms in this group are checked in.")
    done, skipped = lifecycle.check_out_many(in_house, request=request)
    if done:
        notify('group_checked_out', done[0])
    return _results(in_house, done, skipped)


def cancellable(group):
    return [b for b in group_bookings(group) if b.status in (Status.PENDING, Status.CONFIRMED)]


def cancel_group(group, *, reason='', waive_penalty=False, request=None, by_guest=False):
    """Cancel every room still to come under the cancellation policy; one message lists them all."""
    rooms = cancellable(group)
    if not rooms:
        raise InvalidTransitionError("Nothing in this group can be cancelled.")
    done, skipped = lifecycle.cancel_many(rooms, reason=reason, waive_penalty=waive_penalty, request=request,
                                          by_guest=by_guest)
    if done:
        notify('group_cancelled', done[0])
    return _results(rooms, done, skipped)
