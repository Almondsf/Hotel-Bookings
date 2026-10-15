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


def rank_for_party(room_types, adults, children, check_in_date, check_out_date):
    """
    Order room types for a search: the closest fit for the party first (fewest
    spare places, so two adults see a double before a family suite), then the
    lowest price for the stay. Every room type passed in must already fit.
    """
    def key(room_type):
        spare = (room_type.max_adults - adults) + (room_type.max_children - children)
        return spare, calculate_total_price(room_type, check_in_date, check_out_date), room_type.name

    return sorted(room_types, key=key)


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


def split_party(room_types, adults, children):
    """
    Suggest who sleeps where: every room gets one adult first (children can't
    have a room alone), then the remaining adults and children fill the
    largest rooms first. Returns [(room_type, adults, children)] or None if the
    party can't be split that way.
    """
    if adults < len(room_types):
        return None
    order = sorted(range(len(room_types)), key=lambda i: (room_types[i].max_adults, room_types[i].max_children), reverse=True)
    placed_adults = [1] * len(room_types)
    placed_children = [0] * len(room_types)
    left_adults, left_children = adults - len(room_types), children
    for i in order:
        extra = min(left_adults, room_types[i].max_adults - 1)
        placed_adults[i] += extra
        left_adults -= extra
        kids = min(left_children, room_types[i].max_children)
        placed_children[i] += kids
        left_children -= kids
    if left_adults or left_children:
        return None
    return [(room_types[i], placed_adults[i], placed_children[i]) for i in range(len(room_types))]


def suggest_group_plans(check_in_date, check_out_date, adults, children, limit=3):
    """
    Ready-made multi-room plans for a party too big for one room, booked
    together as a group: the cheapest ("Best value"), the fewest rooms, and the
    roomiest for a modest premium ("Most space"), without duplicates. Prices
    are the best available rate for the stay, with and without taxes.
    """
    from billing.models import ChargeCategory
    from billing.taxes import quote

    nights = (check_out_date - check_in_date).days
    inventory = []
    for room_type in RoomType.objects.all():
        available = get_available_rooms_for_type(room_type, check_in_date, check_out_date).count()
        if available:
            inventory.append((room_type, available, calculate_total_price(room_type, check_in_date, check_out_date)))

    candidates = []
    for combination in _find_room_combinations(adults, children, inventory):
        rooms = split_party([room_type for room_type, _ in combination], adults, children)
        if rooms is None:
            continue
        total = sum((price for _, price in combination), Decimal('0.00'))
        spare = sum(rt.max_adults + rt.max_children for rt, _ in combination) - adults - children
        candidates.append({'rooms': rooms, 'total': total, 'spare': spare})
    if not candidates:
        return []

    cheapest = min(candidates, key=lambda p: (p['total'], len(p['rooms'])))
    fewest = min(candidates, key=lambda p: (len(p['rooms']), p['total']))
    # Most space: more room to spread out, but not more than half again the cheapest price
    affordable = [p for p in candidates if p['total'] <= cheapest['total'] * Decimal('1.5')]
    roomiest = max(affordable, key=lambda p: (p['spare'], -p['total']))

    def signature(plan):
        return tuple(sorted((rt.pk, a, c) for rt, a, c in plan['rooms']))

    plans, seen = [], set()
    for label, plan in [('Best value', cheapest), ('Fewest rooms', fewest), ('Most space', roomiest)]:
        if signature(plan) in seen:
            continue
        seen.add(signature(plan))
        price = quote(ChargeCategory.ROOM, plan['total'])
        plans.append({
            'label': label,
            'rooms': [{'room_type': rt, 'number_of_adults': a, 'number_of_children': c} for rt, a, c in plan['rooms']],
            'total_price': plan['total'],
            'taxes': price['taxes'],
            'total_with_taxes': price['gross'],
            'price_per_night': (plan['total'] / nights).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP),
        })
    return plans[:limit]
