from collections import Counter
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from booking.models import Booking
from rooms.models import Room, RoomAvailabilityOverride, RoomType

# Upper bound on rooms in a suggested multi-room plan, and on plans explored,
# so large parties can't make the search blow up combinatorially.
MAX_ROOMS_PER_PLAN = 10
MAX_PLANS_EXPLORED = 5000

def get_available_rooms_for_type(room_type, check_in_date, check_out_date, exclude_booking=None):
    """
    Rooms of `room_type` free for the whole stay. `exclude_booking` ignores
    that booking's own hold, for re-checking availability when modifying it.
    """
    conflicting_bookings = Booking.objects.blocking().overlapping(check_in_date, check_out_date)
    if exclude_booking is not None:
        conflicting_bookings = conflicting_bookings.exclude(pk=exclude_booking.pk)

    return Room.objects.filter(
        room_type=room_type,
    ).exclude(
        status__in=Room.UNSELLABLE_STATUSES
    ).exclude(
        id__in=conflicting_bookings.values("room_id")
    ).exclude(
        id__in=RoomAvailabilityOverride.objects.filter(
            start_date__lt=check_out_date,
            end_date__gt=check_in_date
        ).values("room_id")
    )


def nightly_rates(room_type, check_in_date, check_out_date):
    """[(date, rate)] for each night of the stay (check-out night excluded)."""
    # One query for all seasonal rates overlapping the stay instead of one per night
    pricings = list(room_type.pricings.filter(
        start_date__lt=check_out_date,
        end_date__gte=check_in_date
    ))

    rates = []
    current_date = check_in_date
    while current_date < check_out_date:
        pricing = next(
            (p for p in pricings if p.start_date <= current_date <= p.end_date),
            None
        )
        rates.append((current_date, pricing.price_per_night if pricing else room_type.base_price))
        current_date += timedelta(days=1)
    return rates


def calculate_total_price(room_type, check_in_date, check_out_date) -> Decimal:
    return sum((rate for _, rate in nightly_rates(room_type, check_in_date, check_out_date)), Decimal("0.00"))


def calculate_average_price_per_night(room_type, check_in_date, check_out_date) -> Decimal:
    nights = (check_out_date - check_in_date).days
    total = calculate_total_price(room_type, check_in_date, check_out_date)
    return (total / nights).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def generate_booking_plans(check_in_date, check_out_date, adults, children):
    """
    Generate multiple room booking combinations when no single room fits everyone.
    Returns plans sorted by cheapest price and fewest rooms.
    """
    nights = (check_out_date - check_in_date).days

    # 1. Available room count and stay price per room type, computed once
    inventory = []
    for room_type in RoomType.objects.all():
        available_count = get_available_rooms_for_type(room_type, check_in_date, check_out_date).count()
        if available_count:
            inventory.append((
                room_type,
                available_count,
                calculate_total_price(room_type, check_in_date, check_out_date),
            ))

    # 2. Generate combinations within availability
    valid_plans = []
    for plan in _find_room_combinations(adults, children, inventory):
        room_counts = Counter(room_type for room_type, _ in plan)
        total_price = sum((price for _, price in plan), Decimal('0.00'))
        valid_plans.append({
            'rooms': room_counts,  # {RoomType: count}
            'total_rooms': len(plan),
            'total_price': total_price,
            'price_per_night': (total_price / nights).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        })

    # 3. Sort plans
    by_price = sorted(valid_plans, key=lambda x: (x['total_price'], x['total_rooms']))
    by_rooms = sorted(valid_plans, key=lambda x: (x['total_rooms'], x['total_price']))

    return {
        'budget_friendly': by_price[:5],  # Top 5 cheapest
        'convenience': by_rooms[:5]  # Top 5 fewest rooms
    }


def _find_room_combinations(adults, children, inventory):
    """
    Find minimal room combinations that fit the party, without exceeding the
    available count of any room type. Each combination is a list of
    (room_type, stay_price) tuples.

    Room types are only added in non-decreasing index order, so each multiset
    of rooms is produced once rather than once per ordering.
    """
    plans = []

    def covers(rooms):
        return (
            sum(rt.max_adults for rt, _ in rooms) >= adults
            and sum(rt.max_children for rt, _ in rooms) >= children
        )

    def search(start, current, used):
        if len(plans) >= MAX_PLANS_EXPLORED:
            return
        if covers(current):
            # Skip plans where some room could be dropped and still fit everyone
            if not any(covers(current[:i] + current[i + 1:]) for i in range(len(current))):
                plans.append(list(current))
            return
        if len(current) >= MAX_ROOMS_PER_PLAN:
            return
        for index in range(start, len(inventory)):
            room_type, available_count, price = inventory[index]
            if used[index] >= available_count:
                continue
            used[index] += 1
            current.append((room_type, price))
            search(index, current, used)
            current.pop()
            used[index] -= 1

    search(0, [], [0] * len(inventory))
    return plans
