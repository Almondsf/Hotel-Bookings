from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from authentication.permissions import HasCapability
from booking.models import Booking
from hotel.schema import ANY, DATE_RANGE, body, extend_schema, query, serializers as s

from . import services
from .models import KeyCard


class KeyCardSerializer(serializers.ModelSerializer):
    room_number = serializers.CharField(source='room.room_number', read_only=True)

    class Meta:
        model = KeyCard
        fields = ['id', 'room_number', 'status', 'valid_from', 'valid_until', 'issued_at', 'revoked_at', 'revoke_reason']


class BookingKeysView(APIView):
    """GET the booking's keys; POST {cards} to encode new ones."""

    def get_permissions(self):
        return [HasCapability('bookings.view' if self.request.method == 'GET' else 'bookings.manage')()]

    @extend_schema(summary='Key cards issued for a stay', responses=ANY)
    def get(self, request, booking_id):
        booking = get_object_or_404(Booking, pk=booking_id)
        return Response(KeyCardSerializer(booking.key_cards.select_related('room'), many=True).data)

    @extend_schema(summary='Encode key cards', request=body('EncodeKeys', cards=s.IntegerField(default=1, min_value=1)), responses=ANY)
    def post(self, request, booking_id):
        booking = get_object_or_404(Booking.objects.select_related('room', 'guest'), pk=booking_id)
        cards = request.data.get('cards', 1)
        if not str(cards).isdigit():
            return Response({'cards': ['Enter a number of cards.']}, status=status.HTTP_400_BAD_REQUEST)
        keys = services.issue_keys(booking, cards=int(cards), request=request)
        return Response(KeyCardSerializer(keys, many=True).data, status=status.HTTP_201_CREATED)


class RevokeKeysView(APIView):
    """Lost card: revoke all of the booking's active keys (then issue new ones)."""
    permission_classes = [HasCapability('bookings.manage')]

    @extend_schema(summary="Revoke a stay's active key cards", request=body('RevokeKeys', reason=s.CharField(required=False)), responses=ANY)
    def post(self, request, booking_id):
        booking = get_object_or_404(Booking, pk=booking_id)
        revoked = services.revoke_keys(booking, reason=str(request.data.get('reason') or 'Lost card'), request=request)
        return Response({'revoked': revoked})
