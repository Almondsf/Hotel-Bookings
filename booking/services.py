import secrets
import string
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from audit.models import AuditLog
from audit.services import record_many
from booking.allocation import allocate_room, allocate_rooms, lock_room_types
from booking.exceptions import BookingError
from booking.models import Booking, BookingGroup, BookingNight, Guest
from booking.signals import bookings_saved
from booking.validation import validate_stay
from hotel.clock import business_date
from hotel.errors import DomainError
from notifications.services import notify, notify_many
from billing import services as billing
from billing.models import ChargeCategory
from billing.taxes import active_rules, quote
from booking.pricing import create_nights, summarize
from rates.engine import STAFF, WEBSITE, RatePlanUnavailable, StayContext, require_plan
from rooms.services import nightly_rates

CODE_CHARS = string.ascii_uppercase + string.digits


def _generate_codes(prefix, model, field, count):
    """`count` unique codes like BK-ABC123, checked against the table in one query (retried on a clash)."""
    codes = set()
    while len(codes) < count:
        candidates = {f'{prefix}-' + ''.join(secrets.choice(CODE_CHARS) for _ in range(6))
                      for _ in range(count - len(codes))} - codes
        taken = set(model.objects.filter(**{f'{field}__in': candidates}).values_list(field, flat=True))
        codes |= candidates - taken
    return list(codes)


def generate_confirmation_numbers(count):
    return _generate_codes('BK', Booking, 'confirmation_number', count)


def generate_confirmation_number():
    """Generate a short, unique confirmation number like BK-ABC123"""
    return generate_confirmation_numbers(1)[0]


def generate_group_reference():
    return _generate_codes('GR', BookingGroup, 'reference', 1)[0]


def _insert_bookings(rooms, *, check_in_date, check_out_date, rate_plan=None, channel, promo_code=None,
                     account=None, override=None, **fields):
    """
    Allocate, price, validate and insert one booking per item of `rooms`
    ({room_type, room (optional), number_of_adults, number_of_children}) with
    their nights, in a fixed number of queries whatever the number of rooms.
    `fields` are set on every booking. Must run inside transaction.atomic()
    after lock_room_types().
    """
    allocated = allocate_rooms([(item['room_type'], item.get('room')) for item in rooms],
                               check_in_date, check_out_date)
    stay = StayContext(check_in_date, check_out_date)
    numbers = generate_confirmation_numbers(len(rooms))
    rates_by_type, bookings, stays = {}, [], []
    for item, room, number in zip(rooms, allocated, numbers):
        room_type = item['room_type']
        if room_type.pk not in rates_by_type:
            rates_by_type[room_type.pk] = _priced(rate_plan, room_type, check_in_date, check_out_date, channel=channel,
                                                  promo_code=promo_code, account=account, override=override, ctx=stay)
        rates = rates_by_type[room_type.pk]
        total_price, average_rate = summarize(rates)
        booking = Booking(
            room=room, check_in_date=check_in_date, check_out_date=check_out_date,
            number_of_adults=item['number_of_adults'], number_of_children=item.get('number_of_children', 0),
            price_per_night=average_rate, total_price=total_price, rate_plan=rate_plan,
            confirmation_number=number, **fields,
        )
        booking.validate()
        bookings.append(booking)
        stays.append(rates)
    Booking.objects.bulk_create(bookings)
    BookingNight.objects.bulk_create(
        BookingNight(booking=booking, date=day, rate=rate) for booking, rates in zip(bookings, stays) for day, rate in rates)
    bookings_saved.send(sender=Booking, bookings=bookings)
    return bookings


def send_booking_confirmation(booking):
    """Email / SMS the guest their confirmation once the transaction commits."""
    notify('booking_confirmed', booking)


def send_confirmations(bookings):
    """Confirm bookings made together: one message per room, or a single one listing a group's rooms."""
    grouped = [b for b in bookings if b.group_id]
    notify_many('booking_confirmed', [b for b in bookings if not b.group_id])
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
        bookings = _insert_bookings(
            rooms, check_in_date=check_in_date, check_out_date=check_out_date, channel=WEBSITE,
            guest=guest, group=group, special_requests=validated_data.get('special_requests', ''),
            status=Booking.Status.PENDING, source=Booking.Source.WEBSITE, hold_expires_at=hold_until,
        )
        folios = billing.open_folios(bookings)
        rules = active_rules()
        amount_due = sum((amount_due_online(booking, rules) for booking in bookings), Decimal('0.00'))

    lead = bookings[0]
    try:
        txn = start_payment(
            gateway=validated_data['gateway'], folio=folios[0], amount=amount_due, email=guest.email,
            purpose=PaymentTransaction.Purpose.BOOKING_PREPAYMENT, booking=lead, customer_name=str(guest),
            description=f"Group {group.reference} ({len(bookings)} rooms)",
        )
    except DomainError:
        Booking.objects.filter(group=group).update(
            status=Booking.Status.CANCELLED, cancelled_at=timezone.now(), cancellation_reason="Payment could not be started",
        )
        raise
    return group, bookings, txn


def amount_due_online(booking, rules=None):
    """What the guest pays up front for one booking: the stay including taxes. `rules`: tax rules already loaded."""
    return quote(ChargeCategory.ROOM, booking.total_price, rules)['gross']


def _priced(rate_plan, room_type, check_in_date, check_out_date, *, channel, promo_code=None, account=None,
            override=None, ctx=None):
    """Nightly rates for a new booking, enforcing the rate plan's conditions. `ctx`: a StayContext for the dates."""
    seasonal = ctx.seasonal[room_type.pk] if ctx is not None else None
    if override is not None:
        return [(date, override) for date, _ in nightly_rates(room_type, check_in_date, check_out_date, seasonal)]
    try:
        return require_plan(rate_plan, room_type, check_in_date, check_out_date, channel=channel,
                            promo_code=promo_code, account=account, ctx=ctx) if rate_plan else \
            nightly_rates(room_type, check_in_date, check_out_date, seasonal)
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
    today = business_date()
    for item in rooms:
        validate_stay(item['room_type'], check_in_date, check_out_date,
                      item['number_of_adults'], item['number_of_children'], today=today)

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

        bookings = _insert_bookings(
            rooms, check_in_date=check_in_date, check_out_date=check_out_date, rate_plan=rate_plan, channel=STAFF,
            account=corporate_account, override=rate_override,
            guest=guest, group=group, special_requests=special_requests, status=Booking.Status.CONFIRMED,
            confirmed_at=now, source=source, created_by=actor, corporate_account=corporate_account,
            nightly_rate_override=rate_override, rate_override_reason=override_reason,
        )

    record_many(AuditLog.Action.BOOKING_CREATED, bookings, request=request,
                changes={'source': source, 'group': group.reference if group else None,
                         'rate_plan': rate_plan.code if rate_plan else 'BAR',
                         'rate_override': str(rate_override) if rate_override is not None else None,
                         'override_reason': override_reason or None})
    send_confirmations(bookings)
    return bookings
