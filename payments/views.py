import logging
import re

from django.shortcuts import get_object_or_404
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.models import AuditLog
from audit.services import record
from authentication.permissions import HasCapability
from billing.models import Folio
from hotel.schema import ANY, DATE_RANGE, body, extend_schema, query, serializers as s

from . import services
from .gateways import GATEWAYS, GatewayError, GatewayField
from .models import PaymentTransaction

logger = logging.getLogger(__name__)

REFERENCE_PATTERN = re.compile(r'^PAY-[0-9A-F]{20}$')


class TransactionSerializer(serializers.ModelSerializer):
    booking = serializers.CharField(source='booking.confirmation_number', default=None, read_only=True)
    folio = serializers.CharField(source='folio.number', read_only=True)

    class Meta:
        model = PaymentTransaction
        fields = ['id', 'reference', 'gateway', 'purpose', 'booking', 'folio', 'amount', 'currency', 'email',
                  'status', 'authorization_url', 'gateway_transaction_id', 'refunded_amount', 'review_reason',
                  'created_at', 'settled_at']
        read_only_fields = fields


class VerifyPaymentView(APIView):
    """
    Called by the guest site when the gateway redirects back. The outcome is
    always fetched from the gateway, never taken from the request.
    """
    permission_classes = [AllowAny]
    throttle_scope = 'payment_verify'

    @extend_schema(summary='Confirm an online payment after the gateway redirect', request=body('VerifyPayment', reference=s.CharField()), responses=ANY)
    def post(self, request):
        reference = str(request.data.get('reference', '')).strip().upper()
        if not REFERENCE_PATTERN.match(reference):
            return Response({"error": "Invalid payment reference."}, status=status.HTTP_400_BAD_REQUEST)
        if not PaymentTransaction.objects.filter(reference=reference).exists():
            return Response({"error": "Payment not found."}, status=status.HTTP_404_NOT_FOUND)
        txn = services.confirm_payment(reference)
        booking = txn.booking
        if booking is not None:
            booking.refresh_from_db()
        group = None
        if booking is not None and booking.group_id:
            members = booking.group.bookings.select_related('room__room_type').order_by('pk')
            group = {'reference': booking.group.reference, 'bookings': [
                {'confirmation_number': b.confirmation_number, 'status': b.status, 'room_type_name': b.room.room_type.name,
                 'number_of_adults': b.number_of_adults, 'number_of_children': b.number_of_children} for b in members]}
        return Response({
            'reference': txn.reference,
            'status': txn.status,
            'booking': {'confirmation_number': booking.confirmation_number, 'status': booking.status} if booking else None,
            'group': group,
        })


class WebhookView(APIView):
    """Gateway webhooks. Authenticated by signature, not by user."""
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = []
    gateway_code = None

    @extend_schema(summary='Gateway webhook (signature-checked)', request=ANY, responses=ANY)
    def post(self, request):
        gateway = GATEWAYS[self.gateway_code]()
        try:
            reference = gateway.webhook_reference(request)
        except PermissionError:
            logger.warning("Rejected %s webhook with a bad signature from %s", self.gateway_code,
                           request.META.get('REMOTE_ADDR'))
            return Response(status=status.HTTP_401_UNAUTHORIZED)
        except ValueError:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        if reference and PaymentTransaction.objects.filter(reference=reference, gateway=self.gateway_code).exists():
            try:
                services.confirm_payment(reference)
            except GatewayError:
                # Tell the provider to retry later
                return Response(status=status.HTTP_503_SERVICE_UNAVAILABLE)
        # Acknowledge everything else so the provider stops retrying
        return Response(status=status.HTTP_200_OK)


class PaystackWebhookView(WebhookView):
    gateway_code = 'PAYSTACK'


class FlutterwaveWebhookView(WebhookView):
    gateway_code = 'FLUTTERWAVE'


class PaymentLinkSerializer(serializers.Serializer):
    folio = serializers.PrimaryKeyRelatedField(queryset=Folio.objects.filter(status=Folio.Status.OPEN))
    gateway = GatewayField()
    email = serializers.EmailField()
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, required=False,
                                      help_text="Defaults to the folio balance")



class RefundSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    reason = serializers.CharField(max_length=255)


class TransactionViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = TransactionSerializer
    queryset = PaymentTransaction.objects.select_related('booking', 'folio')

    def get_permissions(self):
        capability = {'refund': 'payments.refund', 'payment_link': 'payments.take'}.get(self.action, 'folios.view')
        return [HasCapability(capability)()]

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.query_params.get('status'):
            queryset = queryset.filter(status=self.request.query_params['status'].upper())
        return queryset

    @action(detail=False, methods=['post'], url_path='payment-link')
    def payment_link(self, request):
        """Create a checkout link for an outstanding folio, to send to the guest or company."""
        serializer = PaymentLinkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        folio = data['folio']
        txn = services.start_payment(
            gateway=data['gateway'], folio=folio, amount=data.get('amount') or folio.balance, email=data['email'],
            purpose=PaymentTransaction.Purpose.FOLIO_SETTLEMENT, customer_name=folio.display_name,
            description=f"Folio {folio.number}",
        )
        record(AuditLog.Action.PAYMENT_LINK_CREATED, request=request, target=txn,
               changes={'folio': folio.number, 'amount': str(txn.amount)})
        return Response(TransactionSerializer(txn).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def refund(self, request, pk=None):
        serializer = RefundSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        txn = services.refund_transaction(get_object_or_404(PaymentTransaction, pk=pk), request=request,
                                          **serializer.validated_data)
        record(AuditLog.Action.ONLINE_PAYMENT_REFUNDED, request=request, target=txn,
               changes={'amount': str(serializer.validated_data['amount'])})
        return Response(TransactionSerializer(txn).data)
