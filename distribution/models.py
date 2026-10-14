from django.db import models

from hotel.fields import EncryptedTextField


class ChannelConnection(models.Model):
    """The hotel's link to a channel manager, which in turn connects the OTAs."""

    class Provider(models.TextChoices):
        CHANNEX = 'CHANNEX', 'Channex'

    provider = models.CharField(max_length=20, choices=Provider.choices, unique=True)
    is_active = models.BooleanField(default=False)
    api_key = EncryptedTextField(blank=True)
    property_id = models.CharField(max_length=100, blank=True, help_text="The hotel's id at the provider")
    # Shared secret the provider sends with webhooks
    webhook_secret = EncryptedTextField(blank=True)
    sync_days = models.PositiveIntegerField(default=365, help_text="How far ahead to publish availability and rates")
    last_full_sync_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=500, blank=True)

    def __str__(self):
        return f"{self.get_provider_display()} ({'active' if self.is_active else 'inactive'})"


class RoomTypeMapping(models.Model):
    connection = models.ForeignKey(ChannelConnection, related_name='room_types', on_delete=models.CASCADE)
    room_type = models.ForeignKey('rooms.RoomType', related_name='+', on_delete=models.CASCADE)
    external_id = models.CharField(max_length=100)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['connection', 'room_type'], name='channel_room_type_once'),
            models.UniqueConstraint(fields=['connection', 'external_id'], name='channel_room_type_external_once'),
        ]


class RatePlanMapping(models.Model):
    """One external rate plan = one of our rate plans sold for one room type."""
    connection = models.ForeignKey(ChannelConnection, related_name='rate_plans', on_delete=models.CASCADE)
    room_type = models.ForeignKey('rooms.RoomType', related_name='+', on_delete=models.CASCADE)
    rate_plan = models.ForeignKey('rates.RatePlan', related_name='+', on_delete=models.CASCADE)
    external_id = models.CharField(max_length=100)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['connection', 'external_id'], name='channel_rate_plan_external_once'),
        ]


class ChannelBooking(models.Model):
    """
    An OTA reservation (and every later revision of it) as received. Links to
    our booking once one could be created; otherwise it waits for staff.
    """

    class Status(models.TextChoices):
        IMPORTED = 'IMPORTED', 'Imported'
        CANCELLED = 'CANCELLED', 'Cancelled'
        NEEDS_ATTENTION = 'NEEDS_ATTENTION', 'Needs attention'

    connection = models.ForeignKey(ChannelConnection, related_name='bookings', on_delete=models.PROTECT)
    external_id = models.CharField(max_length=100, help_text="The provider's booking id")
    ota_name = models.CharField(max_length=60, blank=True)
    ota_reference = models.CharField(max_length=100, blank=True, help_text="e.g. the Booking.com reservation number")
    last_revision_id = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=Status.choices)
    problem = models.CharField(max_length=500, blank=True)
    payload = models.JSONField(default=dict)
    bookings = models.ManyToManyField('booking.Booking', blank=True, related_name='channel_bookings')
    received_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        constraints = [models.UniqueConstraint(fields=['connection', 'external_id'], name='channel_booking_once')]

    def __str__(self):
        return f"{self.ota_name} {self.ota_reference or self.external_id} ({self.status})"
