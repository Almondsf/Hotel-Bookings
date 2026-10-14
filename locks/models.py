from django.conf import settings
from django.db import models


class KeyCard(models.Model):
    """A room key encoded for a stay. Revoked at check-out or when the guest changes rooms."""

    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        REVOKED = 'REVOKED', 'Revoked'

    booking = models.ForeignKey('booking.Booking', related_name='key_cards', on_delete=models.PROTECT)
    room = models.ForeignKey('rooms.Room', related_name='key_cards', on_delete=models.PROTECT)
    # The lock system's own id for the key, used to revoke it
    external_id = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    valid_from = models.DateTimeField()
    valid_until = models.DateTimeField()
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    issued_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoke_reason = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ['-issued_at']
        indexes = [models.Index(fields=['booking', 'status'])]
