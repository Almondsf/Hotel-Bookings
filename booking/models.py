from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from hotel.fields import EncryptedTextField


class Guest(models.Model):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(db_index=True)
    phone_number = models.CharField(max_length=15, blank=True, null=True)
    address = models.CharField(max_length=400, blank=True, null=True)
    country = models.CharField(max_length=40, blank=True, null=True)
    nationality = models.CharField(max_length=60, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    company_name = models.CharField(max_length=150, blank=True)
    is_vip = models.BooleanField(default=False)
    # Consent (NDPA): transactional messages are sent unless opted out;
    # marketing only with explicit consent
    sms_opt_out = models.BooleanField(default=False)
    accepts_marketing = models.BooleanField(default=False)
    notes = models.TextField(blank=True, help_text="Preferences and remarks visible to staff.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def has_valid_identification(self):
        today = timezone.localdate()
        return self.identifications.filter(Q(expiry_date__isnull=True) | Q(expiry_date__gte=today)).exists()


class GuestIdentification(models.Model):
    """An identity document seen at check-in. The number is encrypted at rest."""

    class DocumentType(models.TextChoices):
        PASSPORT = 'PASSPORT', 'International Passport'
        NATIONAL_ID = 'NATIONAL_ID', 'National ID (NIN)'
        DRIVERS_LICENCE = 'DRIVERS_LICENCE', "Driver's Licence"
        VOTERS_CARD = 'VOTERS_CARD', "Voter's Card"
        RESIDENCE_PERMIT = 'RESIDENCE_PERMIT', 'Residence Permit'
        OTHER = 'OTHER', 'Other'

    guest = models.ForeignKey(Guest, related_name='identifications', on_delete=models.CASCADE)
    document_type = models.CharField(max_length=20, choices=DocumentType.choices)
    document_number = EncryptedTextField()
    number_last4 = models.CharField(max_length=4, help_text="Last 4 characters, for display")
    issuing_country = models.CharField(max_length=60, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    captured_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    captured_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-captured_at']

    def save(self, *args, **kwargs):
        self.number_last4 = self.document_number[-4:]
        super().save(*args, **kwargs)

    @property
    def masked_number(self):
        return f"•••• {self.number_last4}"

    @property
    def is_expired(self):
        return self.expiry_date is not None and self.expiry_date < timezone.localdate()

    def __str__(self):
        return f"{self.get_document_type_display()} {self.masked_number} ({self.guest})"


class BookingGroup(models.Model):
    """Several room bookings made together (a family, a wedding party, a corporate block)."""
    reference = models.CharField(max_length=20, unique=True)
    booker = models.ForeignKey(Guest, related_name='booking_groups', on_delete=models.PROTECT)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.reference} - {self.booker}"


class BookingQuerySet(models.QuerySet):
    def blocking(self, now=None):
        """Bookings that currently take a room off the market."""
        now = now or timezone.now()
        unexpired_hold = Q(status=Booking.Status.PENDING) & (
            Q(hold_expires_at__isnull=True) | Q(hold_expires_at__gt=now)
        )
        return self.filter(Q(status__in=[Booking.Status.CONFIRMED, Booking.Status.CHECKED_IN]) | unexpired_hold)

    def overlapping(self, check_in_date, check_out_date):
        return self.filter(check_in_date__lt=check_out_date, check_out_date__gt=check_in_date)


class Booking(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        CONFIRMED = 'CONFIRMED', 'Confirmed'
        CHECKED_IN = 'CHECKED_IN', 'Checked In'
        CHECKED_OUT = 'CHECKED_OUT', 'Checked Out'
        CANCELLED = 'CANCELLED', 'Cancelled'
        NO_SHOW = 'NO_SHOW', 'No Show'

    class Source(models.TextChoices):
        WEBSITE = 'WEBSITE', 'Website'
        FRONT_DESK = 'FRONT_DESK', 'Front Desk'
        WALK_IN = 'WALK_IN', 'Walk-in'
        PHONE = 'PHONE', 'Phone'
        EMAIL = 'EMAIL', 'Email'
        CORPORATE = 'CORPORATE', 'Corporate'
        TRAVEL_AGENT = 'TRAVEL_AGENT', 'Travel Agent'
        OTA = 'OTA', 'Online Travel Agency'

    # Allowed status transitions; everything else is rejected by booking.lifecycle.
    TRANSITIONS = {
        Status.PENDING: {Status.CONFIRMED, Status.CANCELLED},
        Status.CONFIRMED: {Status.CHECKED_IN, Status.CANCELLED, Status.NO_SHOW},
        Status.CHECKED_IN: {Status.CHECKED_OUT},
        Status.CHECKED_OUT: set(),
        Status.CANCELLED: set(),
        Status.NO_SHOW: set(),
    }
    MODIFIABLE_STATUSES = [Status.PENDING, Status.CONFIRMED, Status.CHECKED_IN]

    # Bookings are financial records: deleting a guest must not erase them.
    guest = models.ForeignKey(Guest, related_name='bookings', on_delete=models.PROTECT)
    room = models.ForeignKey('rooms.Room', related_name='bookings', on_delete=models.PROTECT)
    number_of_adults = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    number_of_children = models.PositiveIntegerField(default=0)
    special_requests = models.TextField(blank=True, null=True)
    price_per_night = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    total_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    status = models.CharField(max_length=50, choices=Status.choices, default=Status.PENDING)
    confirmation_number = models.CharField(max_length=100, unique=True)
    check_in_date = models.DateField()
    check_out_date = models.DateField()
    group = models.ForeignKey(BookingGroup, null=True, blank=True, related_name='bookings', on_delete=models.PROTECT)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.WEBSITE)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+',
        help_text="Staff member who took the booking; empty for online bookings.",
    )
    # Empty means the hotel's Best Available Rate
    rate_plan = models.ForeignKey('rates.RatePlan', null=True, blank=True, related_name='bookings',
                                  on_delete=models.PROTECT)
    corporate_account = models.ForeignKey('billing.CorporateAccount', null=True, blank=True, related_name='bookings',
                                          on_delete=models.PROTECT)
    # A manager-agreed nightly rate replacing the plan's prices
    nightly_rate_override = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True,
                                                validators=[MinValueValidator(0)])
    rate_override_reason = models.CharField(max_length=255, blank=True)

    # Unpaid online bookings hold their room only until this moment
    hold_expires_at = models.DateTimeField(null=True, blank=True)

    confirmed_at = models.DateTimeField(null=True, blank=True)
    checked_in_at = models.DateTimeField(null=True, blank=True)
    checked_out_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)
    # Charged under the cancellation / no-show policy; collected via the folio
    penalty_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    penalty_waived = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = BookingQuerySet.as_manager()

    @property
    def nights(self) -> int:
        return (self.check_out_date - self.check_in_date).days

    def __str__(self):
        return f"{self.confirmation_number} - {self.guest}"

    def clean(self):
        if self.check_in_date and self.check_out_date and self.check_in_date >= self.check_out_date:
            raise ValidationError("Check-out date must be after check-in date.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['room', 'check_in_date', 'check_out_date']),
            models.Index(fields=['status', 'check_in_date']),
            models.Index(fields=['status', 'check_out_date']),
            models.Index(fields=['status', 'hold_expires_at']),
        ]
        # Enforced by the database too, so bulk updates, raw SQL or future
        # code paths that skip save() can't store invalid bookings.
        constraints = [
            models.CheckConstraint(
                condition=Q(check_out_date__gt=F('check_in_date')),
                name='booking_check_out_after_check_in',
            ),
            models.CheckConstraint(condition=Q(number_of_adults__gte=1), name='booking_at_least_one_adult'),
            models.CheckConstraint(
                condition=Q(total_price__gte=0) & Q(price_per_night__gte=0) & Q(penalty_amount__gte=0),
                name='booking_prices_non_negative',
            ),
        ]


class BookingNight(models.Model):
    """The agreed room rate for one night of a booking."""
    booking = models.ForeignKey(Booking, related_name='nightly_rates', on_delete=models.CASCADE)
    date = models.DateField()
    rate = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])

    class Meta:
        ordering = ['date']
        constraints = [
            models.UniqueConstraint(fields=['booking', 'date'], name='booking_night_unique'),
            models.CheckConstraint(condition=Q(rate__gte=0), name='booking_night_rate_non_negative'),
        ]

    def __str__(self):
        return f"{self.booking_id} {self.date}: {self.rate}"
