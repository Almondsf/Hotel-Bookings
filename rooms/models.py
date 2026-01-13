from django.db import models
from django.core.exceptions import ValidationError
from autoslug import AutoSlugField
# Create your models here.
class Amenity(models.Model):
    """Amenity Model Definition"""

    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    is_premium = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name
    
    class Meta:
        verbose_name_plural = "Amenities"
        
class RoomType(models.Model):
    """RoomType Model Definition"""
    BED_TYPE_CHOICES = [
    ('KING', 'King'),
    ('QUEEN', 'Queen'),
    ('DOUBLE', 'Double'),
    ('TWIN', 'Twin'),
    ('SINGLE', 'Single'),
    ('SOFA_BED', 'Sofa Bed'),
    ('FUTON', 'Futon'),
    ('BUNK_BED', 'Bunk Bed'),]

    name = models.CharField(max_length=150, unique=True)
    description = models.TextField()
    amenities = models.ManyToManyField('Amenity', related_name='room_types')
    base_price = models.DecimalField(max_digits=10, decimal_places=2)
    max_adults = models.PositiveIntegerField()
    max_children = models.PositiveIntegerField()
    slug = AutoSlugField(populate_from='name', unique=True)
    bed_type = models.CharField(choices=BED_TYPE_CHOICES, max_length=50)
    bed_count = models.PositiveIntegerField()
    size = models.PositiveIntegerField(help_text="Size in square feet")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    

    def __str__(self):
        return self.name
    
    class Meta:
        ordering = ['name', 'base_price']
        indexes = [models.Index(fields=['base_price'])]

class Room(models.Model):   
    """Room Model Definition"""
    STATUS_CHOICES = [
    ('AVAILABLE', 'Available'),
    ('OCCUPIED', 'Occupied'),
    ('MAINTENANCE', 'Under Maintenance'),
    ('OUT_OF_SERVICE', 'Out of Service'),]

    room_number = models.CharField(max_length=10, unique=True)
    room_type = models.ForeignKey('RoomType', related_name='rooms', on_delete=models.PROTECT)
    floor_number = models.PositiveIntegerField()
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='AVAILABLE')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Room {self.room_number} - {self.room_type.name}"
    
    class Meta:
        ordering = ['room_number']
        indexes = [models.Index(fields=['status', 'room_type'])]
    
class RoomImage(models.Model):
    """RoomImage Model Definition"""

    room_type = models.ForeignKey('RoomType', related_name='images', on_delete=models.CASCADE)
    image_url = models.URLField()
    description = models.CharField(max_length=255, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    is_primary = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"Image for {self.room_type.name} - {self.description or 'No Description'}"
    class Meta:
        ordering = ['-is_primary', 'order']

class RoomPricing(models.Model):
    """RoomPricing Model Definition"""

    room_type = models.ForeignKey('RoomType', related_name='pricings', on_delete=models.CASCADE)
    price_per_night = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.CharField(max_length=255, blank=True)
    start_date = models.DateField()
    end_date = models.DateField()

    
    def clean(self):
        if self.end_date <= self.start_date:
            raise ValidationError("End date must be after start date.")
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.room_type.name} - {self.start_date} to {self.end_date} Pricing"
    
    class Meta:
        ordering = ['start_date']
    

class RoomAvailabilityOverride(models.Model):
    """RoomAvailabilityOverride Model Definition"""
    
    REASON_CHOICES = [
    ('MAINTENANCE', 'Maintenance'),
    ('RENOVATION', 'Renovation'),
    ('VIP_HOLD', 'VIP Hold'),
    ('BLOCKED', 'Blocked'),
    ]
    
    room = models.ForeignKey('Room', related_name='availability_overrides', on_delete=models.CASCADE)
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.CharField(choices=REASON_CHOICES, max_length=50)
    note = models.TextField(blank=True)
    
    def clean(self):
        if self.end_date <= self.start_date:
            raise ValidationError("End date must be after start date.")
        
    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
        
    def __str__(self):
        return f"Availability Override for {self.room.room_number} on {self.start_date} to {self.end_date}"
        
    class Meta:
        ordering = ['start_date']
        verbose_name_plural = "Room Availability Overrides"
    
