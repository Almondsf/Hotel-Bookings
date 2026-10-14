"""
Hotel KPIs. Closed days are measured from what was actually posted
(charges, payments); today and future days from what is on the books
(bookings and their agreed nightly rates).

  Occupancy = rooms sold / rooms available
  ADR       = room revenue / rooms sold
  RevPAR    = room revenue / rooms available
"""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum

from billing.models import Charge, ChargeCategory, CorporateAccount, Folio, FolioPayment
from booking.models import Booking, BookingNight
from hotel.clock import business_date
from hotel.money import ZERO, money
from rooms.models import Room, RoomAvailabilityOverride


def _ratio(numerator, denominator):
    return money(Decimal(numerator) / Decimal(denominator)) if denominator else ZERO


def rooms_available(day):
    """Rooms that could be sold on `day`: all rooms minus those out of order."""
    blocked = set(RoomAvailabilityOverride.objects.filter(start_date__lte=day, end_date__gt=day)
                  .values_list('room_id', flat=True))
    if day >= business_date():
        blocked |= set(Room.objects.filter(status=Room.Status.OUT_OF_SERVICE).values_list('pk', flat=True))
    return Room.objects.count() - len(blocked)


def _room_nights(day):
    """(rooms sold, room revenue) for the night of `day`."""
    if day < business_date():
        posted = Charge.objects.filter(category=ChargeCategory.ROOM, service_date=day, is_void=False)
        totals = posted.aggregate(count=Count('id'), revenue=Sum('net_amount'))
        return totals['count'], totals['revenue'] or ZERO
    on_books = BookingNight.objects.filter(
        date=day,
        booking__in=Booking.objects.blocking().overlapping(day, day + timedelta(days=1)),
    )
    totals = on_books.aggregate(count=Count('id'), revenue=Sum('rate'))
    return totals['count'], totals['revenue'] or ZERO


def occupancy_day(day):
    available = rooms_available(day)
    sold, revenue = _room_nights(day)
    return {
        'date': day,
        'actual': day < business_date(),
        'rooms_available': available,
        'rooms_sold': sold,
        'occupancy_percent': float(_ratio(sold * 100, available)),
        'room_revenue': revenue,
        'adr': _ratio(revenue, sold),
        'revpar': _ratio(revenue, available),
    }


def occupancy(start, end):
    """One row per day in [start, end]."""
    days = (end - start).days + 1
    return [occupancy_day(start + timedelta(days=i)) for i in range(days)]


def revenue(start, end):
    """Posted revenue by department and the taxes collected, for [start, end]."""
    charges = Charge.objects.filter(service_date__range=(start, end), is_void=False)
    by_category = {row['category']: row for row in charges.values('category').annotate(
        net=Sum('net_amount'), tax=Sum('tax_amount'), gross=Sum('total_amount'))}
    categories = [{
        'category': code, 'name': label,
        'net': by_category.get(code, {}).get('net') or ZERO,
        'tax': by_category.get(code, {}).get('tax') or ZERO,
        'gross': by_category.get(code, {}).get('gross') or ZERO,
    } for code, label in ChargeCategory.choices if code in by_category]

    taxes = defaultdict(lambda: {'name': '', 'amount': ZERO})
    for lines in charges.exclude(tax_lines=[]).values_list('tax_lines', flat=True):
        for line in lines:
            taxes[line['code']]['name'] = line['name']
            taxes[line['code']]['amount'] += money(line['amount'])

    return {
        'from': start, 'to': end,
        'categories': categories,
        'taxes': [{'code': code, **t} for code, t in sorted(taxes.items())],
        'totals': {
            'net': sum((c['net'] for c in categories), ZERO),
            'tax': sum((c['tax'] for c in categories), ZERO),
            'gross': sum((c['gross'] for c in categories), ZERO),
        },
    }


def payments(start, end):
    """Cashier report: money taken by method and by staff member, for [start, end]."""
    rows = FolioPayment.objects.filter(service_date__range=(start, end), is_void=False)
    signed = lambda kind: Sum('amount', filter=Q(kind=kind))  # noqa: E731
    by_method = rows.values('method').annotate(received=signed('PAYMENT'), refunded=signed('REFUND')).order_by('method')
    by_staff = (rows.values('received_by__email').annotate(received=signed('PAYMENT'), refunded=signed('REFUND'))
                .order_by('received_by__email'))

    def net(row):
        received, refunded = row['received'] or ZERO, row['refunded'] or ZERO
        return {'received': received, 'refunded': refunded, 'net': received - refunded}

    methods = [{'method': row['method'], **net(row)} for row in by_method]
    return {
        'from': start, 'to': end,
        'by_method': methods,
        'by_staff': [{'staff': row['received_by__email'] or 'Online', **net(row)} for row in by_staff],
        'total': sum((m['net'] for m in methods), ZERO),
    }


def guest_ledger():
    """Open folios and what is owed on each (in-house guests and non-guest accounts)."""
    folios = Folio.objects.filter(status=Folio.Status.OPEN).select_related('booking__room', 'guest')
    rows = []
    for folio in folios:
        booking = folio.booking
        rows.append({
            'folio_id': folio.pk, 'folio': folio.number, 'name': folio.display_name,
            'room': booking.room.room_number if booking else None,
            'booking_status': booking.status if booking else None,
            'charges': folio.charges_total, 'payments': folio.payments_total, 'balance': folio.balance,
        })
    return {'folios': rows, 'total_balance': sum((r['balance'] for r in rows), ZERO)}


def city_ledger(today=None):
    """What companies owe, aged by how long ago each folio was billed to them."""
    today = today or business_date()
    buckets = [('current', 0, 30), ('31_60', 31, 60), ('61_90', 61, 90), ('over_90', 91, None)]
    accounts = []
    for account in CorporateAccount.objects.prefetch_related('folios', 'payments'):
        aged = {name: ZERO for name, _, _ in buckets}
        for folio in account.folios.filter(status=Folio.Status.TRANSFERRED):
            age = (today - folio.transferred_at.date()).days
            name = next(n for n, low, high in buckets if age >= low and (high is None or age <= high))
            aged[name] += folio.balance
        paid = account.payments.filter(is_void=False).aggregate(total=Sum('amount'))['total'] or ZERO
        # Payments settle the oldest debt first
        for name in reversed([b[0] for b in buckets]):
            applied = min(aged[name], paid)
            aged[name] -= applied
            paid -= applied
        balance = sum(aged.values(), ZERO) - paid
        if balance or account.is_active:
            accounts.append({'account_id': account.pk, 'code': account.code, 'name': account.name,
                             'credit_limit': account.credit_limit, 'balance': balance, **aged})
    return {'as_of': today, 'accounts': accounts, 'total': sum((a['balance'] for a in accounts), ZERO)}


def flash(day):
    """The manager's one-page summary of a day."""
    bookings = Booking.objects.all()
    return {
        'date': day,
        **{k: v for k, v in occupancy_day(day).items() if k != 'date'},
        'arrivals': bookings.filter(check_in_date=day, status__in=[Booking.Status.CHECKED_IN, Booking.Status.CHECKED_OUT]).count(),
        'departures': bookings.filter(check_out_date=day, status=Booking.Status.CHECKED_OUT).count(),
        'no_shows': bookings.filter(check_in_date=day, status=Booking.Status.NO_SHOW).count(),
        'cancellations': bookings.filter(cancelled_at__date=day).count(),
        'in_house': bookings.filter(status=Booking.Status.CHECKED_IN).count() if day == business_date() else None,
        'revenue': revenue(day, day)['totals'],
        'payments': payments(day, day)['total'],
    }
