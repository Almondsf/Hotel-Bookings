from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from payments.gateways import GatewayField
from rates.engine import WEBSITE, RatePlanUnavailable, require_plan
from rates.models import RatePlan
from rooms.models import RoomType
from rooms.services import get_available_rooms_for_type

from .exceptions import BookingError
from .models import Booking, Guest
from .policies import cancellation_penalty, describe_cancellation_policy, free_cancellation_deadline
from .validation import validate_stay


class GuestSerializer(serializers.ModelSerializer):
    def validate_email(self, value):
        return value.strip().lower()

    class Meta:
        model = Guest
        fields = ['id', 'first_name', 'last_name', 'email', 'phone_number', 'address', 'country', 'accepts_marketing']


class PaymentSerializer(serializers.Serializer):
    """Online payment attempts for a booking (no card details are ever stored)."""
    reference = serializers.CharField()
    gateway = serializers.CharField()
    status = serializers.CharField()
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    currency = serializers.CharField()
    created_at = serializers.DateTimeField()
    settled_at = serializers.DateTimeField()


def run_domain_validation(check, *args, **kwargs):
    """Run a domain validator, reporting its errors as DRF validation errors."""
    try:
        check(*args, **kwargs)
    except BookingError as e:
        raise serializers.ValidationError(e.as_response_data())


class BookingCreateSerializer(serializers.ModelSerializer):
    room_type = serializers.PrimaryKeyRelatedField(queryset=RoomType.objects.all(), write_only=True)
    guest = GuestSerializer(write_only=True)
    gateway = GatewayField(write_only=True)
    rate_plan = serializers.SlugRelatedField(slug_field='code', queryset=RatePlan.objects.filter(is_active=True),
                                             required=False, allow_null=True, write_only=True)
    promo_code = serializers.CharField(max_length=40, required=False, allow_blank=True, write_only=True)

    class Meta:
        model = Booking
        fields = [
            'guest', 'room_type', 'check_in_date', 'check_out_date',
            'number_of_adults', 'number_of_children', 'special_requests',
            'gateway', 'rate_plan', 'promo_code',
            'confirmation_number', 'status', 'price_per_night', 'total_price',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['status', 'confirmation_number', 'price_per_night', 'total_price', 'created_at', 'updated_at']


    def validate(self, data):
        run_domain_validation(
            validate_stay, data['room_type'], data['check_in_date'], data['check_out_date'],
            data['number_of_adults'], data.get('number_of_children', 0),
        )
        # Re-checked under a lock when the booking is created
        if not get_available_rooms_for_type(data['room_type'], data['check_in_date'], data['check_out_date']).exists():
            raise serializers.ValidationError("No available rooms for the selected room type and dates.")
        if data.get('rate_plan'):
            try:
                require_plan(data['rate_plan'], data['room_type'], data['check_in_date'], data['check_out_date'],
                             channel=WEBSITE, promo_code=data.get('promo_code'))
            except RatePlanUnavailable as e:
                raise serializers.ValidationError({'rate_plan': e.reasons})
        return data


class GroupRoomSerializer(serializers.Serializer):
    room_type = serializers.PrimaryKeyRelatedField(queryset=RoomType.objects.all())
    number_of_adults = serializers.IntegerField(min_value=1)
    number_of_children = serializers.IntegerField(min_value=0, default=0)


class GroupBookingCreateSerializer(serializers.Serializer):
    """Several rooms booked online together (a group plan), paid in one checkout."""
    MAX_ROOMS = 10

    guest = GuestSerializer()
    check_in_date = serializers.DateField()
    check_out_date = serializers.DateField()
    rooms = GroupRoomSerializer(many=True)
    special_requests = serializers.CharField(required=False, allow_blank=True, default='', max_length=2000)
    gateway = GatewayField()


    def validate_rooms(self, rooms):
        if not 2 <= len(rooms) <= self.MAX_ROOMS:
            raise serializers.ValidationError(f"A group booking has between 2 and {self.MAX_ROOMS} rooms.")
        return rooms

    def validate(self, data):
        for room in data['rooms']:
            run_domain_validation(
                validate_stay, room['room_type'], data['check_in_date'], data['check_out_date'],
                room['number_of_adults'], room['number_of_children'],
            )
        # Enough rooms of each type for the whole group (re-checked under a lock on creation)
        needed = {}
        for room in data['rooms']:
            needed[room['room_type']] = needed.get(room['room_type'], 0) + 1
        for room_type, count in needed.items():
            if get_available_rooms_for_type(room_type, data['check_in_date'], data['check_out_date']).count() < count:
                raise serializers.ValidationError(f"Not enough {room_type.name} rooms left for those dates.")
        return data


class TaxQuoteMixin(serializers.Serializer):
    taxes = serializers.SerializerMethodField()
    total_with_taxes = serializers.SerializerMethodField()

    def _quote(self, obj):
        from billing.models import ChargeCategory
        from billing.taxes import quote
        return quote(ChargeCategory.ROOM, obj.total_price)

    def get_taxes(self, obj) -> str:
        return str(self._quote(obj)['taxes'])

    def get_total_with_taxes(self, obj) -> str:
        return str(self._quote(obj)['gross'])


class CancellationInfoMixin(serializers.Serializer):
    cancellation_policy = serializers.SerializerMethodField()
    free_cancellation_until = serializers.SerializerMethodField()
    cancellation_fee_if_cancelled_now = serializers.SerializerMethodField()

    def get_cancellation_policy(self, obj) -> str:
        return describe_cancellation_policy(obj)

    @extend_schema_field(OpenApiTypes.DATETIME)
    def get_free_cancellation_until(self, obj):
        deadline = free_cancellation_deadline(obj)
        return timezone.localtime(deadline) if deadline else None

    def get_cancellation_fee_if_cancelled_now(self, obj) -> str | None:
        if obj.status == Booking.Status.PENDING:
            return '0.00'
        if obj.status != Booking.Status.CONFIRMED:
            return None
        return str(cancellation_penalty(obj))


class RatePlanInfoMixin(serializers.Serializer):
    rate_plan = serializers.SerializerMethodField()

    def get_rate_plan(self, obj) -> dict | None:
        plan = obj.rate_plan
        if plan is None:
            return {'code': 'BAR', 'name': 'Best Available Rate', 'meal_plan': 'RO', 'is_refundable': True}
        return {'code': plan.code, 'name': plan.name, 'meal_plan': plan.meal_plan, 'is_refundable': plan.is_refundable}


class BookingConfirmationSerializer(RatePlanInfoMixin, TaxQuoteMixin, CancellationInfoMixin, serializers.ModelSerializer):
    guest = GuestSerializer(read_only=True)
    room_number = serializers.CharField(source='room.room_number', read_only=True)
    room_type_name = serializers.CharField(source='room.room_type.name', read_only=True)
    payments = PaymentSerializer(source='payment_transactions', many=True, read_only=True)
    refunded = serializers.SerializerMethodField(help_text="Paid back to the guest from this booking's bill")

    class Meta:
        model = Booking
        fields = [
            'confirmation_number', 'guest', 'room_number', 'room_type_name', 'rate_plan',
            'check_in_date', 'check_out_date', 'number_of_adults', 'number_of_children',
            'price_per_night', 'total_price', 'taxes', 'total_with_taxes', 'status', 'payments', 'refunded',
            'cancellation_policy', 'free_cancellation_until', 'cancellation_fee_if_cancelled_now',
            'cancelled_at', 'penalty_amount', 'created_at',
        ]

    def get_refunded(self, obj) -> str:
        from billing.models import FolioPayment
        folio = getattr(obj, 'folio', None)
        if folio is None:
            return '0.00'
        total = sum((p.amount for p in folio.payments.filter(kind=FolioPayment.Kind.REFUND, is_void=False)), 0)
        return f"{total:.2f}"

class GuestBookingAccessSerializer(serializers.Serializer):
    """Guests prove access to a booking with its confirmation number and email."""
    confirmation_number = serializers.CharField(max_length=100)
    email = serializers.EmailField()

    def validate(self, data):
        booking = (
            Booking.objects
            .select_related('guest', 'room__room_type')
            .prefetch_related('payment_transactions')
            .filter(
                confirmation_number=data['confirmation_number'].strip().upper(),
                guest__email__iexact=data['email'].strip(),
            )
            .first()
        )
        data['booking'] = booking
        return data


class GuestCancelSerializer(GuestBookingAccessSerializer):
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True, default='')
