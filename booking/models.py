from django.db import models

# Create your models here.
class Guest(models.Model):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField()
    phone_number = models.CharField(max_length=15, blank=True, null=True)
    address = models.CharField(max_length=400, blank=True, null=True)
    country = models.CharField(max_length=40, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.first_name} {self.last_name}"

class Booking(models.Model):
    
    STATUS_CHOICES = [
    ('PENDING', 'Pending'),
    ('CONFIRMED', 'Confirmed'),
    ('CHECKED_IN', 'Checked In'),
    ('CHECKED_OUT', 'Checked Out'),
    ('CANCELLED', 'Cancelled'),
    ('NO_SHOW', 'No Show'),
]
    
    guest = models.ForeignKey(Guest, related_name='bookings', on_delete=models.CASCADE)
    room = models.ForeignKey('rooms.Room', related_name='bookings', on_delete=models.PROTECT)
    number_of_adults = models.PositiveIntegerField()
    number_of_children = models.PositiveIntegerField()
    special_requests = models.TextField(blank=True, null=True)
    price_per_night = models.DecimalField(max_digits=10, decimal_places=2)
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=50, choices = STATUS_CHOICES, default='PENDING')
    confirmation_number = models.CharField(max_length=100, unique=True)
    check_in_date = models.DateField()
    check_out_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Booking for {self.guest} - Room {self.room.room_number}"
    
    def clean(self):
        from django.core.exceptions import ValidationError
        if self.check_in_date >= self.check_out_date:
            raise ValidationError("Check-out date must be after check-in date.")
    
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
        
    class Meta:
        ordering = ['-created_at']
        
        
class Payment(models.Model):
    PAYMENT_METHOD_CHOICES = [
        ('CREDIT_CARD', 'Credit Card'),
        ('DEBIT_CARD', 'Debit Card'),
        ('PAYPAL', 'PayPal'),
        ('BANK_TRANSFER', 'Bank Transfer'),
        ('CASH', 'Cash'),
    ]
    
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
        ('REFUNDED', 'Refunded'),
    ]
    
    booking = models.ForeignKey(Booking, related_name='payments', on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=50, choices=PAYMENT_METHOD_CHOICES)
    transaction_id = models.CharField(max_length=255, blank=True, null=True, unique=True)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='PENDING')
    payment_gateway = models.CharField(max_length=50, blank=True, help_text="e.g., Stripe, PayPal")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    
    def __str__(self):
        return f"Payment {self.id} for Booking {self.booking.confirmation_number} - {self.status}"
    
    class Meta:
        ordering = ['-created_at']