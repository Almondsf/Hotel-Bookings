from django.db import models
from django.db.models import Q


class Notification(models.Model):
    """One message to one guest on one channel, and what happened to it."""

    class Channel(models.TextChoices):
        EMAIL = 'EMAIL', 'Email'
        SMS = 'SMS', 'SMS'
        WHATSAPP = 'WHATSAPP', 'WhatsApp'

    class Status(models.TextChoices):
        QUEUED = 'QUEUED', 'Queued'
        SENT = 'SENT', 'Sent'
        FAILED = 'FAILED', 'Failed'
        SKIPPED = 'SKIPPED', 'Skipped'

    template = models.CharField(max_length=50)
    channel = models.CharField(max_length=10, choices=Channel.choices)
    booking = models.ForeignKey('booking.Booking', null=True, blank=True, related_name='notifications',
                                on_delete=models.CASCADE)
    recipient = models.CharField(max_length=255)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    provider_message_id = models.CharField(max_length=100, blank=True)
    error = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            # A booking never gets the same message twice on a channel (jobs can retry safely)
            models.UniqueConstraint(fields=['template', 'channel', 'booking'], condition=Q(booking__isnull=False),
                                    name='notification_once_per_booking'),
        ]

    def __str__(self):
        return f"{self.template} via {self.channel} to {self.recipient} ({self.status})"
