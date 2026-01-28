from rest_framework import serializers
from .models import Amenity, RoomImage, RoomPricing, RoomAvailabilityOverride, RoomType, Room
from decimal import Decimal
from rooms.services import (
    calculate_price_per_night,
    calculate_total_price
)


class AmenitySerializer(serializers.ModelSerializer):
    class Meta:

        model = Amenity
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at']

class RoomImageSerializer(serializers.ModelSerializer):
    class Meta:

        model = RoomImage
        fields = '__all__'
        read_only_fields = ['id', 'uploaded_at']


class RoomTypeSerializer(serializers.ModelSerializer):
    amenities = AmenitySerializer(many=True, read_only=True)
    
    class Meta:

        model = RoomType
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at']

class RoomTypeDetailSerializer(serializers.ModelSerializer):
    amenities = AmenitySerializer(many=True, read_only=True)
    images = RoomImageSerializer(many=True, read_only=True)
    available_room_count = serializers.SerializerMethodField()
    
    class Meta:
        model = RoomType
        fields = [
            'id', 'name', 'slug', 'description', 'base_price',
            'max_adults', 'max_children', 'bed_type', 'bed_count', 'size',
            'amenities', 'images', 'available_room_count',
            'created_at'
        ]
    
    def get_available_room_count(self, obj):
        """Returns count of rooms of this type with AVAILABLE status"""
        return obj.rooms.filter(status='AVAILABLE').count()

class RoomTypeAvailabilitySerializer(serializers.ModelSerializer):
    price_per_night = serializers.SerializerMethodField()
    total_price = serializers.SerializerMethodField()
    primary_image = serializers.SerializerMethodField()
    
    class Meta:
        model = RoomType
        fields = [
            'id', 'name', 'slug', 'description',
            'max_adults', 'max_children',
            'bed_type', 'bed_count', 'size',
            'price_per_night', 'total_price', 'primary_image'
        ]

    def get_price_per_night(self, obj):
        """
        Returns the price per night for the check-in date
        """
        check_in = self.context.get('check_in_date')

        if not check_in:
            return None

        price = calculate_price_per_night(obj, check_in)
        return price

    def get_total_price(self, obj):
        """
        Returns total price between check-in and check-out dates
        """
        check_in = self.context.get('check_in_date')
        check_out = self.context.get('check_out_date')

        if not check_in or not check_out:
            return None

        total = calculate_total_price(obj, check_in, check_out)
        return total

    def get_primary_image(self, obj):
        """
        Returns the primary image URL (or first image if no primary flag)
        """
        image = obj.images.filter(is_primary=True).first()

        if not image:
            image = obj.images.first()

        if not image:
            return None

        return image.image_url


class RoomSerializer(serializers.ModelSerializer):
    room_type = RoomTypeSerializer(read_only=True)
    
    class Meta:

        model = Room
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at']
        