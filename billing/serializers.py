from decimal import Decimal

from rest_framework import serializers

from .models import (
    AccountPayment,
    Charge,
    ChargeCategory,
    CorporateAccount,
    ExchangeRate,
    Folio,
    FolioPayment,
    Invoice,
    PaymentMethod,
    TaxRule,
)


class ChargeSerializer(serializers.ModelSerializer):
    posted_by = serializers.EmailField(source='posted_by.email', default=None, read_only=True)
    transferred_from = serializers.CharField(source='transferred_from.number', default=None, read_only=True)

    class Meta:
        model = Charge
        fields = [
            'id', 'category', 'description', 'quantity', 'unit_price', 'net_amount', 'tax_amount', 'total_amount',
            'tax_lines', 'service_date', 'source', 'transferred_from', 'posted_by', 'posted_at',
            'is_void', 'void_reason', 'voided_at',
        ]
        read_only_fields = fields


class FolioPaymentSerializer(serializers.ModelSerializer):
    received_by = serializers.EmailField(source='received_by.email', default=None, read_only=True)
    online = serializers.SerializerMethodField(help_text="Gateway transaction behind an online payment, for card refunds")

    class Meta:
        model = FolioPayment
        fields = [
            'id', 'kind', 'method', 'amount', 'tendered_currency', 'tendered_amount', 'exchange_rate',
            'reference', 'notes', 'received_by', 'received_at', 'service_date', 'is_void', 'void_reason', 'online',
        ]
        read_only_fields = fields

    def get_online(self, payment):
        txn = getattr(payment, 'transaction', None)  # reverse one-to-one; absent for desk payments
        if txn is None:
            return None
        return {'transaction_id': txn.pk, 'gateway': txn.gateway, 'status': txn.status,
                'refundable': str(txn.amount - txn.refunded_amount)}


class InvoiceSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Invoice
        fields = ['id', 'number', 'issued_at', 'total']
        read_only_fields = fields


class FolioSerializer(serializers.ModelSerializer):
    number = serializers.CharField(read_only=True)
    display_name = serializers.CharField(read_only=True)
    confirmation_number = serializers.CharField(source='booking.confirmation_number', default=None, read_only=True)
    account = serializers.CharField(source='account.code', default=None, read_only=True)
    charges_total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    payments_total = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    balance = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = Folio
        fields = [
            'id', 'number', 'display_name', 'booking', 'confirmation_number', 'guest', 'account', 'status',
            'currency', 'charges_total', 'payments_total', 'balance', 'opened_at', 'closed_at',
        ]
        read_only_fields = fields


class FolioDetailSerializer(FolioSerializer):
    charges = ChargeSerializer(many=True, read_only=True)
    payments = FolioPaymentSerializer(many=True, read_only=True)
    invoices = InvoiceSummarySerializer(many=True, read_only=True)

    class Meta(FolioSerializer.Meta):
        fields = FolioSerializer.Meta.fields + ['charges', 'payments', 'invoices']
        read_only_fields = fields


class NonGuestFolioSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)


class PostChargeSerializer(serializers.Serializer):
    # Room nights are posted automatically; PENALTY by the cancellation flow
    category = serializers.ChoiceField(choices=[c for c in ChargeCategory.choices
                                                if c[0] not in (ChargeCategory.ROOM, ChargeCategory.PENALTY)])
    description = serializers.CharField(max_length=255)
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2, default=1, min_value=Decimal('0.01'))


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255)


class TransferChargeSerializer(serializers.Serializer):
    to_folio = serializers.PrimaryKeyRelatedField(queryset=Folio.objects.all())
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')


# Gateway payments are recorded by the gateway integration, not typed in
STAFF_PAYMENT_METHODS = [PaymentMethod.CASH, PaymentMethod.CARD_TERMINAL, PaymentMethod.BANK_TRANSFER]


class RecordPaymentSerializer(serializers.Serializer):
    method = serializers.ChoiceField(choices=[(m.value, m.label) for m in STAFF_PAYMENT_METHODS])
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, required=False)
    currency = serializers.CharField(max_length=3, required=False, allow_blank=True)
    tendered_amount = serializers.DecimalField(max_digits=14, decimal_places=2, required=False)
    reference = serializers.CharField(max_length=150, required=False, allow_blank=True, default='')
    notes = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')

    def validate(self, data):
        if data.get('method') in (PaymentMethod.CARD_TERMINAL, PaymentMethod.BANK_TRANSFER) and not data['reference']:
            raise serializers.ValidationError({"reference": "Card and transfer payments need a reference."})
        return data


class RefundSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    method = serializers.ChoiceField(choices=[(m.value, m.label) for m in STAFF_PAYMENT_METHODS])
    reference = serializers.CharField(max_length=150, required=False, allow_blank=True, default='')
    reason = serializers.CharField(max_length=255)


class TransferToAccountSerializer(serializers.Serializer):
    account = serializers.PrimaryKeyRelatedField(queryset=CorporateAccount.objects.all())


class CorporateAccountSerializer(serializers.ModelSerializer):
    balance = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = CorporateAccount
        fields = ['id', 'code', 'name', 'contact_name', 'email', 'phone', 'address', 'tax_id', 'credit_limit',
                  'payment_terms_days', 'is_active', 'notes', 'balance', 'created_at']
        read_only_fields = ['id', 'balance', 'created_at']


class AccountPaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccountPayment
        fields = ['id', 'amount', 'method', 'reference', 'received_at', 'is_void']
        read_only_fields = ['id', 'received_at', 'is_void']


class TaxRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaxRule
        fields = ['id', 'code', 'name', 'rate', 'categories', 'is_active', 'sort_order', 'updated_at']
        read_only_fields = ['id', 'updated_at']

    def validate_categories(self, value):
        valid = set(ChargeCategory.values)
        unknown = [c for c in value if c not in valid]
        if unknown:
            raise serializers.ValidationError(f"Unknown categories: {', '.join(unknown)}")
        return value


class ExchangeRateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExchangeRate
        fields = ['id', 'currency', 'rate', 'effective_from']
        read_only_fields = ['id', 'effective_from']

    def validate_currency(self, value):
        value = value.upper()
        if len(value) != 3 or not value.isalpha():
            raise serializers.ValidationError("Use a 3-letter ISO currency code, e.g. USD.")
        return value
