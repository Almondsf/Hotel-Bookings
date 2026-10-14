from django.conf import settings
from django.db import models
from django.db.models import Q


class BusinessDay(models.Model):
    """
    A hotel trading day. Exactly one is OPEN at a time; night audit closes it,
    freezes its statistics and opens the next.
    """

    class Status(models.TextChoices):
        OPEN = 'OPEN', 'Open'
        CLOSED = 'CLOSED', 'Closed'

    date = models.DateField(unique=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                  related_name='+')
    # Frozen figures for the day (the manager's flash report), set at close
    statistics = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-date']
        constraints = [
            # At most one open day
            models.UniqueConstraint(fields=['status'], condition=Q(status='OPEN'), name='one_open_business_day'),
        ]

    def __str__(self):
        return f"{self.date} ({self.get_status_display()})"
