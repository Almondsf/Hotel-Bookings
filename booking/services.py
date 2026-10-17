import secrets
import string
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from audit.models import AuditLog
from audit.services import record
from booking.allocation import allocate_room, lock_room_types
from booking.exceptions import BookingError
from booking.models import Booking, BookingGroup, Guest
from booking.validation import validate_stay
from hotel.errors import DomainError
from notifications.services import notify
from billing import services as billing
from billing.models import ChargeCategory
from billing.taxes import quote
from booking.pricing import create_nights, summarize
from rates.engine import STAFF, WEBSITE, RatePlanUnavailable, require_plan
from rooms.services import nightly_rates

CODE_CHARS = string.ascii_uppercase + string.digits


def _generate_code(prefix, model, field):
    while True:
        code = f'{prefix}-' + ''.join(secrets.choice(CODE_CHARS) for _ in range(6))
        if not model.objects.filter(**{field: code}).exists():
            return code


def generate_confirmation_number():
    """Generate a short, unique confirmation number like BK-ABC123"""
    return _generate_code('BK', Booking, 'confirmation_number')


def generate_group_reference():
    return _generate_code('GR', BookingGroup, 'reference')


def send_booking_confirmation(booking):
    """Email / SMS the guest their confirmation once the transaction commits."""
    notify('booking_confirmed', booking)


def send_confirmations(bookings):
    """Confirm bookings made together: one message per room, or a single one listing a group's rooms."""
    grouped = [b for b in bookings if b.group_id]
    for booking in bookings:
        if not booking.group_id:
            send_booking_confirmation(booking)
    if grouped:
        notify('group_confirmed', grouped[0])


def create_online_booking(validated_data):
    """
    Online booking: hold a room and start a gateway checkout. The booking is
    confirmed when the payment is verified (payments.services.confirm_payment).
    Returns (booking, payment_transaction).
    """
    from payments.models import PaymentTransaction
    from payments.services import start_payment

    guest_data = validated_data['guest']
    room_type = validated_data['room_type']
    check_in_date = validated_data['check_in_date']
    check_out_date = validated_data['check_out_date']
    rate_plan = validated_data.get('rate_plan')

    rates = _priced(rate_plan, room_type, check_in_date, check_out_date, channel=WEBSITE,
                    promo_code=validated_data.get('promo_code'))
    total_price, average_rate = summarize(rates)
    # The guest pays the full price including taxes up front
    amount_due = quote(ChargeCategory.ROOM, total_price)['gross']

    with transaction.atomic():
        lock_room_types([room_type])
        room = allocate_room(room_type, check_in_date, check_out_date)
        guest = Guest.objects.create(**guest_data)
        booking = Booking.objects.create(
            guest=guest,
            room=room,
            check_in_date=check_in_date,
            check_out_date=check_out_date,
            number_of_adults=validated_data['number_of_adults'],
            number_of_children=validated_data.get('number_of_children', 0),
            special_requests=validated_data.get('special_requests', ''),
            price_per_night=average_rate,
            total_price=total_price,
            status=Booking.Status.PENDING,
            source=Booking.Source.WEBSITE,
            rate_plan=rate_plan,
            hold_expires_at=timezone.now() + timedelta(minutes=settings.BOOKING_HOLD_MINUTES),
            confirmation_number=generate_confirmation_number(),
        )
        create_nights(booking, rates)
        folio = billing.folio_for(booking)

    # Talk to the gateway outside the transaction: no locks held over the network.
    try:
        txn = start_payment(
            gateway=validated_data['gateway'], folio=folio, amount=amount_due, email=guest.email,
            purpose=PaymentTransaction.Purpose.BOOKING_PREPAYMENT, booking=booking,
            customer_name=str(guest), description=f"Booking {booking.confirmation_number}",
        )
    except DomainError:
        # Release the hold straight away rather than blocking the room for the hold period
        Booking.objects.filter(pk=booking.pk).update(
            status=Booking.Status.CANCELLED, cancelled_at=timezone.now(), cancellation_reason="Payment could not be started",
        )
        raise
    return booking, txn


def create_online_group_booking(validated_data):
    """
    Several rooms booked online together (a group plan): every room is held
    under one BookingGroup and paid in a single checkout at the best
    available rate. The lead booking (the first room) carries the payment;
    on success the payment is split across each room's folio and all rooms
    are confirmed together (payments.services). Returns (group, bookings, txn).
    """
    from payments.models import PaymentTransaction
    from payments.services import start_payment

    check_in_date = validated_data['check_in_date']
    check_out_date = validated_data['check_out_date']
    rooms = validated_data['rooms']
    hold_until = timezone.now() + timedelta(minutes=settings.BOOKING_HOLD_MINUTES)

    with transaction.atomic():
        lock_room_types(room['room_type'] for room in rooms)
        guest = Guest.objects.create(**validated_data['guest'])
        group = BookingGroup.objects.create(reference=generate_group_reference(), booker=guest,
                                            notes="Booked online as a group plan")
        bookings, taken, amount_due = [], [], Decimal('0.00')
        for room in rooms:
            allocated = allocate_room(room['room_type'], check_in_date, check_out_date, taken=taken)
            taken.append(allocated.pk)
            rates = _priced(None, room['room_type'], check_in_date, check_out_date, channel=WEBSITE)
            total_price, average_rate = summarize(rates)
            booking = Booking.objects.create(
                guest=guest, room=allocated, group=group,
                check_in_date=check_in_date, check_out_date=check_out_date,
                number_of_adults=room['number_of_adults'], number_of_children=room['number_of_children'],
                special_requests=validated_data.get('special_requests', ''),
                price_per_night=average_rate, total_price=total_price,
                status=Booking.Status.PENDING, source=Booking.Source.WEBSITE, hold_expires_at=hold_until,
                confirmation_number=generate_confirmation_number(),
            )
            create_nights(booking, rates)
            billing.folio_for(booking)
            amount_due += quote(ChargeCategory.ROOM, total_price)['gross']
            bookings.append(booking)

    lead = bookings[0]
    try:
        txn = start_payment(
            gateway=validated_data['gateway'], folio=billing.folio_for(lead), amount=amount_due, email=guest.email,
            purpose=PaymentTransaction.Purpose.BOOKING_PREPAYMENT, booking=lead, customer_name=str(guest),
            description=f"Group {group.reference} ({len(bookings)} rooms)",
        )
    except DomainError:
        Booking.objects.filter(group=group).update(
            status=Booking.Status.CANCELLED, cancelled_at=timezone.now(), cancellation_reason="Payment could not be started",
        )
        raise
    return group, bookings, txn


def amount_due_online(booking):
    """What the guest pays up front for one booking: the stay including taxes."""
    return quote(ChargeCategory.ROOM, booking.total_price)['gross']


def _priced(rate_plan, room_type, check_in_date, check_out_date, *, channel, promo_code=None, account=None,
            override=None):
    """Nightly rates for a new booking, enforcing the rate plan's conditions."""
    if override is not None:
        return [(date, override) for date, _ in nightly_rates(room_type, check_in_date, check_out_date)]
    try:
        return require_plan(rate_plan, room_type, check_in_date, check_out_date, channel=channel,
                            promo_code=promo_code, account=account) if rate_plan else \
            nightly_rates(room_type, check_in_date, check_out_date)
    except RatePlanUnavailable as e:
        raise BookingError(f"{rate_plan.name} isn't available: {'; '.join(e.reasons)}.", field='rate_plan')


def create_staff_reservation(*, guest, rooms, check_in_date, check_out_date, special_requests='',
                             source=Booking.Source.FRONT_DESK, notes='', request=None, rate_plan=None,
                             corporate_account=None, rate_override=None, override_reason=''):
    """
    Reservation taken by staff (phone, walk-in, corporate...). Confirmed
    immediately; payment is settled through the guest's folio.

    `rooms` is a list of dicts: {room_type, room (optional), number_of_adults, number_of_children}.
    More than one room creates a BookingGroup. `rate_override` (a nightly
    rate) needs `override_reason`; permission is checked by the caller.
    """
    if not rooms:
        raise BookingError("At least one room is required.", field='rooms')
    if rate_override is not None and not override_reason:
        raise BookingError("A reason is required to override the rate.", field='override_reason')

    actor = request.user if request is not None else None
    for item in rooms:
        validate_stay(item['room_type'], check_in_date, check_out_date,
                      item['number_of_adults'], item['number_of_children'])

    now = timezone.now()
    with transaction.atomic():
        lock_room_types(item['room_type'] for item in rooms)

        if isinstance(guest, dict):
            guest = Guest.objects.create(**guest)

        group = None
        if len(rooms) > 1:
            group = BookingGroup.objects.create(
                reference=generate_group_reference(), booker=guest, notes=notes, created_by=actor,
            )

        bookings, taken = [], []
        for item in rooms:
            room_type = item['room_type']
            room = allocate_room(room_type, check_in_date, check_out_date,
                                 preferred_room=item.get('room'), taken=taken)
            taken.append(room.pk)
            rates = _priced(rate_plan, room_type, check_in_date, check_out_date, channel=STAFF,
                            account=corporate_account, override=rate_override)
            total_price, average_rate = summarize(rates)
            booking = Booking.objects.create(
                guest=guest,
                room=room,
                group=group,
                check_in_date=check_in_date,
                check_out_date=check_out_date,
                number_of_adults=item['number_of_adults'],
                number_of_children=item['number_of_children'],
                special_requests=special_requests,
                price_per_night=average_rate,
                total_price=total_price,
                status=Booking.Status.CONFIRMED,
                confirmed_at=now,
                source=source,
                created_by=actor,
                rate_plan=rate_plan,
                corporate_account=corporate_account,
                nightly_rate_override=rate_override,
                rate_override_reason=override_reason,
                confirmation_number=generate_confirmation_number(),
            )
            create_nights(booking, rates)
            bookings.append(booking)

    for booking in bookings:
        record(AuditLog.Action.BOOKING_CREATED, request=request, target=booking,
               changes={'source': booking.source, 'group': group.reference if group else None,
                        'rate_plan': rate_plan.code if rate_plan else 'BAR',
                        'rate_override': str(rate_override) if rate_override is not None else None,
                        'override_reason': override_reason or None})
    send_confirmations(bookings)
    return bookings
