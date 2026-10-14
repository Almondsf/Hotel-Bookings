"""
Booking status changes. Every transition goes through this module so the
rules in Booking.TRANSITIONS, row locking, timestamps and the audit trail are
applied consistently.
"""
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from audit.models import AuditLog
from audit.services import record
from billing import services as billing
from billing.exceptions import BillingError
from billing.models import ChargeCategory
from booking.allocation import allocate_room, lock_room_types
from booking.exceptions import BookingError, InvalidTransitionError, RoomUnavailableError
from booking.models import Booking, GuestIdentification
from booking.policies import cancellation_penalty, penalty_for
from booking.pricing import reprice
from booking.validation import validate_stay
from hotel.clock import business_date
from housekeeping.services import mark_dirty
from locks.services import revoke_keys
from notifications.services import notify
from rooms.models import Room
from rooms.services import get_available_rooms_for_type

Status = Booking.Status
HOLD_EXPIRED_REASON = "Payment hold expired"


def _lock(booking):
    """Re-read the booking under a row lock so concurrent actions are serialized."""
    return Booking.objects.select_for_update().get(pk=booking.pk)


def _ensure_can_become(booking, new_status):
    if new_status not in Booking.TRANSITIONS[booking.status]:
        raise InvalidTransitionError(
            f"A {booking.get_status_display().lower()} booking cannot be changed to "
            f"{Status(new_status).label.lower()}."
        )


def confirm(booking):
    """PENDING -> CONFIRMED, e.g. once payment succeeds. Caller provides the transaction."""
    booking = _lock(booking)
    _ensure_can_become(booking, Status.CONFIRMED)
    booking.status = Status.CONFIRMED
    booking.confirmed_at = timezone.now()
    booking.hold_expires_at = None
    booking.save(update_fields=['status', 'confirmed_at', 'hold_expires_at', 'updated_at'])
    return booking


def record_identification(guest, document, *, request=None):
    """Store an ID document seen at the desk. `document` holds the GuestIdentification fields."""
    identification = GuestIdentification.objects.create(
        guest=guest, captured_by=request.user if request is not None else None, **document,
    )
    record(AuditLog.Action.GUEST_ID_CAPTURED, request=request, target=guest,
           changes={'document_type': identification.document_type, 'number_last4': identification.number_last4})
    return identification


def confirm_paid_booking(booking):
    """
    Confirm an online booking whose payment has just succeeded. If the
    payment arrived after the hold lapsed, the room may have been resold, so
    a free room of the same type is found again; raises RoomUnavailableError
    when there is none (the caller refunds).
    """
    with transaction.atomic():
        booking = _lock(booking)
        if booking.status == Status.CONFIRMED:
            return booking
        hold_lapsed = (
            booking.status == Status.CANCELLED and booking.cancellation_reason == HOLD_EXPIRED_REASON
        ) or (booking.status == Status.PENDING and booking.hold_expires_at and booking.hold_expires_at <= timezone.now())
        if booking.status != Status.PENDING and not hold_lapsed:
            raise InvalidTransitionError(f"A {booking.get_status_display().lower()} booking can't be confirmed.")

        if hold_lapsed:
            room_type = Room.objects.get(pk=booking.room_id).room_type
            lock_room_types([room_type])
            free = get_available_rooms_for_type(room_type, booking.check_in_date, booking.check_out_date,
                                                exclude_booking=booking)
            room = free.filter(pk=booking.room_id).first() or free.first()
            if room is None:
                raise RoomUnavailableError("The room was released before payment completed and is no longer available.")
            booking.room = room
            booking.cancelled_at = None
            booking.cancellation_reason = ''

        booking.status = Status.CONFIRMED
        booking.confirmed_at = timezone.now()
        booking.hold_expires_at = None
        booking.save()
    record(AuditLog.Action.BOOKING_CONFIRMED, target=booking, changes={'after_lapsed_hold': bool(hold_lapsed)})
    return booking


def check_in(booking, *, identification=None, request=None):
    """
    Check the guest in. `identification` optionally records an ID document
    in the same step; with REQUIRE_GUEST_ID_AT_CHECK_IN a valid one must be
    on file.
    """
    with transaction.atomic():
        booking = _lock(booking)
        _ensure_can_become(booking, Status.CHECKED_IN)

        if identification:
            record_identification(booking.guest, identification, request=request)
        if settings.REQUIRE_GUEST_ID_AT_CHECK_IN and not booking.guest.has_valid_identification:
            raise BookingError("A valid ID document must be recorded before check-in.", field='identification')

        today = business_date()
        if today < booking.check_in_date:
            raise BookingError(f"This booking arrives on {booking.check_in_date}; it can't be checked in yet.")
        if today >= booking.check_out_date:
            raise BookingError("This booking's stay has already ended.")

        room = Room.objects.select_for_update().get(pk=booking.room_id)
        if room.status in Room.UNSELLABLE_STATUSES:
            raise RoomUnavailableError(
                f"Room {room.room_number} is {room.get_status_display().lower()}. Move the booking to another room first."
            )
        ready = ([Room.Housekeeping.INSPECTED] if settings.REQUIRE_ROOM_INSPECTION
                 else [Room.Housekeeping.CLEAN, Room.Housekeeping.INSPECTED])
        if settings.REQUIRE_CLEAN_ROOM_AT_CHECK_IN and room.housekeeping_status not in ready:
            raise RoomUnavailableError(
                f"Room {room.room_number} is {room.get_housekeeping_status_display().lower()}; "
                "housekeeping must finish it first (or move the guest to a ready room)."
            )
        if Booking.objects.filter(room=room, status=Status.CHECKED_IN).exclude(pk=booking.pk).exists():
            raise RoomUnavailableError(f"Room {room.room_number} is still occupied by an in-house guest.")

        booking.status = Status.CHECKED_IN
        booking.checked_in_at = timezone.now()
        booking.save(update_fields=['status', 'checked_in_at', 'updated_at'])
        billing.folio_for(booking)  # open the bill so extras can be posted from the first hour
        room.status = Room.Status.OCCUPIED
        room.save(update_fields=['status', 'updated_at'])

    record(AuditLog.Action.BOOKING_CHECKED_IN, request=request, target=booking, changes={'room': room.room_number})
    return booking


def _last_night_stayed(booking):
    """The last night to bill: the night before departure, or before today for an early departure."""
    today = business_date()
    departure = min(booking.check_out_date, max(today, booking.check_in_date + timedelta(days=1)))
    return departure - timedelta(days=1)


def bring_folio_up_to_date(booking, *, request=None):
    """Post room charges through the last night stayed, so the desk can present the bill."""
    if booking.status != Status.CHECKED_IN:
        raise InvalidTransitionError("Only in-house bookings have room charges to post.")
    with transaction.atomic():
        billing.post_room_charges(_lock(booking), through_date=_last_night_stayed(booking), request=request)
    return billing.folio_for(booking)


def check_out(booking, *, transfer_to_account=None, request=None):
    """
    Post any unbilled room nights, then close the folio: settle it if paid,
    or bill it to `transfer_to_account` (city ledger). With
    CHECKOUT_REQUIRES_SETTLED_FOLIO, check-out is refused while money is owed.
    """
    with transaction.atomic():
        booking = _lock(booking)
        _ensure_can_become(booking, Status.CHECKED_OUT)

        billing.post_room_charges(booking, through_date=_last_night_stayed(booking), request=request)
        folio = billing.folio_for(booking)
        if transfer_to_account is not None:
            billing.transfer_to_account(folio, transfer_to_account, request=request)
        elif folio.balance == 0:
            billing.settle(folio, request=request)
        elif settings.CHECKOUT_REQUIRES_SETTLED_FOLIO and folio.balance > 0:
            raise BillingError(
                f"The guest owes {folio.balance} {folio.currency}. Take payment or bill it to a company account first.",
            )

        booking.status = Status.CHECKED_OUT
        booking.checked_out_at = timezone.now()
        booking.save(update_fields=['status', 'checked_out_at', 'updated_at'])

        room = Room.objects.select_for_update().get(pk=booking.room_id)
        if room.status == Room.Status.OCCUPIED:
            room.status = Room.Status.AVAILABLE
            room.save(update_fields=['status', 'updated_at'])
        mark_dirty(room, request=request, reason=f"Check-out {booking.confirmation_number}")

    revoke_keys(booking, reason='Checked out', request=request)
    notify('checked_out', booking)
    early = business_date() < booking.check_out_date
    record(AuditLog.Action.BOOKING_CHECKED_OUT, request=request, target=booking,
           changes={'early_departure': early} if early else None)
    return booking


def _post_penalty(booking, description, request):
    """Charge the policy penalty to the folio, where it nets against any prepayment."""
    if booking.penalty_amount > 0:
        billing.post_charge(
            billing.folio_for(booking), category=ChargeCategory.PENALTY,
            description=f"{description} - {booking.confirmation_number}",
            unit_price=booking.penalty_amount, source=f'booking:{booking.pk}', request=request,
        )


def _apply_penalty(booking, penalty, waive, reason):
    if waive and penalty > 0:
        if not reason:
            raise BookingError("A reason is required to waive the penalty.", field='reason')
        booking.penalty_waived = True
        booking.penalty_amount = Decimal('0.00')
    else:
        booking.penalty_amount = penalty


def cancel(booking, *, reason='', waive_penalty=False, request=None, by_guest=False):
    """
    Cancel a pending or confirmed booking, applying the cancellation policy.
    Unpaid holds are released free of charge. Only staff may waive penalties.
    """
    if by_guest and waive_penalty:
        raise BookingError("Guests cannot waive cancellation penalties.")

    with transaction.atomic():
        booking = _lock(booking)
        _ensure_can_become(booking, Status.CANCELLED)

        penalty = Decimal('0.00') if booking.status == Status.PENDING else cancellation_penalty(booking)
        _apply_penalty(booking, penalty, waive_penalty, reason)
        booking.status = Status.CANCELLED
        booking.cancelled_at = timezone.now()
        booking.cancellation_reason = reason
        booking.save(update_fields=[
            'status', 'cancelled_at', 'cancellation_reason', 'penalty_amount', 'penalty_waived', 'updated_at',
        ])
        _post_penalty(booking, "Late cancellation fee", request)

    notify('booking_cancelled', booking)
    record(AuditLog.Action.BOOKING_CANCELLED, request=request, target=booking,
           actor_email=booking.guest.email if by_guest else '',
           changes={'penalty': str(booking.penalty_amount), 'waived': booking.penalty_waived,
                    'policy_penalty': str(penalty), 'by_guest': by_guest, 'reason': reason})
    return booking


def mark_no_show(booking, *, waive_penalty=False, reason='', request=None):
    with transaction.atomic():
        booking = _lock(booking)
        _ensure_can_become(booking, Status.NO_SHOW)
        if business_date() < booking.check_in_date:
            raise BookingError("A booking can't be marked as a no-show before its arrival date.")

        penalty = penalty_for(booking)
        _apply_penalty(booking, penalty, waive_penalty, reason)
        booking.status = Status.NO_SHOW
        booking.cancellation_reason = reason
        booking.save(update_fields=['status', 'cancellation_reason', 'penalty_amount', 'penalty_waived', 'updated_at'])
        _post_penalty(booking, "No-show fee", request)

    record(AuditLog.Action.BOOKING_NO_SHOW, request=request, target=booking,
           changes={'penalty': str(booking.penalty_amount), 'waived': booking.penalty_waived})
    return booking


def expire_holds(now=None):
    """Cancel PENDING bookings whose payment hold has lapsed. Returns how many were expired."""
    now = now or timezone.now()
    expired = 0
    candidates = Booking.objects.filter(status=Status.PENDING, hold_expires_at__lte=now).values_list('pk', flat=True)
    for pk in candidates:
        with transaction.atomic():
            booking = Booking.objects.select_for_update().get(pk=pk)
            # Re-check under the lock: payment may have confirmed it meanwhile
            if booking.status != Status.PENDING or booking.hold_expires_at > now:
                continue
            booking.status = Status.CANCELLED
            booking.cancelled_at = now
            booking.cancellation_reason = HOLD_EXPIRED_REASON
            booking.save(update_fields=['status', 'cancelled_at', 'cancellation_reason', 'updated_at'])
        record(AuditLog.Action.BOOKING_HOLD_EXPIRED, target=booking)
        expired += 1
    return expired


MODIFIABLE_FIELDS = {'check_in_date', 'check_out_date', 'room_type', 'room', 'number_of_adults',
                     'number_of_children', 'special_requests'}
IN_HOUSE_MODIFIABLE_FIELDS = {'check_out_date', 'number_of_adults', 'number_of_children', 'special_requests'}


def modify(booking, changes, *, request=None):
    """
    Change dates, room type/room, party size or requests. Availability is
    re-checked (ignoring the booking's own hold). Added nights are priced at
    current rates; nights already booked keep their agreed rate unless the
    room type changes.

    In-house guests may only change their departure date, party size and
    requests; moving rooms is a front-desk room move.
    """
    unknown = set(changes) - MODIFIABLE_FIELDS
    if unknown:
        raise BookingError(f"Cannot modify: {', '.join(sorted(unknown))}.")

    with transaction.atomic():
        booking = _lock(booking)
        if booking.status not in Booking.MODIFIABLE_STATUSES:
            raise InvalidTransitionError(f"A {booking.get_status_display().lower()} booking can't be modified.")
        if booking.status == Status.CHECKED_IN:
            not_allowed = set(changes) - IN_HOUSE_MODIFIABLE_FIELDS
            if not_allowed:
                raise BookingError(f"In-house bookings can't change: {', '.join(sorted(not_allowed))}.")

        current_room = Room.objects.select_related('room_type').get(pk=booking.room_id)
        old_room_type = current_room.room_type
        room_type = changes.get('room_type') or (changes['room'].room_type if changes.get('room') else old_room_type)
        check_in_date = changes.get('check_in_date', booking.check_in_date)
        check_out_date = changes.get('check_out_date', booking.check_out_date)
        adults = changes.get('number_of_adults', booking.number_of_adults)
        children = changes.get('number_of_children', booking.number_of_children)

        if booking.status == Status.CHECKED_IN and check_out_date <= business_date():
            raise BookingError("Use check-out to end an in-house stay.", field='check_out_date')
        validate_stay(room_type, check_in_date, check_out_date, adults, children,
                      allow_past_check_in=check_in_date == booking.check_in_date)

        dates_changed = (check_in_date, check_out_date) != (booking.check_in_date, booking.check_out_date)
        type_changed = room_type.pk != old_room_type.pk
        room = current_room
        if dates_changed or type_changed or changes.get('room'):
            lock_room_types({room_type, old_room_type})
            preferred = changes.get('room')
            if preferred is None and not type_changed and get_available_rooms_for_type(
                room_type, check_in_date, check_out_date, exclude_booking=booking,
            ).filter(pk=current_room.pk).exists():
                preferred = current_room  # keep the guest in their room if it's still free
            room = allocate_room(room_type, check_in_date, check_out_date,
                                 preferred_room=preferred, exclude_booking=booking)

        before = _snapshot(booking)
        booking.room = room
        booking.check_in_date = check_in_date
        booking.check_out_date = check_out_date
        booking.number_of_adults = adults
        booking.number_of_children = children
        if 'special_requests' in changes:
            booking.special_requests = changes['special_requests']
        booking.save()
        if dates_changed or type_changed:
            # A new room type re-prices every night still to come; date changes
            # only price the added nights and keep the agreed rates for the rest.
            reprice_from = (max(check_in_date, business_date()) if type_changed else None)
            reprice(booking, room_type, reprice_from=reprice_from)

    after = _snapshot(booking)
    diff = {k: {'from': v, 'to': after[k]} for k, v in before.items() if after[k] != v}
    if diff:
        record(AuditLog.Action.BOOKING_MODIFIED, request=request, target=booking, changes=diff)
    return booking


def move_room(booking, new_room, *, reason, reprice_stay=False, request=None):
    """
    Move a booking to another room (upgrade, fault, guest request). In-house
    guests move from tonight. Rates are kept unless `reprice_stay`, which
    re-prices the remaining nights at the new room type's rates.
    """
    if not reason:
        raise BookingError("A reason is required for a room move.", field='reason')

    with transaction.atomic():
        booking = _lock(booking)
        if booking.status not in Booking.MODIFIABLE_STATUSES:
            raise InvalidTransitionError(f"A {booking.get_status_display().lower()} booking can't be moved.")
        if new_room.pk == booking.room_id:
            raise BookingError("The booking is already in this room.", field='room')

        old_room = Room.objects.select_related('room_type').get(pk=booking.room_id)
        in_house = booking.status == Status.CHECKED_IN
        move_from = max(business_date(), booking.check_in_date) if in_house else booking.check_in_date

        lock_room_types({new_room.room_type, old_room.room_type})
        allocate_room(new_room.room_type, move_from, booking.check_out_date,
                      preferred_room=new_room, exclude_booking=booking)
        if in_house and Booking.objects.filter(room=new_room, status=Status.CHECKED_IN).exists():
            raise RoomUnavailableError(f"Room {new_room.room_number} is occupied.")

        booking.room = new_room
        booking.save(update_fields=['room', 'updated_at'])
        if reprice_stay:
            reprice(booking, new_room.room_type, reprice_from=move_from)
        if in_house:
            Room.objects.filter(pk=old_room.pk, status=Room.Status.OCCUPIED).update(
                status=Room.Status.AVAILABLE, updated_at=timezone.now())
            mark_dirty(old_room, request=request, reason=f"Room move {booking.confirmation_number}")
            revoke_keys(booking, reason='Room move', room=old_room, request=request)
            Room.objects.filter(pk=new_room.pk).update(status=Room.Status.OCCUPIED, updated_at=timezone.now())

    record(AuditLog.Action.BOOKING_ROOM_MOVED, request=request, target=booking, changes={
        'from': old_room.room_number, 'to': new_room.room_number, 'reason': reason,
        'repriced': reprice_stay, 'total_price': str(booking.total_price),
    })
    return booking


def _snapshot(booking):
    return {
        'room': booking.room.room_number,
        'check_in_date': str(booking.check_in_date),
        'check_out_date': str(booking.check_out_date),
        'number_of_adults': booking.number_of_adults,
        'number_of_children': booking.number_of_children,
        'special_requests': booking.special_requests or '',
        'total_price': str(booking.total_price),
    }
