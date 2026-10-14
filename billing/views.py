from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from audit.models import AuditLog
from audit.services import record
from authentication.permissions import HasCapability

from . import services
from .models import CorporateAccount, ExchangeRate, Folio, Invoice, TaxRule
from .pdf import render_invoice
from .serializers import (
    AccountPaymentSerializer,
    ChargeSerializer,
    CorporateAccountSerializer,
    ExchangeRateSerializer,
    FolioDetailSerializer,
    FolioPaymentSerializer,
    FolioSerializer,
    InvoiceSummarySerializer,
    NonGuestFolioSerializer,
    PostChargeSerializer,
    ReasonSerializer,
    RecordPaymentSerializer,
    RefundSerializer,
    TaxRuleSerializer,
    TransferChargeSerializer,
    TransferToAccountSerializer,
)


class CapabilityPerActionMixin:
    """Map each viewset action to the capability it requires."""
    capabilities = {}
    default_capability = None

    def get_permissions(self):
        return [HasCapability(self.capabilities.get(self.action, self.default_capability))()]


class FolioViewSet(CapabilityPerActionMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                   viewsets.GenericViewSet):
    """
    Folios. Filters: ?status=OPEN ?booking=<id> ?account=<code> ?q=<guest or folio name>
    """
    default_capability = 'folios.view'
    capabilities = {
        'create': 'folios.post',
        'charges': 'folios.post',
        'void_charge': 'folios.adjust',
        'transfer_charge': 'folios.adjust',
        'payments': 'payments.take',
        'void_payment': 'folios.adjust',
        'refunds': 'payments.refund',
        'transfer_to_account': 'accounts.manage',
        'settle': 'payments.take',
    }

    def get_serializer_class(self):
        return FolioDetailSerializer if self.action == 'retrieve' else FolioSerializer

    def get_queryset(self):
        queryset = Folio.objects.select_related('booking', 'guest', 'account')
        if self.action == 'retrieve':
            queryset = queryset.prefetch_related('charges__posted_by', 'payments__received_by', 'invoices')
        params = self.request.query_params
        if params.get('status'):
            queryset = queryset.filter(status=params['status'].upper())
        if params.get('booking', '').isdigit():
            queryset = queryset.filter(booking_id=params['booking'])
        if params.get('account'):
            queryset = queryset.filter(account__code=params['account'])
        if params.get('q'):
            q = params['q']
            queryset = queryset.filter(name__icontains=q) | queryset.filter(guest__last_name__icontains=q)
        return queryset

    def detail_response(self, folio, status_code=status.HTTP_200_OK):
        return Response(FolioDetailSerializer(self.get_queryset().get(pk=folio.pk)).data, status=status_code)

    def create(self, request):
        """Open a folio for a non-staying customer."""
        serializer = NonGuestFolioSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        folio = services.open_non_guest_folio(name=serializer.validated_data['name'], request=request)
        return self.detail_response(folio, status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def charges(self, request, pk=None):
        serializer = PostChargeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data['category'] == 'ALLOWANCE' and not request.user.has_capability('folios.adjust'):
            return Response({"error": "Only managers and accountants can post allowances."},
                            status=status.HTTP_403_FORBIDDEN)
        charge = services.post_charge(self.get_object(), request=request, **data)
        return Response(ChargeSerializer(charge).data, status=status.HTTP_201_CREATED)

    def _charge(self, folio, charge_id):
        return get_object_or_404(folio.charges, pk=charge_id)

    @action(detail=True, methods=['post'], url_path=r'charges/(?P<charge_id>[0-9]+)/void')
    def void_charge(self, request, pk=None, charge_id=None):
        serializer = ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        folio = self.get_object()
        services.void_charge(self._charge(folio, charge_id), reason=serializer.validated_data['reason'], request=request)
        return self.detail_response(folio)

    @action(detail=True, methods=['post'], url_path=r'charges/(?P<charge_id>[0-9]+)/transfer')
    def transfer_charge(self, request, pk=None, charge_id=None):
        serializer = TransferChargeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        folio = self.get_object()
        services.transfer_charge(self._charge(folio, charge_id), serializer.validated_data['to_folio'],
                                 reason=serializer.validated_data['reason'], request=request)
        return self.detail_response(folio)

    @action(detail=True, methods=['post'])
    def payments(self, request, pk=None):
        serializer = RecordPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment = services.record_payment(self.get_object(), request=request, **serializer.validated_data)
        return Response(FolioPaymentSerializer(payment).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path=r'payments/(?P<payment_id>[0-9]+)/void')
    def void_payment(self, request, pk=None, payment_id=None):
        serializer = ReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        folio = self.get_object()
        services.void_payment(get_object_or_404(folio.payments, pk=payment_id),
                              reason=serializer.validated_data['reason'], request=request)
        return self.detail_response(folio)

    @action(detail=True, methods=['post'])
    def refunds(self, request, pk=None):
        serializer = RefundSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment = services.refund(self.get_object(), request=request, **serializer.validated_data)
        return Response(FolioPaymentSerializer(payment).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='transfer-to-account')
    def transfer_to_account(self, request, pk=None):
        serializer = TransferToAccountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invoice = services.transfer_to_account(self.get_object(), serializer.validated_data['account'], request=request)
        return Response(InvoiceSummarySerializer(invoice).data)

    @action(detail=True, methods=['post'])
    def settle(self, request, pk=None):
        invoice = services.settle(self.get_object(), request=request)
        return Response(InvoiceSummarySerializer(invoice).data)


class InvoiceViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = InvoiceSummarySerializer
    permission_classes = [HasCapability('folios.view')]
    queryset = Invoice.objects.select_related('folio')

    def retrieve(self, request, pk=None):
        invoice = self.get_object()
        return Response({**InvoiceSummarySerializer(invoice).data, 'snapshot': invoice.snapshot})

    @action(detail=True, methods=['get'])
    def pdf(self, request, pk=None):
        invoice = self.get_object()
        response = HttpResponse(render_invoice(invoice), content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="{invoice.number}.pdf"'
        return response


class CorporateAccountViewSet(CapabilityPerActionMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                             mixins.CreateModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = CorporateAccountSerializer
    queryset = CorporateAccount.objects.all()
    default_capability = 'accounts.manage'
    capabilities = {'list': 'folios.view', 'retrieve': 'folios.view'}
    http_method_names = ['get', 'post', 'patch', 'head', 'options']

    @action(detail=True, methods=['get', 'post'])
    def payments(self, request, pk=None):
        account = self.get_object()
        if request.method == 'POST':
            serializer = AccountPaymentSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            payment = services.record_account_payment(account, request=request, **serializer.validated_data)
            return Response(AccountPaymentSerializer(payment).data, status=status.HTTP_201_CREATED)
        return Response(AccountPaymentSerializer(account.payments.all(), many=True).data)

    @action(detail=True, methods=['get'])
    def statement(self, request, pk=None):
        """Transferred folios and payments, for sending to the company."""
        account = self.get_object()
        folios = account.folios.filter(status=Folio.Status.TRANSFERRED).select_related('booking', 'guest')
        return Response({
            'account': CorporateAccountSerializer(account).data,
            'folios': FolioSerializer(folios, many=True).data,
            'payments': AccountPaymentSerializer(account.payments.filter(is_void=False), many=True).data,
        })


class TaxRuleViewSet(mixins.ListModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = TaxRuleSerializer
    queryset = TaxRule.objects.all()
    permission_classes = [HasCapability('billing.configure')]
    http_method_names = ['get', 'patch', 'head', 'options']

    def perform_update(self, serializer):
        rule = serializer.save()
        record(AuditLog.Action.BILLING_CONFIGURED, request=self.request, target=rule,
               changes={k: str(v) for k, v in serializer.validated_data.items()})


class ExchangeRateViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    """Rates are append-only: setting a new rate keeps the history used by past payments."""
    serializer_class = ExchangeRateSerializer
    queryset = ExchangeRate.objects.all()
    permission_classes = [HasCapability('billing.configure')]

    def perform_create(self, serializer):
        rate = serializer.save(set_by=self.request.user)
        record(AuditLog.Action.BILLING_CONFIGURED, request=self.request, target=rate,
               changes={'currency': rate.currency, 'rate': str(rate.rate)})
