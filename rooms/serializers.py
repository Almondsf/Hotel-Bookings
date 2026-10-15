from rest_framework import serializers
from .models import Amenity, RoomImage, RoomPricing, RoomAvailabilityOverride, RoomType, Room
from django.conf import settings
from django.utils import timezone

from hotel.clock import business_date
from rooms.services import (
    calculate_average_price_per_night,
    calculate_total_price
)


class RoomSearchQuerySerializer(serializers.Serializer):
    """Validates availability search query parameters."""
    check_in = serializers.DateField()
    check_out = serializers.DateField()
    adults = serializers.IntegerField(min_value=1, max_value=settings.MAX_GUESTS_PER_SEARCH)
    children = serializers.IntegerField(min_value=0, max_value=settings.MAX_GUESTS_PER_SEARCH, default=0)

    def validate_check_in(self, value):
        if value < business_date():
            raise serializers.ValidationError("Check-in date cannot be in the past")
        return value

    def validate(self, data):
        nights = (data['check_out'] - data['check_in']).days
        if nights < 1:
            raise serializers.ValidationError({"check_out": "Check-out must be after check-in"})
        if nights > settings.MAX_STAY_NIGHTS:
            raise serializers.ValidationError(
                {"check_out": f"Stays longer than {settings.MAX_STAY_NIGHTS} nights must be booked with the hotel directly"}
            )
        return data


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
    
    def get_available_room_count(self, obj) -> int:
        """Returns count of sellable rooms of this type"""
        return obj.rooms.exclude(status__in=Room.UNSELLABLE_STATUSES).count()

class RoomTypeAvailabilitySerializer(serializers.ModelSerializer):
    price_per_night = serializers.SerializerMethodField()
    total_price = serializers.SerializerMethodField()
    taxes = serializers.SerializerMethodField()
    total_with_taxes = serializers.SerializerMethodField()
    rate_plans = serializers.SerializerMethodField()
    primary_image = serializers.SerializerMethodField()
    
    class Meta:
        model = RoomType
        fields = [
            'id', 'name', 'slug', 'description',
            'max_adults', 'max_children',
            'bed_type', 'bed_count', 'size',
            'price_per_night', 'total_price', 'taxes', 'total_with_taxes', 'primary_image', 'rate_plans'
        ]

    def get_price_per_night(self, obj):
        """
        Returns the average nightly price across the stay
        """
        check_in = self.context.get('check_in_date')
        check_out = self.context.get('check_out_date')

        if not check_in or not check_out:
            return None

        return calculate_average_price_per_night(obj, check_in, check_out)

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

    def _quote(self, obj):
        from billing.models import ChargeCategory
        from billing.taxes import quote
        total = self.get_total_price(obj)
        return quote(ChargeCategory.ROOM, total) if total is not None else None

    def get_taxes(self, obj) -> str:
        q = self._quote(obj)
        return q and q['taxes']

    def get_total_with_taxes(self, obj) -> str:
        q = self._quote(obj)
        return q and q['gross']

    def get_rate_plans(self, obj):
        """Bookable rate plans for this stay, cheapest first, with taxes."""
        from billing.models import ChargeCategory
        from billing.taxes import quote
        from rates.engine import quote_plans

        check_in, check_out = self.context.get('check_in_date'), self.context.get('check_out_date')
        if not check_in or not check_out:
            return []
        plans = []
        for plan_quote in quote_plans(obj, check_in, check_out, promo_code=self.context.get('promo_code')):
            plan, priced = plan_quote.plan, quote(ChargeCategory.ROOM, plan_quote.total)
            plans.append({
                'code': plan.code, 'name': plan.name, 'description': plan.description,
                'meal_plan': plan.meal_plan, 'meal_plan_name': plan.get_meal_plan_display(),
                'is_refundable': plan.is_refundable, 'total_price': str(priced['net']),
                'taxes': str(priced['taxes']), 'total_with_taxes': str(priced['gross']),
                **cancellation_terms(plan, check_in),
            })
        return plans

    def get_primary_image(self, obj):
        """
        Returns the primary image URL (or first image if no primary flag)
        """
        images = list(obj.images.all())  # uses prefetch; ordered primary-first
        return images[0].image_url if images else None


def cancellation_terms(plan, check_in_date):
    """
    When free cancellation ends for a stay starting `check_in_date` under `plan` (None = best
    available rate), using the same policy that prices a cancellation. A last-minute booking may
    already be past it, so guests are told before they pay.
    """
    from types import SimpleNamespace

    from booking.policies import free_cancellation_deadline

    deadline = free_cancellation_deadline(SimpleNamespace(rate_plan=plan, check_in_date=check_in_date))
    return {
        'free_cancellation_until': timezone.localtime(deadline).isoformat() if deadline else None,
        'free_cancellation_passed': deadline is None or deadline <= timezone.now(),
    }


class RoomSerializer(serializers.ModelSerializer):
    room_type = serializers.PrimaryKeyRelatedField(queryset=RoomType.objects.all())
    room_type_detail = RoomTypeSerializer(source='room_type', read_only=True)
    
    class Meta:

        model = Room
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at']
        