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
from audit.services import record, record_many
from billing import services as billing
from billing.exceptions import BillingError
from billing.models import ChargeCategory
from booking.allocation import allocate_room, lock_room_types
from booking.exceptions import BookingError, InvalidTransitionError, RoomUnavailableError
from booking.models import Booking, GuestIdentification, valid_identifications
from booking.signals import bookings_saved
from booking.policies import cancellation_penalty, penalty_for
from booking.pricing import reprice
from booking.validation import validate_stay
from hotel.clock import business_date
from hotel.money import money
from housekeeping.services import mark_dirty, set_rooms_status
from locks.services import revoke_keys, revoke_keys_for
from notifications.services import notify
from rooms.models import Room
from rooms.services import free_rooms, get_available_rooms_for_type

Status = Booking.Status
HOLD_EXPIRED_REASON = "Payment hold expired"


def _lock(booking):
    """Re-read the booking under a row lock so concurrent actions are serialized."""
    return Booking.objects.select_for_update().get(pk=booking.pk)


def _lock_many(bookings):
    """Re-read several bookings under row locks in one query (id order, so requests can't deadlock)."""
    ids = sorted({booking.pk for booking in bookings})
    return list(Booking.objects.select_for_update(of=('self',)).select_related('guest', 'rate_plan', 'group')
                .filter(pk__in=ids).order_by('pk'))


def _ensure_can_become(booking, new_status):
    if new_status not in Booking.TRANSITIONS[booking.status]:
        raise InvalidTransitionError(
            f"A {booking.get_status_display().lower()} booking cannot be changed to "
            f"{Status(new_status).label.lower()}."
        )


def _only(done, skipped):
    """The single booking a one-item batch acted on, or the error that stopped it."""
    if skipped:
        raise skipped[0][1]
    return done[0]


def _saved(bookings, fields):
    """Write `fields` of the bookings in one query and tell listeners (bulk_update sends no post_save)."""
    if bookings:
        now = timezone.now()
        for booking in bookings:
            booking.updated_at = now
        Booking.objects.bulk_update(bookings, [*fields, 'updated_at'])
        bookings_saved.send(sender=Booking, bookings=bookings)


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
    return confirm_paid_bookings([booking])[0]


def confirm_paid_bookings(bookings):
    """
    Confirm online bookings whose (shared) payment has just succeeded, all or
    none, in a fixed number of queries. If the payment arrived after a hold
    lapsed, that room may have been resold, so a free room of the same type is
    found again; raises RoomUnavailableError when there is none (the caller
    refunds). Bookings already confirmed are left as they are.
    """
    now = timezone.now()
    with transaction.atomic():
        locked = _lock_many(bookings)
        todo, lapsed = [], set()
        for booking in locked:
            if booking.status == Status.CONFIRMED:
                continue
            hold_lapsed = (
                booking.status == Status.CANCELLED and booking.cancellation_reason == HOLD_EXPIRED_REASON
            ) or (booking.status == Status.PENDING and booking.hold_expires_at and booking.hold_expires_at <= now)
            if booking.status != Status.PENDING and not hold_lapsed:
                raise InvalidTransitionError(f"A {booking.get_status_display().lower()} booking can't be confirmed.")
            todo.append(booking)
            if hold_lapsed:
                lapsed.add(booking.pk)
        if lapsed:
            _reallocate([b for b in todo if b.pk in lapsed])
        for booking in todo:
            booking.status = Status.CONFIRMED
            booking.confirmed_at = now
            booking.hold_expires_at = None
        _saved(todo, ['status', 'confirmed_at', 'hold_expires_at', 'room', 'cancelled_at', 'cancellation_reason'])
    record_many(AuditLog.Action.BOOKING_CONFIRMED, todo, changes=lambda b: {'after_lapsed_hold': b.pk in lapsed})
    return locked


def _reallocate(bookings):
    """Give bookings whose hold lapsed a free room again: their own if still free, else another of the type."""
    rooms = Room.objects.select_related('room_type').in_bulk([b.room_id for b in bookings])
    lock_room_types(room.room_type for room in rooms.values())
    taken = set()
    by_stay = {}
    for booking in bookings:
        by_stay.setdefault((booking.check_in_date, booking.check_out_date), []).append(booking)
    for (check_in_date, check_out_date), stay in by_stay.items():  # one query per distinct stay (one for a group)
        free = list(free_rooms(check_in_date, check_out_date, exclude_bookings=stay)
                    .filter(room_type__in={rooms[b.room_id].room_type_id for b in stay}))
        for booking in stay:
            room_type_id = rooms[booking.room_id].room_type_id
            room = next((r for r in free if r.pk == booking.room_id and r.pk not in taken), None) or \
                next((r for r in free if r.room_type_id == room_type_id and r.pk not in taken), None)
            if room is None:
                raise RoomUnavailableError("The room was released before payment completed and is no longer available.")
            taken.add(room.pk)
            booking.room = room
            booking.cancelled_at = None
            booking.cancellation_reason = ''


def check_in(booking, *, identification=None, request=None):
    """
    Check the guest in. `identification` optionally records an ID document
    in the same step; with REQUIRE_GUEST_ID_AT_CHECK_IN a valid one must be
    on file.
    """
    with transaction.atomic():  # a failed check-in doesn't keep the ID document either
        if identification:
            record_identification(_lock(booking).guest, identification, request=request)
        return _only(*check_in_many([booking], request=request))


def check_in_many(bookings, *, request=None):
    """
    Check several bookings in together (a group), in a fixed number of
    queries. Each follows the same rules as a single check-in; one that can't
    go ahead (room not ready, no ID, wrong day) is skipped with the reason.
    Returns (checked_in, skipped) where skipped is [(booking, error)].
    """
    today, now = business_date(), timezone.now()
    ready = ([Room.Housekeeping.INSPECTED] if settings.REQUIRE_ROOM_INSPECTION
             else [Room.Housekeeping.CLEAN, Room.Housekeeping.INSPECTED])
    with transaction.atomic():
        locked = _lock_many(bookings)
        rooms = {room.pk: room for room in Room.objects.select_for_update(of=('self',)).select_related('room_type')
                 .filter(pk__in=sorted({b.room_id for b in locked})).order_by('pk')}
        occupied = set(Booking.objects.filter(room__in=rooms, status=Status.CHECKED_IN)
                       .exclude(pk__in=[b.pk for b in locked]).values_list('room_id', flat=True))
        with_id = set(valid_identifications().filter(guest__in={b.guest_id for b in locked})
                      .values_list('guest_id', flat=True)) if settings.REQUIRE_GUEST_ID_AT_CHECK_IN else set()

        done, skipped = [], []
        for booking in locked:
            room = rooms[booking.room_id]
            try:
                _ensure_can_become(booking, Status.CHECKED_IN)
                if settings.REQUIRE_GUEST_ID_AT_CHECK_IN and booking.guest_id not in with_id:
                    raise BookingError("A valid ID document must be recorded before check-in.", field='identification')
                if today < booking.check_in_date:
                    raise BookingError(f"This booking arrives on {booking.check_in_date}; it can't be checked in yet.")
                if today >= booking.check_out_date:
                    raise BookingError("This booking's stay has already ended.")
                if room.status in Room.UNSELLABLE_STATUSES:
                    raise RoomUnavailableError(f"Room {room.room_number} is {room.get_status_display().lower()}. "
                                               "Move the booking to another room first.")
                if settings.REQUIRE_CLEAN_ROOM_AT_CHECK_IN and room.housekeeping_status not in ready:
                    raise RoomUnavailableError(
                        f"Room {room.room_number} is {room.get_housekeeping_status_display().lower()}; "
                        "housekeeping must finish it first (or move the guest to a ready room)."
                    )
                if room.pk in occupied:
                    raise RoomUnavailableError(f"Room {room.room_number} is still occupied by an in-house guest.")
            except BookingError as e:
                skipped.append((booking, e))
                continue
            booking.status = Status.CHECKED_IN
            booking.checked_in_at = now
            room.status = Room.Status.OCCUPIED
            room.updated_at = now
            occupied.add(room.pk)
            done.append(booking)

        _saved(done, ['status', 'checked_in_at'])
        Room.objects.bulk_update([rooms[b.room_id] for b in done], ['status', 'updated_at'])
        billing.folios_for(done)  # open the bills so extras can be posted from the first hour

    record_many(AuditLog.Action.BOOKING_CHECKED_IN, done, request=request,
                changes=lambda b: {'room': rooms[b.room_id].room_number})
    return done, skipped


def _last_night_stayed(booking, today=None):
    """The last night to bill: the night before departure, or before today for an early departure."""
    today = today or business_date()
    departure = min(booking.check_out_date, max(today, booking.check_in_date + timedelta(days=1)))
    return departure - timedelta(days=1)


def bring_folio_up_to_date(booking, *, request=None):
    """Post room charges through the last night stayed, so the desk can present the bill."""
    if booking.status != Status.CHECKED_IN:
        raise InvalidTransitionError("Only in-house bookings have room charges to post.")
    with transaction.atomic():
        billing.post_room_charges(_lock(booking), through_date=_last_night_stayed(booking), request=request)
    return billing.folio_for(booking)


def check_out(booking, *, transfer_to_account=None, request=None, notify_guest=True):
    """
    Post any unbilled room nights, then close the folio: settle it if paid,
    or bill it to `transfer_to_account` (city ledger). With
    CHECKOUT_REQUIRES_SETTLED_FOLIO, check-out is refused while money is owed.
    `notify_guest=False` leaves the thank-you to the caller (a group check-out sends one).
    """
    with transaction.atomic():  # a refused check-out doesn't keep the room charges it posted either
        booking = _only(*check_out_many([booking], transfer_to_account=transfer_to_account, request=request))
    if notify_guest:
        notify('checked_out', booking)
    return booking


def check_out_many(bookings, *, transfer_to_account=None, request=None):
    """
    Check several bookings out together (a group), in a fixed number of
    queries: room nights posted, paid bills settled with their invoices,
    rooms freed and marked for cleaning, keys revoked. A booking whose bill
    still owes money (with CHECKOUT_REQUIRES_SETTLED_FOLIO) is skipped with the
    reason and stays in house. Returns (checked_out, skipped). The caller
    sends the guest's thank-you.
    """
    today, now = business_date(), timezone.now()
    with transaction.atomic():
        candidates, skipped = [], []
        for booking in _lock_many(bookings):
            try:
                _ensure_can_become(booking, Status.CHECKED_OUT)
            except InvalidTransitionError as e:
                skipped.append((booking, e))
                continue
            candidates.append(booking)

        billing.post_room_charges_for(candidates, through_date={b.pk: _last_night_stayed(b, today) for b in candidates},
                                      request=request)
        folios = billing.folios_for(candidates)
        credits = billing.folio_credits(folios.values())
        done, to_settle = [], []
        for booking in candidates:
            folio, balance = folios[booking.pk], -credits[folios[booking.pk].pk]
            if transfer_to_account is None and settings.CHECKOUT_REQUIRES_SETTLED_FOLIO and balance > 0:
                skipped.append((booking, BillingError(
                    f"The guest owes {money(balance)} {folio.currency}. Take payment or bill it to a company account first.")))
                continue
            if transfer_to_account is None and balance == 0:
                to_settle.append(folio)
            done.append(booking)
        if transfer_to_account is not None:
            for booking in done:  # the city-ledger transfer checks the company's credit for each bill in turn
                billing.transfer_to_account(folios[booking.pk], transfer_to_account, request=request)
        billing.settle_many(to_settle, request=request)

        for booking in done:
            booking.status = Status.CHECKED_OUT
            booking.checked_out_at = now
        _saved(done, ['status', 'checked_out_at'])
        rooms = list(Room.objects.select_for_update(of=('self',)).select_related('room_type')
                     .filter(pk__in=sorted({b.room_id for b in done})).order_by('pk'))
        freed = [room for room in rooms if room.status == Room.Status.OCCUPIED]
        for room in freed:
            room.status = Room.Status.AVAILABLE
            room.updated_at = now
        Room.objects.bulk_update(freed, ['status', 'updated_at'])
        set_rooms_status(rooms, Room.Housekeeping.DIRTY, request=request,
                         reasons={b.room_id: f"Check-out {b.confirmation_number}" for b in done})

    revoke_keys_for(done, reason='Checked out', request=request)
    record_many(AuditLog.Action.BOOKING_CHECKED_OUT, done, request=request,
                changes=lambda b: {'early_departure': True} if today < b.check_out_date else None)
    return done, skipped


def _post_penalties(bookings, description, request):
    """Charge each booking's policy penalty to its folio, where it nets against any prepayment (all at once)."""
    charged = [b for b in bookings if b.penalty_amount > 0]
    if not charged:
        return
    folios = billing.folios_for(charged)
    billing.post_charges([{
        'folio': folios[booking.pk], 'category': ChargeCategory.PENALTY,
        'description': f"{description} - {booking.confirmation_number}",
        'unit_price': booking.penalty_amount, 'source': f'booking:{booking.pk}',
    } for booking in charged], request=request)


def _apply_penalty(booking, penalty, waive, reason):
    if waive and penalty > 0:
        if not reason:
            raise BookingError("A reason is required to waive the penalty.", field='reason')
        booking.penalty_waived = True
        booking.penalty_amount = Decimal('0.00')
    else:
        booking.penalty_amount = penalty


def cancel(booking, *, reason='', waive_penalty=False, request=None, by_guest=False, notify_guest=True):
    """
    Cancel a pending or confirmed booking, applying the cancellation policy.
    Unpaid holds are released free of charge. Only staff may waive penalties.
    `notify_guest=False` leaves the message to the caller (a group cancellation sends one).
    """
    booking = _only(*cancel_many([booking], reason=reason, waive_penalty=waive_penalty, request=request,
                                 by_guest=by_guest))
    if notify_guest:
        notify('booking_cancelled', booking)
    return booking


def cancel_many(bookings, *, reason='', waive_penalty=False, request=None, by_guest=False):
    """
    Cancel several bookings together (a group) under the cancellation policy,
    in a fixed number of queries: one lock, one update, the fees posted
    together, one audit insert, and money prepaid online beyond the fees
    refunded once per payment rather than once per room. A booking that can't
    be cancelled is skipped with the reason. Returns (cancelled, skipped).
    """
    if by_guest and waive_penalty:
        raise BookingError("Guests cannot waive cancellation penalties.")

    now = timezone.now()
    with transaction.atomic():
        done, skipped, policy = [], [], {}
        for booking in _lock_many(bookings):
            try:
                _ensure_can_become(booking, Status.CANCELLED)
            except InvalidTransitionError as e:
                skipped.append((booking, e))
                continue
            penalty = Decimal('0.00') if booking.status == Status.PENDING else cancellation_penalty(booking, at=now)
            _apply_penalty(booking, penalty, waive_penalty, reason)
            policy[booking.pk] = penalty
            booking.status = Status.CANCELLED
            booking.cancelled_at = now
            booking.cancellation_reason = reason
            done.append(booking)
        _saved(done, ['status', 'cancelled_at', 'cancellation_reason', 'penalty_amount', 'penalty_waived'])
        _post_penalties(done, "Late cancellation fee", request)

    record_many(AuditLog.Action.BOOKING_CANCELLED, done, request=request,
                actor_email=done[0].guest.email if by_guest and done else '',
                changes=lambda b: {'penalty': str(b.penalty_amount), 'waived': b.penalty_waived,
                                   'policy_penalty': str(policy[b.pk]), 'by_guest': by_guest, 'reason': reason})
    # Money prepaid online beyond the fee goes straight back to the guest's card (outside the
    # cancellation's transaction: a slow or failing gateway never blocks the cancellation itself)
    from payments.services import refund_prepaid_remainders
    refund_prepaid_remainders(done, request=request)
    return done, skipped


def mark_no_show(booking, *, waive_penalty=False, reason='', request=None):
    return _only(*mark_no_shows([booking], waive_penalty=waive_penalty, reason=reason, request=request))


def mark_no_shows(bookings, *, waive_penalty=False, reason='', request=None):
    """Mark several bookings as no-shows (the night audit), fees posted together. Returns (marked, skipped)."""
    today = business_date()
    with transaction.atomic():
        done, skipped = [], []
        for booking in _lock_many(bookings):
            try:
                _ensure_can_become(booking, Status.NO_SHOW)
                if today < booking.check_in_date:
                    raise BookingError("A booking can't be marked as a no-show before its arrival date.")
            except BookingError as e:
                skipped.append((booking, e))
                continue
            _apply_penalty(booking, penalty_for(booking), waive_penalty, reason)
            booking.status = Status.NO_SHOW
            booking.cancellation_reason = reason
            done.append(booking)
        _saved(done, ['status', 'cancellation_reason', 'penalty_amount', 'penalty_waived'])
        _post_penalties(done, "No-show fee", request)

    record_many(AuditLog.Action.BOOKING_NO_SHOW, done, request=request,
                changes=lambda b: {'penalty': str(b.penalty_amount), 'waived': b.penalty_waived})
    return done, skipped


def expire_holds(now=None):
    """Cancel PENDING bookings whose payment hold has lapsed. Returns how many were expired."""
    now = now or timezone.now()
    with transaction.atomic():
        # Selected under the lock, so a hold confirmed by a payment meanwhile is left alone
        expired = list(Booking.objects.select_for_update().filter(status=Status.PENDING, hold_expires_at__lte=now)
                       .order_by('pk'))
        for booking in expired:
            booking.status = Status.CANCELLED
            booking.cancelled_at = now
            booking.cancellation_reason = HOLD_EXPIRED_REASON
        _saved(expired, ['status', 'cancelled_at', 'cancellation_reason'])
    record_many(AuditLog.Action.BOOKING_HOLD_EXPIRED, expired)
    return len(expired)


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
