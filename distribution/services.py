"""
Two-way sync with the channel manager.

Outbound (ARI): availability per room type and price/restrictions per mapped
rate plan, for each day of the sync window, compressed into date ranges.

Inbound: booking revisions (new / modified / cancelled) become PMS bookings.
OTAs have already confirmed these to the guest, so a booking that can't be
placed (no room, unknown mapping) is kept and flagged for staff instead of
being rejected.
"""
import logging
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.tasks import task
from django.utils import timezone

from audit.models import AuditLog
from audit.services import record
from billing.models import ExchangeRate
from booking import lifecycle
from booking.allocation import allocate_room, lock_room_types
from booking.exceptions import BookingError
from booking.models import Booking, BookingNight, Guest
from booking.pricing import summarize
from booking.services import generate_confirmation_number
from hotel.clock import business_date
from hotel.errors import DomainError
from hotel.money import money
from rates.engine import RatePlanUnavailable, plan_nightly_rates
from rates.models import RateRestriction
from rooms.models import Room, RoomAvailabilityOverride

from .channex import ChannexClient
from .models import ChannelBooking, ChannelConnection

logger = logging.getLogger(__name__)


def active_connection():
    return ChannelConnection.objects.filter(is_active=True).first()


# --- Outbound ---------------------------------------------------------------

def _days(start, end):
    return [start + timedelta(days=i) for i in range((end - start).days)]


def availability_by_day(room_type, start, end):
    """{date: sellable rooms} for [start, end), in a constant number of queries."""
    rooms = set(Room.objects.filter(room_type=room_type).exclude(status__in=Room.UNSELLABLE_STATUSES)
                .values_list('pk', flat=True))
    taken = defaultdict(set)
    for room_id, check_in, check_out in (Booking.objects.blocking().overlapping(start, end)
                                         .filter(room__in=rooms).values_list('room_id', 'check_in_date', 'check_out_date')):
        for day in _days(max(check_in, start), min(check_out, end)):
            taken[day].add(room_id)
    for room_id, block_start, block_end in (RoomAvailabilityOverride.objects
                                            .filter(room__in=rooms, start_date__lt=end, end_date__gt=start)
                                            .values_list('room_id', 'start_date', 'end_date')):
        for day in _days(max(block_start, start), min(block_end, end)):
            taken[day].add(room_id)
    return {day: len(rooms - taken[day]) for day in _days(start, end)}


def compress(per_day, **fields):
    """Turn {date: value-dict} into ranges of consecutive days with identical values."""
    ranges, current = [], None
    for day in sorted(per_day):
        value = per_day[day]
        if current and current['value'] == value and current['date_to'] == day - timedelta(days=1):
            current['date_to'] = day
        else:
            current = {'date_from': day, 'date_to': day, 'value': value}
            ranges.append(current)
    return [{**fields, 'date_from': str(r['date_from']), 'date_to': str(r['date_to']), **r['value']} for r in ranges]


def _restrictions_by_day(plan, room_type, start, end):
    rules = list(RateRestriction.objects.filter(
        Q(rate_plan__isnull=True) | Q(rate_plan=plan), Q(room_type__isnull=True) | Q(room_type=room_type),
        start_date__lt=end, end_date__gte=start,
    ))
    by_day = {}
    for day in _days(start, end):
        active = [r for r in rules if r.start_date <= day <= r.end_date]
        by_day[day] = {
            'stop_sell': any(r.stop_sell for r in active) or not plan.is_active,
            'closed_to_arrival': any(r.closed_to_arrival for r in active),
            'closed_to_departure': any(r.closed_to_departure for r in active),
            'min_stay_arrival': max([plan.min_stay] + [r.min_stay or 0 for r in active]),
        }
    return by_day


def build_ari(connection, start, end):
    availability, restrictions = [], []
    for mapping in connection.room_types.select_related('room_type'):
        per_day = {d: {'availability': n} for d, n in availability_by_day(mapping.room_type, start, end).items()}
        availability += compress(per_day, room_type_id=mapping.external_id)
    for mapping in connection.rate_plans.select_related('room_type', 'rate_plan'):
        try:
            prices = dict(plan_nightly_rates(mapping.rate_plan, mapping.room_type, start, end))
        except RatePlanUnavailable:
            prices = {}
        rules = _restrictions_by_day(mapping.rate_plan, mapping.room_type, start, end)
        per_day = {}
        for day in _days(start, end):
            price = prices.get(day)
            per_day[day] = {**rules[day], 'rate': str(price) if price is not None else None,
                            'stop_sell': rules[day]['stop_sell'] or price is None}
        restrictions += compress(per_day, rate_plan_id=mapping.external_id)
    return availability, restrictions


@task
def push_ari(date_from=None, date_to=None):
    """Publish availability, rates and restrictions. Defaults to the whole sync window."""
    connection = active_connection()
    if connection is None:
        return 'no active channel connection'
    start = date.fromisoformat(date_from) if date_from else business_date()
    end = date.fromisoformat(date_to) if date_to else start + timedelta(days=connection.sync_days)
    availability, restrictions = build_ari(connection, start, end)
    client = ChannexClient(connection)
    try:
        if availability:
            client.update_availability(availability)
        if restrictions:
            client.update_restrictions(restrictions)
    except DomainError as e:
        ChannelConnection.objects.filter(pk=connection.pk).update(last_error=e.message[:500])
        raise
    update = {'last_error': ''}
    if not date_from:
        update['last_full_sync_at'] = timezone.now()
    ChannelConnection.objects.filter(pk=connection.pk).update(**update)
    return {'availability_ranges': len(availability), 'restriction_ranges': len(restrictions)}


def schedule_push(booking):
    """After a booking changes, republish availability for its dates (once the change commits)."""
    if active_connection() is None:
        return
    start, end = str(booking.check_in_date), str(booking.check_out_date)
    transaction.on_commit(lambda: push_ari.enqueue(date_from=start, date_to=end))


# --- Inbound ----------------------------------------------------------------

def _to_hotel_currency(amount, currency):
    amount = Decimal(str(amount))
    if not currency or currency == settings.HOTEL_CURRENCY:
        return money(amount)
    rate = ExchangeRate.objects.filter(currency=currency).first()
    if rate is None:
        raise DomainError(f"No exchange rate for {currency}")
    return money(amount * rate.rate)


def _create_bookings(connection, attributes):
    """Place every room of an OTA reservation, all or nothing."""
    customer = attributes.get('customer') or {}
    check_in = date.fromisoformat(attributes['arrival_date'])
    check_out = date.fromisoformat(attributes['departure_date'])
    currency = attributes.get('currency', settings.HOTEL_CURRENCY)
    room_maps = {m.external_id: m.room_type for m in connection.room_types.select_related('room_type')}
    plan_maps = {m.external_id: m.rate_plan for m in connection.rate_plans.select_related('rate_plan')}

    rooms = attributes.get('rooms') or []
    if not rooms:
        raise DomainError("Reservation has no rooms")
    for item in rooms:
        if item.get('room_type_id') not in room_maps:
            raise DomainError(f"Unmapped room type {item.get('room_type_id')}")

    with transaction.atomic():
        lock_room_types({room_maps[i['room_type_id']] for i in rooms})
        guest = Guest.objects.create(
            first_name=(customer.get('name') or 'OTA')[:100], last_name=(customer.get('surname') or 'Guest')[:100],
            email=(customer.get('mail') or f"ota-{attributes.get('booking_id')}@invalid.example")[:254],
            phone_number=(customer.get('phone') or '')[:15], country=(customer.get('country') or '')[:40],
        )
        created, taken = [], []
        for item in rooms:
            room_type = room_maps[item['room_type_id']]
            room = allocate_room(room_type, check_in, check_out, taken=taken)
            taken.append(room.pk)
            days = item.get('days') or {}
            rates = [(d, _to_hotel_currency(days.get(str(d), 0), currency)) for d in _days(check_in, check_out)]
            total, average = summarize(rates)
            occupancy = item.get('occupancy') or {}
            booking = Booking.objects.create(
                guest=guest, room=room, check_in_date=check_in, check_out_date=check_out,
                number_of_adults=max(1, int(occupancy.get('adults') or 1)),
                number_of_children=int(occupancy.get('children') or 0),
                special_requests=(attributes.get('notes') or '')[:2000],
                price_per_night=average, total_price=total,
                status=Booking.Status.CONFIRMED, confirmed_at=timezone.now(), source=Booking.Source.OTA,
                rate_plan=plan_maps.get(item.get('rate_plan_id')),
                confirmation_number=generate_confirmation_number(),
            )
            BookingNight.objects.bulk_create(BookingNight(booking=booking, date=d, rate=r) for d, r in rates)
            created.append(booking)
    return created


def _cancel_linked(channel_booking, reason):
    for booking in channel_booking.bookings.filter(status__in=[Booking.Status.PENDING, Booking.Status.CONFIRMED]):
        # The OTA applies its own cancellation terms to the guest
        lifecycle.cancel(booking, reason=reason, waive_penalty=True)
    return not channel_booking.bookings.filter(status=Booking.Status.CHECKED_IN).exists()


def import_revision(connection, revision):
    """Apply one booking revision. Idempotent per revision id."""
    revision_id = str(revision['id'])
    attributes = revision.get('attributes') or {}
    external_id = str(attributes.get('booking_id') or revision_id)
    status = attributes.get('status', 'new')
    ota = attributes.get('ota_name', '')

    channel_booking, _ = ChannelBooking.objects.get_or_create(
        connection=connection, external_id=external_id,
        defaults={'last_revision_id': '', 'status': ChannelBooking.Status.IMPORTED, 'ota_name': ota},
    )
    if channel_booking.last_revision_id == revision_id:
        return channel_booking
    channel_booking.ota_name = ota
    channel_booking.ota_reference = str(attributes.get('ota_reservation_code') or '')[:100]
    channel_booking.payload = revision
    channel_booking.last_revision_id = revision_id
    channel_booking.problem = ''

    try:
        if status == 'cancelled':
            clean = _cancel_linked(channel_booking, f"Cancelled via {ota or 'channel'}")
            channel_booking.status = ChannelBooking.Status.CANCELLED if clean else ChannelBooking.Status.NEEDS_ATTENTION
            if not clean:
                channel_booking.problem = "Cancelled by the OTA while the guest is checked in."
        else:
            if status == 'modified' and channel_booking.bookings.exists():
                # Re-place the reservation as modified (rooms may change); in-house stays need a person
                if not _cancel_linked(channel_booking, f"Modified via {ota or 'channel'}"):
                    raise DomainError("Modified by the OTA while the guest is checked in")
                channel_booking.bookings.clear()
            channel_booking.save()
            bookings = _create_bookings(connection, attributes)
            channel_booking.bookings.add(*bookings)
            channel_booking.status = ChannelBooking.Status.IMPORTED
    except (DomainError, BookingError, KeyError, ValueError) as e:
        message = getattr(e, 'message', str(e))
        channel_booking.status = ChannelBooking.Status.NEEDS_ATTENTION
        channel_booking.problem = f"Could not place automatically: {message}"[:500]
        logger.warning("Channel booking %s needs attention: %s", external_id, message)
    channel_booking.save()
    record(AuditLog.Action.CHANNEL_BOOKING_RECEIVED, target=channel_booking,
           changes={'revision': revision_id, 'status': status, 'result': channel_booking.status,
                    'problem': channel_booking.problem or None})
    return channel_booking


@task
def pull_bookings():
    """Fetch unacknowledged revisions, apply them, acknowledge them."""
    connection = active_connection()
    if connection is None:
        return 'no active channel connection'
    client = ChannexClient(connection)
    processed = 0
    for revision in client.booking_revisions():
        import_revision(connection, revision)
        client.acknowledge(revision['id'])
        processed += 1
    return processed
