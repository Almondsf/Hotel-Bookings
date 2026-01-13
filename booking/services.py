from booking.models import Booking, Payment, Guest
from django.db import transaction
import uuid
from rooms.services import get_available_rooms_for_type, calculate_total_price, calculate_price_per_night

def process_paypal_payment(payment_token, amount):
    # TODO: Implement actual PayPal API integration
    # For now, always return True for testing
    return True

def send_confirmation_email(booking):
    # TODO: Implement email sending
    # For now, just print
    print(f"Confirmation email would be sent for booking {booking.confirmation_number}")

def create_booking_with_payment(validated_data):
    guest_data = validated_data.pop('guest')
    room_type = validated_data.pop('room_type')
    check_in_date = validated_data.pop('check_in_date')
    check_out_date = validated_data.pop('check_out_date')
    number_of_adults = validated_data.pop('number_of_adults')
    number_of_children = validated_data.pop('number_of_children')
    special_requests = validated_data.pop('special_requests', '')
    payment_token = validated_data.pop('payment_token')
    payment_method = validated_data.pop('payment_method')
    
    # 1. create guest object 
    guest = Guest.objects.create(**guest_data)
    
    # 2. find an available room
    available_rooms = get_available_rooms_for_type(room_type, check_in_date, check_out_date)
    if not available_rooms.exists():
        raise Exception("No available rooms")  # Should never happen due to validation
    room = available_rooms.first()
    total_price = calculate_total_price(room_type, check_in_date, check_out_date)
    price_per_night = calculate_price_per_night(room_type, check_in_date)
    confirmation_number = str(uuid.uuid4())
    
    # 3. create booking and payment atomically
    payment_success = process_paypal_payment(payment_token, total_price)
    if not payment_success:
        raise Exception("Payment failed")
    
    with transaction.atomic():
        booking = Booking.objects.create(
            guest=guest,
            room=room,
            check_in_date=check_in_date,
            check_out_date=check_out_date,
            number_of_adults=number_of_adults,
            number_of_children=number_of_children,
            special_requests=special_requests,
            price_per_night=price_per_night,
            total_price=total_price,
            status='CONFIRMED',
            confirmation_number=confirmation_number
        )
        
        payment = Payment.objects.create(
            booking=booking,
            amount=total_price,
            payment_method=payment_method,
            transaction_id=payment_token,  # Store the PayPal token
            status='COMPLETED',
            payment_gateway='PAYPAL'
        )
        
        
    # TODO: Implement email sending
    try:
        send_confirmation_email(booking)
    except Exception as e:
        print(f"Failed to send email: {e}")
        
    return booking
