from django.conf import settings
from django.db import models
from django.db.models import Q


class MaintenanceTicket(models.Model):
    class Category(models.TextChoices):
        PLUMBING = 'PLUMBING', 'Plumbing'
        ELECTRICAL = 'ELECTRICAL', 'Electrical'
        HVAC = 'HVAC', 'Air conditioning'
        FURNITURE = 'FURNITURE', 'Furniture & fittings'
        APPLIANCE = 'APPLIANCE', 'Appliance'
        IT = 'IT', 'TV / Wi-Fi / phone'
        GENERATOR = 'GENERATOR', 'Power / generator'
        OTHER = 'OTHER', 'Other'

    class Priority(models.TextChoices):
        LOW = 'LOW', 'Low'
        MEDIUM = 'MEDIUM', 'Medium'
        HIGH = 'HIGH', 'High'
        URGENT = 'URGENT', 'Urgent'

    class Status(models.TextChoices):
        OPEN = 'OPEN', 'Open'
        IN_PROGRESS = 'IN_PROGRESS', 'In progress'
        ON_HOLD = 'ON_HOLD', 'On hold (parts / vendor)'
        RESOLVED = 'RESOLVED', 'Resolved'

    room = models.ForeignKey('rooms.Room', null=True, blank=True, related_name='maintenance_tickets',
                             on_delete=models.PROTECT)
    location = models.CharField(max_length=150, blank=True, help_text="For public areas, e.g. 'Lobby restroom'")
    title = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.OTHER)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    reported_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name='maintenance_tickets')
    # Taking the room off sale while it's repaired
    out_of_order = models.ForeignKey('rooms.RoomAvailabilityOverride', null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name='+')
    resolution_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name='+')

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['status', 'priority'])]
        constraints = [
            models.CheckConstraint(condition=Q(room__isnull=False) | ~Q(location=''),
                                   name='maintenance_ticket_has_place'),
        ]

    @property
    def number(self):
        return f"MT-{self.pk:05d}"

    def __str__(self):
        where = f"Room {self.room.room_number}" if self.room_id else self.location
        return f"{self.number} {self.title} ({where})"
