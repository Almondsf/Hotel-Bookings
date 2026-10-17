from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from billing.models import CorporateAccount
from rooms.models import Room, RoomType

from django.utils import timezone

from .models import Booking, BookingGroup, Guest, GuestIdentification
from rates.models import RatePlan

from .serializers import CancellationInfoMixin, PaymentSerializer, RatePlanInfoMixin, TaxQuoteMixin

MAX_ROOMS_PER_RESERVATION = 30


class GuestProfileSerializer(serializers.ModelSerializer):
    """Guest as seen by staff, including internal fields guests can't set themselves."""
    has_valid_identification = serializers.BooleanField(read_only=True)

    def validate_email(self, value):
        return value.strip().lower()

    class Meta:
        model = Guest
        fields = [
            'id', 'first_name', 'last_name', 'email', 'phone_number', 'address', 'country',
            'nationality', 'date_of_birth', 'company_name', 'is_vip', 'notes',
            'has_valid_identification', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class GuestStaySerializer(serializers.ModelSerializer):
    room_number = serializers.CharField(source='room.room_number', read_only=True)

    class Meta:
        model = Booking
        fields = ['id', 'confirmation_number', 'status', 'room_number', 'check_in_date', 'check_out_date', 'total_price']
        read_only_fields = fields


class GuestDetailSerializer(GuestProfileSerializer):
    stays = serializers.SerializerMethodField()

    class Meta(GuestProfileSerializer.Meta):
        fields = GuestProfileSerializer.Meta.fields + ['stays']

    @extend_schema_field(GuestStaySerializer(many=True))
    def get_stays(self, obj):
        bookings = obj.bookings.select_related('room').order_by('-check_in_date')[:50]
        return GuestStaySerializer(bookings, many=True).data


class IdentificationSerializer(serializers.ModelSerializer):
    """Write the full number; reads only ever show the masked form."""
    document_number = serializers.CharField(write_only=True, min_length=4, max_length=50)
    masked_number = serializers.CharField(read_only=True)
    is_expired = serializers.BooleanField(read_only=True)
    captured_by = serializers.EmailField(source='captured_by.email', default=None, read_only=True)

    class Meta:
        model = GuestIdentification
        fields = ['id', 'document_type', 'document_number', 'masked_number', 'issuing_country',
                  'expiry_date', 'is_expired', 'captured_by', 'captured_at']
        read_only_fields = ['id', 'captured_at']

    def validate_document_number(self, value):
        return value.upper().replace(' ', '')

    def validate_expiry_date(self, value):
        if value and value < timezone.localdate():
            raise serializers.ValidationError("This document has expired.")
        return value


class ReservationSerializer(RatePlanInfoMixin, TaxQuoteMixin, CancellationInfoMixin, serializers.ModelSerializer):
    guest = GuestProfileSerializer(read_only=True)
    group_reference = serializers.CharField(source='group.reference', default=None, read_only=True)
    room_number = serializers.CharField(source='room.room_number', read_only=True)
    room_type = serializers.IntegerField(source='room.room_type_id', read_only=True)
    room_type_name = serializers.CharField(source='room.room_type.name', read_only=True)
    created_by = serializers.EmailField(source='created_by.email', default=None, read_only=True)
    payments = PaymentSerializer(source='payment_transactions', many=True, read_only=True)
    folio = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = [
            'id', 'confirmation_number', 'folio', 'rate_plan', 'corporate_account', 'nightly_rate_override',
            'rate_override_reason', 'group_reference', 'status', 'source',
            'guest', 'room', 'room_number', 'room_type', 'room_type_name',
            'check_in_date', 'check_out_date', 'nights', 'number_of_adults', 'number_of_children',
            'special_requests', 'price_per_night', 'total_price', 'taxes', 'total_with_taxes',
            'hold_expires_at', 'confirmed_at', 'checked_in_at', 'checked_out_at',
            'cancelled_at', 'cancellation_reason', 'penalty_amount', 'penalty_waived',
            'cancellation_policy', 'free_cancellation_until', 'cancellation_fee_if_cancelled_now',
            'payments', 'created_by', 'created_at', 'updated_at',
        ]
        read_only_fields = fields

    def get_folio(self, obj) -> dict | None:
        try:
            folio = obj.folio
        except Booking.folio.RelatedObjectDoesNotExist:
            return None
        return {'id': folio.pk, 'number': folio.number, 'status': folio.status, 'balance': str(folio.balance)}


class ReservationRoomSerializer(serializers.Serializer):
    room_type = serializers.PrimaryKeyRelatedField(queryset=RoomType.objects.all())
    room = serializers.PrimaryKeyRelatedField(queryset=Room.objects.all(), required=False, allow_null=True,
                                              help_text="A specific room; otherwise one is assigned.")
    number_of_adults = serializers.IntegerField(min_value=1)
    number_of_children = serializers.IntegerField(min_value=0, default=0)


class ReservationCreateSerializer(serializers.Serializer):
    guest_id = serializers.PrimaryKeyRelatedField(queryset=Guest.objects.all(), required=False, source='existing_guest')
    guest = GuestProfileSerializer(required=False, allow_null=True)
    check_in_date = serializers.DateField()
    check_out_date = serializers.DateField()
    rooms = ReservationRoomSerializer(many=True, allow_empty=False, max_length=MAX_ROOMS_PER_RESERVATION)
    special_requests = serializers.CharField(required=False, allow_blank=True, default='')
    source = serializers.ChoiceField(
        choices=[c for c in Booking.Source.choices if c[0] != Booking.Source.WEBSITE],
        default=Booking.Source.FRONT_DESK,
    )
    notes = serializers.CharField(required=False, allow_blank=True, default='',
                                  help_text="Internal notes for group reservations.")
    rate_plan = serializers.PrimaryKeyRelatedField(queryset=RatePlan.objects.filter(is_active=True), required=False,
                                                   allow_null=True)
    corporate_account = serializers.PrimaryKeyRelatedField(queryset=CorporateAccount.objects.filter(is_active=True),
                                                           required=False, allow_null=True)
    rate_override = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0, required=False,
                                             allow_null=True, help_text="Manager-agreed nightly rate")
    override_reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')

    def validate(self, data):
        if bool(data.get('existing_guest')) == bool(data.get('guest')):
            raise serializers.ValidationError("Provide either guest_id (existing guest) or guest (new guest).")
        if data.get('rate_override') is not None:
            if not self.context['request'].user.has_capability('rates.override'):
                raise serializers.ValidationError({'rate_override': "Only managers can override rates."})
        return data


class ReservationUpdateSerializer(serializers.Serializer):
    check_in_date = serializers.DateField(required=False)
    check_out_date = serializers.DateField(required=False)
    room_type = serializers.PrimaryKeyRelatedField(queryset=RoomType.objects.all(), required=False)
    room = serializers.PrimaryKeyRelatedField(queryset=Room.objects.all(), required=False)
    number_of_adults = serializers.IntegerField(min_value=1, required=False)
    number_of_children = serializers.IntegerField(min_value=0, required=False)
    special_requests = serializers.CharField(required=False, allow_blank=True)

    def validate(self, data):
        if not data:
            raise serializers.ValidationError("Nothing to change.")
        if data.get('room') and data.get('room_type') and data['room'].room_type_id != data['room_type'].pk:
            raise serializers.ValidationError({"room": "Room does not belong to the selected room type."})
        return data


class CheckOutSerializer(serializers.Serializer):
    transfer_to_account = serializers.PrimaryKeyRelatedField(
        queryset=CorporateAccount.objects.all(), required=False, allow_null=True,
        help_text="Bill the outstanding balance to this company account.",
    )


class PenaltyActionSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True, default='')
    waive_penalty = serializers.BooleanField(default=False)


class CheckInSerializer(serializers.Serializer):
    identification = IdentificationSerializer(required=False, allow_null=True)


class MoveRoomSerializer(serializers.Serializer):
    room = serializers.PrimaryKeyRelatedField(queryset=Room.objects.all())
    reason = serializers.CharField(max_length=500)
    reprice = serializers.BooleanField(default=False, help_text="Charge the new room type's rates for the remaining nights.")


class WalkInSerializer(serializers.Serializer):
    guest_id = serializers.PrimaryKeyRelatedField(queryset=Guest.objects.all(), required=False, source='existing_guest')
    guest = GuestProfileSerializer(required=False, allow_null=True)
    room = ReservationRoomSerializer()
    check_out_date = serializers.DateField()
    identification = IdentificationSerializer(required=False, allow_null=True)

    def validate(self, data):
        if bool(data.get('existing_guest')) == bool(data.get('guest')):
            raise serializers.ValidationError("Provide either guest_id (existing guest) or guest (new guest).")
        return data


class GroupActionResultSerializer(serializers.Serializer):
    """What a whole-group action did to one room."""
    confirmation_number = serializers.CharField()
    room_number = serializers.CharField(allow_null=True)
    ok = serializers.BooleanField()
    error = serializers.CharField(allow_blank=True, help_text="Why this room was skipped (empty when ok).")


class BookingGroupSerializer(serializers.ModelSerializer):
    """A group with every room in it and the figures the desk needs at a glance."""
    booker = GuestProfileSerializer(read_only=True)
    created_by = serializers.EmailField(source='created_by.email', default=None, read_only=True)
    bookings = serializers.SerializerMethodField()
    totals = serializers.SerializerMethodField()

    class Meta:
        model = BookingGroup
        fields = ['reference', 'booker', 'notes', 'created_by', 'created_at', 'bookings', 'totals']
        read_only_fields = fields

    def _bookings(self, obj):
        if not hasattr(obj, '_rooms'):
            obj._rooms = list(
                obj.bookings.select_related('guest', 'room__room_type', 'group', 'created_by', 'folio', 'rate_plan')
                .prefetch_related('payment_transactions').order_by('pk'))
        return obj._rooms

    @extend_schema_field(ReservationSerializer(many=True))
    def get_bookings(self, obj):
        return ReservationSerializer(self._bookings(obj), many=True).data

    @extend_schema_field(serializers.DictField())
    def get_totals(self, obj) -> dict:
        rooms = self._bookings(obj)
        live = [b for b in rooms if b.status != Booking.Status.CANCELLED]
        balance = sum((b.folio.balance for b in rooms if hasattr(b, 'folio')), 0)
        return {
            'rooms': len(live),
            'adults': sum(b.number_of_adults for b in live),
            'children': sum(b.number_of_children for b in live),
            'total_price': f"{sum((b.total_price for b in live), 0):.2f}",
            'balance': f"{balance:.2f}",
            'by_status': {s: sum(1 for b in rooms if b.status == s) for s in {b.status for b in rooms}},
        }


class GroupActionResponseSerializer(serializers.Serializer):
    group = BookingGroupSerializer()
    results = GroupActionResultSerializer(many=True)
