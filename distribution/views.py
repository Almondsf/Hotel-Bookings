import hmac

from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from authentication.permissions import HasCapability
from hotel.schema import ANY, DATE_RANGE, body, extend_schema, query, serializers as s

from . import services
from .models import ChannelBooking


class ChannexWebhookView(APIView):
    """
    Channex calls this when a booking arrives or changes. The payload isn't
    trusted: we only use it as a cue to pull revisions over the API.
    Configure the webhook with header X-Webhook-Secret.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = []

    @extend_schema(summary='Channel manager webhook (shared secret)', request=ANY, responses=ANY)
    def post(self, request):
        connection = services.active_connection()
        secret = request.headers.get('X-Webhook-Secret', '')
        if connection is None or not connection.webhook_secret or not hmac.compare_digest(secret, connection.webhook_secret):
            return Response(status=status.HTTP_401_UNAUTHORIZED)
        services.pull_bookings.enqueue()
        return Response(status=status.HTTP_202_ACCEPTED)


class ChannelBookingSerializer(serializers.ModelSerializer):
    bookings = serializers.SlugRelatedField(slug_field='confirmation_number', many=True, read_only=True)

    class Meta:
        model = ChannelBooking
        fields = ['id', 'external_id', 'ota_name', 'ota_reference', 'status', 'problem', 'bookings', 'received_at',
                  'updated_at']


class ChannelStatusView(APIView):
    """Connection health and OTA bookings that need a person (rooms to find, in-house changes)."""
    permission_classes = [HasCapability('bookings.view')]

    @extend_schema(summary='Channel connection status and bookings needing attention', responses=ANY)
    def get(self, request):
        connection = services.active_connection()
        attention = ChannelBooking.objects.filter(status=ChannelBooking.Status.NEEDS_ATTENTION).prefetch_related('bookings')
        recent = ChannelBooking.objects.prefetch_related('bookings')[:20]
        return Response({
            'connected': connection is not None,
            'provider': connection.provider if connection else None,
            'last_full_sync_at': connection.last_full_sync_at if connection else None,
            'last_error': connection.last_error if connection else '',
            'needs_attention': ChannelBookingSerializer(attention, many=True).data,
            'recent': ChannelBookingSerializer(recent, many=True).data,
        })


class ChannelSyncView(APIView):
    """Republish everything now (e.g. after changing rates)."""
    permission_classes = [HasCapability('rates.manage')]

    @extend_schema(summary='Push availability and rates and pull bookings now', request=None, responses=ANY)
    def post(self, request):
        if services.active_connection() is None:
            return Response({'error': 'No channel manager is connected.'}, status=status.HTTP_400_BAD_REQUEST)
        services.push_ari.enqueue()
        services.pull_bookings.enqueue()
        return Response({'detail': 'Sync queued.'}, status=status.HTTP_202_ACCEPTED)


class ResolveChannelBookingView(APIView):
    """Mark a flagged OTA booking as handled once staff have placed or moved it by hand."""
    permission_classes = [HasCapability('bookings.manage')]

    @extend_schema(summary='Mark a flagged channel booking as handled', request=ANY, responses=ANY)
    def post(self, request, pk):
        updated = ChannelBooking.objects.filter(pk=pk, status=ChannelBooking.Status.NEEDS_ATTENTION).update(
            status=ChannelBooking.Status.IMPORTED, problem=f"Resolved by {request.user.email}")
        if not updated:
            return Response({'error': 'Nothing to resolve.'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'detail': 'Resolved.'})
