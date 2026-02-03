from datetime import date, timedelta
from decimal import Decimal
from rooms.models import Room, RoomAvailabilityOverride
from booking.models import Booking
from collections import Counter
from decimal import Decimal

def check_date_overlap(check_in_date_1: date, check_out_date_1: date, check_in_date_2: date, check_out_date_2: date) -> bool:
    return check_in_date_1 < check_out_date_2 and check_out_date_1 > check_in_date_2

def is_room_available(room, search_check_in_date, search_check_out_date) -> bool:
    
    # 1. Room status check
    if room.status != 'AVAILABLE':
        return False

    # 2. Availability overrides (maintenance, blocked, etc.)
    if room.availability_overrides.filter(
        start_date__lt=search_check_out_date,
        end_date__gt=search_check_in_date
    ).exists():
        return False

    # 3. Active bookings
    if room.bookings.filter(
        status__in=['CONFIRMED', 'CHECKED_IN'],
        check_in_date__lt=search_check_out_date,
        check_out_date__gt=search_check_in_date
    ).exists():
        return False

    return True

def get_available_rooms_for_type(room_type, check_in_date, check_out_date):
    return Room.objects.filter(
        room_type=room_type,
        status='AVAILABLE'
    ).exclude(
        id__in=Booking.objects.filter(
            status__in=['CONFIRMED', 'CHECKED_IN'],
            check_in_date__lt=check_out_date,
            check_out_date__gt=check_in_date
        ).values("room_id")
    ).exclude(
        id__in=RoomAvailabilityOverride.objects.filter(
            start_date__lt=check_out_date,
            end_date__gt=check_in_date
        ).values("room_id")
    )
    
    
def calculate_price_per_night(room_type, target_date: date) -> Decimal:
    pricing = room_type.pricings.filter(
        start_date__lte=target_date,
        end_date__gte=target_date
    ).first()

    if pricing:
        return pricing.price_per_night

    return room_type.base_price

def calculate_total_price(room_type, check_in_date, check_out_date) -> Decimal:
    total_price = Decimal("0.00")
    current_date = check_in_date

    number_of_nights = (check_out_date - check_in_date).days

    for _ in range(number_of_nights):
        nightly_price = calculate_price_per_night(room_type, current_date)
        total_price += nightly_price
        current_date += timedelta(days=1)

    return total_price


def generate_booking_plans(check_in_date, check_out_date, adults, children):
    """
    Generate multiple room booking combinations when no single room fits everyone.
    Returns plans sorted by cheapest price and fewest rooms.
    """
    # 1. Get all room types with any availability
    all_room_types = RoomType.objects.all()
    
    available_room_types = []
    for room_type in all_room_types:
        available_rooms = get_available_rooms_for_type(room_type, check_in_date, check_out_date)
        if available_rooms.exists():
            available_room_types.append(room_type)
    
    if not available_room_types:
        return []
    
    # 2. Generate all possible combinations
    all_plans = _find_room_combinations(adults, children, available_room_types)
    
    # 3. Validate and price each plan
    valid_plans = []
    for plan in all_plans:
        # Check if we have enough available rooms for each type in this plan
        room_counts = Counter(plan)
        is_valid = True
        
        for room_type, count_needed in room_counts.items():
            available_count = get_available_rooms_for_type(
                room_type, check_in_date, check_out_date
            ).count()
            
            if available_count < count_needed:
                is_valid = False
                break
        
        if is_valid:
            # Calculate total price
            total_price = Decimal('0.00')
            for room_type in plan:
                total_price += calculate_total_price(room_type, check_in_date, check_out_date)
            
            valid_plans.append({
                'rooms': room_counts,  # {RoomType: count}
                'total_rooms': len(plan),
                'total_price': total_price,
                'price_per_night': total_price / (check_out_date - check_in_date).days
            })
    
    # 4. Sort plans
    by_price = sorted(valid_plans, key=lambda x: x['total_price'])
    by_rooms = sorted(valid_plans, key=lambda x: x['total_rooms'])
    
    return {
        'budget_friendly': by_price[:5],  # Top 5 cheapest
        'convenience': by_rooms[:5]  # Top 5 fewest rooms
    }


def _find_room_combinations(remaining_adults, remaining_children, available_room_types, current_plan=None, depth=0):
    
    """
    Recursive function to find all valid room combinations.
    """
    if current_plan is None:
        current_plan = []
    
    # Limit recursion depth to prevent infinite loops
    if depth > 10:
        return []
    
    # Base case: everyone accommodated
    if remaining_adults <= 0 and remaining_children <= 0:
        return [current_plan]
    
    # Invalid case
    if remaining_adults < 0 or remaining_children < 0:
        return []
    
    all_plans = []
    
    for room_type in available_room_types:
        # Add this room to current plan
        new_plan = current_plan + [room_type]
        
        # Recurse
        plans = _find_room_combinations(
            remaining_adults - room_type.max_adults,
            remaining_children - room_type.max_children,
            available_room_types,
            new_plan,
            depth + 1
        )
        
        all_plans.extend(plans)
    
    return all_plans