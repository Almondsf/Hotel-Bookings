from django.db import models
from django.db.models import Q


class PaymentTransaction(models.Model):
    """One attempt to collect money through an online gateway."""

    class Gateway(models.TextChoices):
        PAYSTACK = 'PAYSTACK', 'Paystack'
        FLUTTERWAVE = 'FLUTTERWAVE', 'Flutterwave'
        LEGACY = 'LEGACY', 'Legacy (pre-gateway)'

    class Purpose(models.TextChoices):
        BOOKING_PREPAYMENT = 'BOOKING_PREPAYMENT', 'Online booking prepayment'
        FOLIO_SETTLEMENT = 'FOLIO_SETTLEMENT', 'Payment link for a folio'

    class Status(models.TextChoices):
        INITIALIZED = 'INITIALIZED', 'Awaiting payment'
        SUCCEEDED = 'SUCCEEDED', 'Succeeded'
        FAILED = 'FAILED', 'Failed'
        REFUNDED = 'REFUNDED', 'Refunded'
        NEEDS_REVIEW = 'NEEDS_REVIEW', 'Needs review'

    reference = models.CharField(max_length=40, unique=True)
    gateway = models.CharField(max_length=20, choices=Gateway.choices)
    purpose = models.CharField(max_length=30, choices=Purpose.choices)
    booking = models.ForeignKey('booking.Booking', null=True, blank=True, related_name='payment_transactions',
                                on_delete=models.PROTECT)
    folio = models.ForeignKey('billing.Folio', related_name='payment_transactions', on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3)
    email = models.EmailField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.INITIALIZED)
    authorization_url = models.URLField(max_length=500, blank=True)
    gateway_transaction_id = models.CharField(max_length=100, blank=True)
    # Provider responses with card/customer details stripped
    gateway_response = models.JSONField(default=dict, blank=True)
    folio_payment = models.OneToOneField('billing.FolioPayment', null=True, blank=True, related_name='transaction',
                                         on_delete=models.PROTECT)
    refunded_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    review_reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    settled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['status', 'created_at'])]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name='payment_txn_amount_positive'),
            models.CheckConstraint(condition=Q(refunded_amount__gte=0) & Q(refunded_amount__lte=models.F('amount')),
                                   name='payment_txn_refund_within_amount'),
        ]

    def __str__(self):
        return f"{self.reference} {self.gateway} {self.amount} {self.currency} ({self.status})"
