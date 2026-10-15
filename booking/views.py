from rest_framework import status
from rest_framework.generics import CreateAPIView, GenericAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from audit.models import AuditLog
from audit.services import record

from . import lifecycle
from .services import create_online_booking, create_online_group_booking
from .serializers import (
    BookingConfirmationSerializer,
    BookingCreateSerializer,
    GroupBookingCreateSerializer,
    GuestBookingAccessSerializer,
    GuestCancelSerializer,
)


def not_found():
    # Same response for "no such booking" and "wrong email", so these endpoints
    # can't be used to discover valid confirmation numbers.
    return Response({"error": "Booking not found."}, status=status.HTTP_404_NOT_FOUND)


class CreateBookingView(CreateAPIView):
    serializer_class = BookingCreateSerializer
    permission_classes = [AllowAny]
    throttle_scope = 'booking_create'

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        booking, txn = create_online_booking(serializer.validated_data)
        record(AuditLog.Action.BOOKING_CREATED, request=request, actor_email=booking.guest.email, target=booking)
        return Response({
            **BookingConfirmationSerializer(booking).data,
            # Send the guest here to pay; the booking is confirmed once payment is verified
            'payment': {'reference': txn.reference, 'gateway': txn.gateway, 'amount': str(txn.amount),
                        'currency': txn.currency, 'authorization_url': txn.authorization_url},
        }, status=status.HTTP_201_CREATED)


class CreateGroupBookingView(CreateAPIView):
    """Book a group plan online: several rooms held together and paid in one checkout."""
    serializer_class = GroupBookingCreateSerializer
    permission_classes = [AllowAny]
    throttle_scope = 'booking_create'

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        group, bookings, txn = create_online_group_booking(serializer.validated_data)
        for booking in bookings:
            record(AuditLog.Action.BOOKING_CREATED, request=request, actor_email=booking.guest.email, target=booking,
                   changes={'group': group.reference, 'source': 'WEBSITE'})
        return Response({
            'group_reference': group.reference,
            'bookings': BookingConfirmationSerializer(bookings, many=True).data,
            'payment': {'reference': txn.reference, 'gateway': txn.gateway, 'amount': str(txn.amount),
                        'currency': txn.currency, 'authorization_url': txn.authorization_url},
        }, status=status.HTTP_201_CREATED)


class GuestBookingView(GenericAPIView):
    """Base for guest self-service endpoints authenticated by confirmation number + email."""
    permission_classes = [AllowAny]
    throttle_scope = 'booking_lookup'

    def validated(self, request):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return None
        return serializer.validated_data


class BookingLookupView(GuestBookingView):
    serializer_class = GuestBookingAccessSerializer

    def post(self, request, *args, **kwargs):
        data = self.validated(request)
        if data is None:
            return Response({"error": "Both confirmation_number and a valid email are required."},
                            status=status.HTTP_400_BAD_REQUEST)
        if data['booking'] is None:
            return not_found()
        return Response(BookingConfirmationSerializer(data['booking']).data)


class GuestCancelBookingView(GuestBookingView):
    """Guest self-service cancellation under the hotel's cancellation policy."""
    serializer_class = GuestCancelSerializer

    def post(self, request, *args, **kwargs):
        data = self.validated(request)
        if data is None:
            return Response({"error": "Both confirmation_number and a valid email are required."},
                            status=status.HTTP_400_BAD_REQUEST)
        if data['booking'] is None:
            return not_found()
        booking = lifecycle.cancel(data['booking'], reason=data['reason'], request=request, by_guest=True)
        return Response(BookingConfirmationSerializer(booking).data)
