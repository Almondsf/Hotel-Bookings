from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q


class RatePlan(models.Model):
    """
    A way of selling rooms: price, inclusions and conditions. "BAR" (best
    available rate) is the reference plan priced from room types' base and
    seasonal prices; other plans derive from it or carry their own prices.
    """

    class MealPlan(models.TextChoices):
        ROOM_ONLY = 'RO', 'Room only'
        BED_AND_BREAKFAST = 'BB', 'Bed & breakfast'
        HALF_BOARD = 'HB', 'Half board'
        FULL_BOARD = 'FB', 'Full board'
        ALL_INCLUSIVE = 'AI', 'All inclusive'

    class Pricing(models.TextChoices):
        DERIVED = 'DERIVED', 'Percentage of BAR'
        FIXED = 'FIXED', 'Own prices per room type'

    BAR_CODE = 'BAR'

    code = models.SlugField(max_length=30, unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    meal_plan = models.CharField(max_length=2, choices=MealPlan.choices, default=MealPlan.ROOM_ONLY)
    pricing = models.CharField(max_length=10, choices=Pricing.choices, default=Pricing.DERIVED)
    adjustment_percent = models.DecimalField(
        max_digits=6, decimal_places=2, default=0,
        validators=[MinValueValidator(-90), MaxValueValidator(500)],
        help_text="For derived plans: -10 = 10% below BAR, 12 = 12% above",
    )
    room_types = models.ManyToManyField('rooms.RoomType', blank=True, related_name='rate_plans',
                                        help_text="Leave empty for all room types")

    # Who can book it
    is_active = models.BooleanField(default=True)
    is_public = models.BooleanField(default=True, help_text="Bookable on the hotel website")
    promo_code = models.CharField(max_length=40, blank=True, help_text="If set, only bookable with this code")
    corporate_account = models.ForeignKey('billing.CorporateAccount', null=True, blank=True, on_delete=models.PROTECT,
                                          related_name='rate_plans', help_text="Negotiated rate for this company only")

    # Conditions
    min_stay = models.PositiveIntegerField(default=1)
    max_stay = models.PositiveIntegerField(null=True, blank=True)
    min_advance_days = models.PositiveIntegerField(default=0, help_text="Book at least this many days before arrival")
    max_advance_days = models.PositiveIntegerField(null=True, blank=True)
    sell_from = models.DateField(null=True, blank=True, help_text="First day the plan can be booked")
    sell_until = models.DateField(null=True, blank=True, help_text="Last day the plan can be booked")
    is_refundable = models.BooleanField(default=True, help_text="Non-refundable: cancelling forfeits the full stay")
    free_cancellation_hours = models.PositiveIntegerField(
        null=True, blank=True, help_text="Overrides the hotel default for this plan",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['code']
        constraints = [
            models.UniqueConstraint(fields=['promo_code'], condition=~Q(promo_code=''), name='rate_plan_unique_promo_code'),
            models.CheckConstraint(condition=Q(max_stay__isnull=True) | Q(max_stay__gte=F('min_stay')),
                                   name='rate_plan_stay_range'),
        ]

    def clean(self):
        if self.promo_code:
            self.promo_code = self.promo_code.strip().upper()
        if self.code == self.BAR_CODE and (self.pricing != self.Pricing.DERIVED or self.adjustment_percent != 0):
            raise ValidationError("BAR is the reference rate; it can't be adjusted.")

    def save(self, *args, **kwargs):
        self.full_clean(exclude=['room_types'])
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} - {self.name}"


class RatePlanPrice(models.Model):
    """Nightly price of a FIXED plan for a room type over a date range (inclusive)."""
    rate_plan = models.ForeignKey(RatePlan, related_name='prices', on_delete=models.CASCADE)
    room_type = models.ForeignKey('rooms.RoomType', related_name='+', on_delete=models.CASCADE)
    start_date = models.DateField()
    end_date = models.DateField()
    price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])

    class Meta:
        ordering = ['start_date']
        indexes = [models.Index(fields=['rate_plan', 'room_type', 'start_date'])]
        constraints = [models.CheckConstraint(condition=Q(end_date__gte=F('start_date')), name='rate_price_range')]


class RateRestriction(models.Model):
    """
    Selling restrictions over a date range (inclusive). Empty rate plan /
    room type means "all". Applied to website and channel bookings; staff can
    still book (they see the reason).
    """
    rate_plan = models.ForeignKey(RatePlan, null=True, blank=True, related_name='restrictions', on_delete=models.CASCADE)
    room_type = models.ForeignKey('rooms.RoomType', null=True, blank=True, related_name='+', on_delete=models.CASCADE)
    start_date = models.DateField()
    end_date = models.DateField()
    stop_sell = models.BooleanField(default=False)
    closed_to_arrival = models.BooleanField(default=False)
    closed_to_departure = models.BooleanField(default=False)
    min_stay = models.PositiveIntegerField(null=True, blank=True, help_text="Minimum stay for arrivals in this range")
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['start_date']
        indexes = [models.Index(fields=['start_date', 'end_date'])]
        constraints = [models.CheckConstraint(condition=Q(end_date__gte=F('start_date')), name='rate_restriction_range')]
