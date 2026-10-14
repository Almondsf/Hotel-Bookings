from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from billing.models import ChargeCategory


class Outlet(models.Model):
    """A selling point: restaurant, bar, room service, laundry, spa."""

    class Kind(models.TextChoices):
        RESTAURANT = 'RESTAURANT', 'Restaurant'
        BAR = 'BAR', 'Bar'
        ROOM_SERVICE = 'ROOM_SERVICE', 'Room service'
        LAUNDRY = 'LAUNDRY', 'Laundry'
        SPA = 'SPA', 'Spa'
        OTHER = 'OTHER', 'Other'

    code = models.SlugField(max_length=30, unique=True)
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    # Staff roles that may sell here (managers always can)
    allowed_roles = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def is_open_to(self, user):
        from authentication.permissions import is_administrator
        return is_administrator(user) or user.role == 'manager' or user.role in self.allowed_roles


class Product(models.Model):
    outlet = models.ForeignKey(Outlet, related_name='products', on_delete=models.PROTECT)
    name = models.CharField(max_length=120)
    section = models.CharField(max_length=60, blank=True, help_text="Menu section, e.g. 'Mains', 'Cocktails'")
    price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)],
                                help_text="Before tax")
    charge_category = models.CharField(max_length=20, choices=ChargeCategory.choices, default=ChargeCategory.FOOD)
    is_available = models.BooleanField(default=True)
    track_stock = models.BooleanField(default=False)
    stock_quantity = models.IntegerField(default=0)
    low_stock_threshold = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['section', 'name']
        constraints = [
            models.UniqueConstraint(fields=['outlet', 'name'], name='pos_product_unique_per_outlet'),
            models.CheckConstraint(condition=~Q(charge_category__in=['ROOM', 'PENALTY', 'ALLOWANCE']),
                                   name='pos_product_sellable_category'),
        ]

    def __str__(self):
        return f"{self.name} ({self.outlet.code})"

    @property
    def is_low_on_stock(self):
        return self.track_stock and self.stock_quantity <= self.low_stock_threshold


class Order(models.Model):
    class Status(models.TextChoices):
        OPEN = 'OPEN', 'Open'
        SETTLED = 'SETTLED', 'Settled'
        VOID = 'VOID', 'Void'

    outlet = models.ForeignKey(Outlet, related_name='orders', on_delete=models.PROTECT)
    table_label = models.CharField(max_length=30, blank=True, help_text="Table, bar seat or room for delivery")
    covers = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    notes = models.CharField(max_length=255, blank=True)
    opened_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    opened_at = models.DateTimeField(auto_now_add=True)
    # Where the sale was billed: the guest's folio (room charge) or a one-off folio (paid now)
    folio = models.ForeignKey('billing.Folio', null=True, blank=True, related_name='pos_orders', on_delete=models.PROTECT)
    booking = models.ForeignKey('booking.Booking', null=True, blank=True, related_name='pos_orders',
                                on_delete=models.PROTECT)
    settled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+')
    settled_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-opened_at']
        indexes = [models.Index(fields=['outlet', 'status'])]

    @property
    def number(self):
        return f"ORD-{self.pk:06d}"

    def __str__(self):
        return f"{self.number} {self.outlet.code} {self.table_label}"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name='items', on_delete=models.CASCADE)
    product = models.ForeignKey(Product, related_name='+', on_delete=models.PROTECT)
    # Snapshots, so later menu changes don't alter past orders
    name = models.CharField(max_length=120)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    charge_category = models.CharField(max_length=20, choices=ChargeCategory.choices)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    notes = models.CharField(max_length=255, blank=True, help_text="e.g. 'no pepper'")

    class Meta:
        ordering = ['id']
        constraints = [models.CheckConstraint(condition=Q(quantity__gte=1), name='pos_item_positive_quantity')]
