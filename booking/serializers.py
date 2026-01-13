from rest_framework import serializers
from .models import Guest, Payment, Booking
from rooms.models import RoomType
from rooms.services import get_available_rooms_for_type  
from datetime import date


class GuestSerializer(serializers.ModelSerializer):
    class Meta:
        model = Guest
        fields = ['id', 'first_name', 'last_name', 'email', 'phone_number', 'address', 'country']
        
class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ['id', 'amount', 'payment_method', 'payment_gateway', 'status', 'created_at', 'completed_at']


class BookingCreateSerializer(serializers.ModelSerializer):
    room_type = serializers.PrimaryKeyRelatedField(queryset=RoomType.objects.all(), write_only=True)
    guest = GuestSerializer(write_only=True)
    payment_token = serializers.CharField(write_only=True)
    payment_method = serializers.ChoiceField(choices=Payment.PAYMENT_METHOD_CHOICES, write_only=True)
    class Meta:
        model = Booking
        fields = [
            'guest', 'room_type', 'check_in_date', 'check_out_date',
            'number_of_adults', 'number_of_children', 'special_requests',
            'payment_token', 'payment_method',
            'confirmation_number', 'status', 'price_per_night', 'total_price',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['status', 'confirmation_number', 'price_per_night', 'total_price', 'created_at', 'updated_at']
        
    def validate_check_in_date(self, value):
        if value < date.today():
            raise serializers.ValidationError(
                "Check-in date cannot be in the past."
            )
        return value
    
    def validate_number_of_adults(self, value):
        if value < 1:
            raise serializers.ValidationError(
                "At least one adult is required for a booking."
            )
        return value
    
    def validate_number_of_children(self, value):
        if value < 0:
            raise serializers.ValidationError("Number of children cannot be negative.")
        return value
 
    def validate(self, data):
        check_in = data.get('check_in_date')
        check_out = data.get('check_out_date')
        room_type = data.get('room_type')
        adults = data.get('number_of_adults')
        children = data.get('number_of_children', 0)

        # Date logic
        if check_in >= check_out:
            raise serializers.ValidationError(
                {"check_out_date": "Check-out date must be after check-in date."}
            )

        # Capacity validation
        if adults > room_type.max_adults:
            raise serializers.ValidationError(
                {"number_of_adults": "Number of adults exceeds room capacity."}
            )

        if children > room_type.max_children:
            raise serializers.ValidationError(
                {"number_of_children": "Number of children exceeds room capacity."}
            )

        # 3. Availability check
        available_rooms = get_available_rooms_for_type(
            room_type=room_type,
            check_in_date=check_in,
            check_out_date=check_out
        )

        if not available_rooms.exists():
            raise serializers.ValidationError(
                "No available rooms for the selected room type and dates."
            )

        return data
    
    def create(self, validated_data):
        from booking.services import create_booking_with_payment

        booking = create_booking_with_payment(validated_data)

        return booking

class BookingConfirmationSerializer(serializers.ModelSerializer):
    guest = GuestSerializer(read_only=True)
    room_number = serializers.CharField(source='room.room_number', read_only=True)
    room_type_name = serializers.CharField(source='room.room_type.name', read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)
    class Meta:
        model = Booking
        fields = [
            'confirmation_number', 'guest', 'room_number', 'room_type_name',
            'check_in_date', 'check_out_date', 'number_of_adults', 'number_of_children',
            'price_per_night', 'total_price', 'status', 'payments',
            'created_at'
        ]