from rest_framework import serializers
from .models import Amenity, RoomImage, RoomPricing, RoomAvailabilityOverride, RoomType, Room


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

class RoomSeriaizer(serializers.ModelSerializer):
    room_type = RoomTypeSerializer(read_only=True)
    
    class Meta:

        model = Room
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at']
        