from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Case, DecimalField, F, OuterRef, Q, Subquery, Sum, Value, When
from django.db.models.functions import Coalesce

from hotel.money import ZERO, money


MONEY = DecimalField(max_digits=14, decimal_places=2)


def _subtotal(queryset, expression, group_by):
    """A correlated subquery summing `expression` over `queryset` (0 when there are no rows)."""
    total = queryset.values(group_by).annotate(total=Sum(expression)).values('total')
    return Coalesce(Subquery(total, output_field=MONEY), Value(ZERO), output_field=MONEY)


# Payments count for the guest, refunds against
_SIGNED_PAYMENT = Case(When(kind='REFUND', then=-F('amount')), default=F('amount'), output_field=MONEY)


class FolioQuerySet(models.QuerySet):
    def with_totals(self):
        """
        Charges, payments and balance computed in the same query, so listing
        folios doesn't run two aggregate queries per folio. Only for reading:
        an annotated folio's totals don't follow later changes.
        """
        return self.annotate(
            charges_sum=_subtotal(Charge.objects.filter(folio=OuterRef('pk'), is_void=False), 'total_amount', 'folio'),
            payments_sum=_subtotal(FolioPayment.objects.filter(folio=OuterRef('pk'), is_void=False), _SIGNED_PAYMENT, 'folio'),
            refunds_sum=_subtotal(FolioPayment.objects.filter(folio=OuterRef('pk'), is_void=False, kind='REFUND'),
                                  'amount', 'folio'),
        )


class CorporateAccountQuerySet(models.QuerySet):
    def with_balance(self):
        """Each account's balance in the same query (see CorporateAccount.balance)."""
        transferred = {'folio__account': OuterRef('pk'), 'folio__status': 'TRANSFERRED', 'is_void': False}
        return self.annotate(balance_sum=(
            _subtotal(Charge.objects.filter(**transferred), 'total_amount', 'folio__account')
            - _subtotal(FolioPayment.objects.filter(**transferred), _SIGNED_PAYMENT, 'folio__account')
            - _subtotal(AccountPayment.objects.filter(account=OuterRef('pk'), is_void=False), 'amount', 'account')
        ))


class ChargeCategory(models.TextChoices):
    ROOM = 'ROOM', 'Room'
    FOOD = 'FOOD', 'Food'
    BEVERAGE = 'BEVERAGE', 'Beverage'
    MINIBAR = 'MINIBAR', 'Minibar'
    LAUNDRY = 'LAUNDRY', 'Laundry'
    SPA = 'SPA', 'Spa & Wellness'
    TRANSPORT = 'TRANSPORT', 'Transport'
    TELEPHONE = 'TELEPHONE', 'Telephone & Internet'
    MISC = 'MISC', 'Miscellaneous'
    PENALTY = 'PENALTY', 'Cancellation / No-show'
    ALLOWANCE = 'ALLOWANCE', 'Allowance / Discount'


class PaymentMethod(models.TextChoices):
    CASH = 'CASH', 'Cash'
    CARD_TERMINAL = 'CARD_TERMINAL', 'Card (POS terminal)'
    BANK_TRANSFER = 'BANK_TRANSFER', 'Bank Transfer'
    PAYSTACK = 'PAYSTACK', 'Paystack'
    FLUTTERWAVE = 'FLUTTERWAVE', 'Flutterwave'
    ONLINE_OTHER = 'ONLINE_OTHER', 'Other online'


class TaxRule(models.Model):
    """
    A tax or levy applied to charges in the given categories, e.g. VAT 7.5%.
    Rates are a fraction (0.075 = 7.5%) and are applied to the net amount
    (not compounded). Changing a rule affects only future charges: every
    charge keeps a copy of the taxes applied to it.
    """
    code = models.SlugField(max_length=30, unique=True)
    name = models.CharField(max_length=100)
    rate = models.DecimalField(max_digits=6, decimal_places=4,
                               validators=[MinValueValidator(0), MaxValueValidator(1)])
    categories = models.JSONField(default=list, help_text="Charge categories this applies to")
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'code']

    def __str__(self):
        return f"{self.name} ({self.rate * 100:.2f}%)"


class ExchangeRate(models.Model):
    """Value of one unit of `currency` in the hotel currency (e.g. 1 USD = 1550 NGN)."""
    currency = models.CharField(max_length=3)
    rate = models.DecimalField(max_digits=14, decimal_places=4, validators=[MinValueValidator(0)])
    effective_from = models.DateTimeField(auto_now_add=True)
    set_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        ordering = ['-effective_from', '-id']
        indexes = [models.Index(fields=['currency', 'effective_from'])]
        constraints = [models.CheckConstraint(condition=Q(rate__gt=0), name='exchange_rate_positive')]

    def __str__(self):
        return f"1 {self.currency} = {self.rate} {settings.HOTEL_CURRENCY}"


class CorporateAccount(models.Model):
    """A company billed on credit (city ledger)."""
    code = models.SlugField(max_length=30, unique=True)
    name = models.CharField(max_length=200)
    contact_name = models.CharField(max_length=150, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    address = models.TextField(blank=True)
    tax_id = models.CharField(max_length=50, blank=True, help_text="Company TIN, printed on invoices")
    credit_limit = models.DecimalField(max_digits=14, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    payment_terms_days = models.PositiveIntegerField(default=30)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    objects = CorporateAccountQuerySet.as_manager()

    @property
    def balance(self):
        """Amount the company owes: transferred folio balances minus its payments."""
        if hasattr(self, 'balance_sum'):  # from CorporateAccount.objects.with_balance()
            return money(self.balance_sum)
        transferred = Folio.objects.filter(account=self, status=Folio.Status.TRANSFERRED)
        charges = Charge.objects.filter(folio__in=transferred, is_void=False).aggregate(t=Sum('total_amount'))['t'] or ZERO
        paid = FolioPayment.objects.filter(folio__in=transferred, is_void=False).aggregate(
            t=Sum(_SIGNED_PAYMENT))['t'] or ZERO
        account_paid = self.payments.filter(is_void=False).aggregate(total=Sum('amount'))['total'] or ZERO
        return money(charges - paid - account_paid)


class Folio(models.Model):
    """The running bill of a stay (or of a non-staying customer)."""

    class Status(models.TextChoices):
        OPEN = 'OPEN', 'Open'
        SETTLED = 'SETTLED', 'Settled'
        TRANSFERRED = 'TRANSFERRED', 'Transferred to city ledger'

    booking = models.OneToOneField('booking.Booking', null=True, blank=True, related_name='folio',
                                   on_delete=models.PROTECT)
    guest = models.ForeignKey('booking.Guest', null=True, blank=True, related_name='folios', on_delete=models.PROTECT)
    name = models.CharField(max_length=200, blank=True, help_text="Who the bill is for, if not a booking's guest")
    account = models.ForeignKey(CorporateAccount, null=True, blank=True, related_name='folios',
                                on_delete=models.PROTECT)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    currency = models.CharField(max_length=3, default='NGN')
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    transferred_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-opened_at']
        indexes = [models.Index(fields=['status', 'opened_at'])]

    def __str__(self):
        return f"{self.number} - {self.display_name}"

    @property
    def number(self):
        return f"F{self.pk:07d}"

    @property
    def display_name(self):
        if self.name:
            return self.name
        return str(self.guest) if self.guest_id else ''

    objects = FolioQuerySet.as_manager()

    @property
    def charges_total(self):
        if hasattr(self, 'charges_sum'):  # from Folio.objects.with_totals()
            return money(self.charges_sum)
        return money(self.charges.filter(is_void=False).aggregate(total=Sum('total_amount'))['total'] or ZERO)

    @property
    def payments_total(self):
        if hasattr(self, 'payments_sum'):
            return money(self.payments_sum)
        return money(self.payments.filter(is_void=False).aggregate(total=Sum(_SIGNED_PAYMENT))['total'] or ZERO)

    @property
    def refunds_total(self):
        """Money given back to the guest from this folio."""
        if hasattr(self, 'refunds_sum'):
            return money(self.refunds_sum)
        return money(self.payments.filter(is_void=False, kind='REFUND').aggregate(total=Sum('amount'))['total'] or ZERO)

    @property
    def balance(self):
        """Positive: the guest owes the hotel. Negative: the hotel owes the guest (credit)."""
        return self.charges_total - self.payments_total


class Charge(models.Model):
    folio = models.ForeignKey(Folio, related_name='charges', on_delete=models.PROTECT)
    category = models.CharField(max_length=20, choices=ChargeCategory.choices)
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    net_amount = models.DecimalField(max_digits=14, decimal_places=2)
    tax_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2)
    # Snapshot of the taxes applied: [{"code", "name", "rate", "amount"}]
    tax_lines = models.JSONField(default=list)
    service_date = models.DateField(help_text="Business date the charge belongs to")
    # Set for nightly room charges so a night can only ever be posted once
    booking_night = models.ForeignKey('booking.BookingNight', null=True, blank=True, related_name='charges',
                                      on_delete=models.PROTECT)
    source = models.CharField(max_length=100, blank=True, help_text="Originating record, e.g. pos.order:12")
    transferred_from = models.ForeignKey(Folio, null=True, blank=True, related_name='+', on_delete=models.PROTECT)
    posted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                  related_name='+')
    posted_at = models.DateTimeField(auto_now_add=True)
    is_void = models.BooleanField(default=False)
    void_reason = models.CharField(max_length=255, blank=True)
    voided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                  related_name='+')
    voided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['service_date', 'posted_at', 'id']
        indexes = [models.Index(fields=['service_date', 'category'])]
        constraints = [
            models.UniqueConstraint(fields=['booking_night'], condition=Q(is_void=False),
                                    name='charge_one_live_posting_per_night'),
            # Only allowances may be negative
            models.CheckConstraint(
                condition=Q(category='ALLOWANCE') | Q(net_amount__gte=0),
                name='charge_non_negative_unless_allowance',
            ),
        ]

    def __str__(self):
        return f"{self.description} {self.total_amount}"


class FolioPayment(models.Model):
    class Kind(models.TextChoices):
        PAYMENT = 'PAYMENT', 'Payment'
        REFUND = 'REFUND', 'Refund'

    folio = models.ForeignKey(Folio, related_name='payments', on_delete=models.PROTECT)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.PAYMENT)
    method = models.CharField(max_length=20, choices=PaymentMethod.choices)
    # In the folio currency
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0)])
    # What was physically handed over, when paid in another currency
    tendered_currency = models.CharField(max_length=3, blank=True)
    tendered_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    exchange_rate = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    reference = models.CharField(max_length=150, blank=True, help_text="Receipt, transfer or gateway reference")
    notes = models.CharField(max_length=255, blank=True)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name='+')
    received_at = models.DateTimeField(auto_now_add=True)
    service_date = models.DateField()
    is_void = models.BooleanField(default=False)
    void_reason = models.CharField(max_length=255, blank=True)
    voided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                  related_name='+')
    voided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['received_at', 'id']
        indexes = [models.Index(fields=['service_date', 'method'])]
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name='folio_payment_positive')]

    def __str__(self):
        return f"{self.get_kind_display()} {self.amount} ({self.get_method_display()})"


class AccountPayment(models.Model):
    """A company settling its city-ledger balance."""
    account = models.ForeignKey(CorporateAccount, related_name='payments', on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0)])
    method = models.CharField(max_length=20, choices=PaymentMethod.choices)
    reference = models.CharField(max_length=150, blank=True)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    received_at = models.DateTimeField(auto_now_add=True)
    is_void = models.BooleanField(default=False)
    void_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-received_at']
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name='account_payment_positive')]


class InvoiceSequence(models.Model):
    """Gapless invoice counter per year (tax authorities expect unbroken numbering)."""
    year = models.PositiveIntegerField(unique=True)
    last_number = models.PositiveIntegerField(default=0)


class Invoice(models.Model):
    """An issued invoice: an immutable snapshot of a folio at closing."""
    number = models.CharField(max_length=30, unique=True)
    folio = models.ForeignKey(Folio, related_name='invoices', on_delete=models.PROTECT)
    issued_at = models.DateTimeField(auto_now_add=True)
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    snapshot = models.JSONField()
    total = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        ordering = ['-issued_at']

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise RuntimeError("Issued invoices are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("Issued invoices cannot be deleted.")

    def __str__(self):
        return self.number
