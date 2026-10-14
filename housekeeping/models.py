from django.conf import settings
from django.db import models


class HousekeepingTask(models.Model):
    class TaskType(models.TextChoices):
        DEPARTURE_CLEAN = 'DEPARTURE_CLEAN', 'Departure clean'
        STAYOVER = 'STAYOVER', 'Stay-over service'
        DEEP_CLEAN = 'DEEP_CLEAN', 'Deep clean'
        TURNDOWN = 'TURNDOWN', 'Turndown'

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        IN_PROGRESS = 'IN_PROGRESS', 'In progress'
        DONE = 'DONE', 'Done'
        SKIPPED = 'SKIPPED', 'Skipped'

    room = models.ForeignKey('rooms.Room', related_name='housekeeping_tasks', on_delete=models.CASCADE)
    date = models.DateField()
    task_type = models.CharField(max_length=20, choices=TaskType.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    # A guest is due in this room today: clean it first
    is_rush = models.BooleanField(default=False)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name='housekeeping_tasks')
    notes = models.CharField(max_length=255, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['date', '-is_rush', 'room__floor_number', 'room__room_number']
        constraints = [
            models.UniqueConstraint(fields=['room', 'date', 'task_type'], name='housekeeping_task_once_per_day'),
        ]
        indexes = [models.Index(fields=['date', 'status'])]

    def __str__(self):
        return f"{self.get_task_type_display()} - Room {self.room.room_number} ({self.date})"
