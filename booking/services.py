from booking.models import Booking, Payment, Guest
from django.db import transaction
import uuid
import random
import string
from rooms.services import get_available_rooms_for_type, calculate_total_price, calculate_price_per_night
from django.core.mail import send_mail
from django.conf import settings

def process_paypal_payment(payment_token, amount):
    # TODO: Implement actual PayPal API integration
    # For now, always return True for testing
    return True



def send_confirmation_email(booking):
    """Send booking confirmation email to guest"""
    subject = f'Booking Confirmation - {booking.confirmation_number}'
    
    message = f"""
    Dear {booking.guest.first_name} {booking.guest.last_name},

    Thank you for your booking!

    Booking Details:
    Confirmation Number: {booking.confirmation_number}
    Room: {booking.room.room_type.name} - Room {booking.room.room_number}
    Check-in: {booking.check_in_date}
    Check-out: {booking.check_out_date}
    Guests: {booking.number_of_adults} adults, {booking.number_of_children} children
    Total Price: ${booking.total_price}

    We look forward to welcoming you!

    Best regards,
    Hotel Team
    """
    
    from_email = settings.DEFAULT_FROM_EMAIL
    recipient_list = [booking.guest.email]
    
    send_mail(
        subject=subject,
        message=message,
        from_email=from_email,
        recipient_list=recipient_list,
        fail_silently=False,
    )

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
    def generate_confirmation_number():
        """Generate a short, unique confirmation number like BK-ABC123"""
        chars = string.ascii_uppercase + string.digits
        random_part = ''.join(random.choices(chars, k=6))
        code = f"BK-{random_part}"
        
        # Ensure uniqueness - regenerate if exists
        while Booking.objects.filter(confirmation_number=code).exists():
            random_part = ''.join(random.choices(chars, k=6))
            code = f"BK-{random_part}"
        
        return code

    # Then in create_booking_with_payment(), replace the uuid line with:
    confirmation_number = generate_confirmation_number()
    
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

