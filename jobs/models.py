from django.db import models


class BackgroundJob(models.Model):
    """
    A queued task for the database task backend. Rows are written in the
    same transaction as the work that enqueues them, so a rolled-back request
    never leaves a stray job (and a committed one never loses its job).
    """

    class Status(models.TextChoices):
        READY = 'READY', 'Ready'
        RUNNING = 'RUNNING', 'Running'
        SUCCESSFUL = 'SUCCESSFUL', 'Successful'
        FAILED = 'FAILED', 'Failed'

    id = models.CharField(max_length=32, primary_key=True)
    task_path = models.CharField(max_length=255)
    queue_name = models.CharField(max_length=50, default='default')
    priority = models.IntegerField(default=0)
    args = models.JSONField(default=list)
    kwargs = models.JSONField(default=dict)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.READY)
    run_after = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=5)
    last_error = models.TextField(blank=True)
    return_value = models.JSONField(null=True, blank=True)
    worker_id = models.CharField(max_length=64, blank=True)
    enqueued_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-priority', 'enqueued_at']
        indexes = [models.Index(fields=['status', 'queue_name', 'run_after', 'priority'])]

    def __str__(self):
        return f"{self.task_path} ({self.status})"


class ScheduledRun(models.Model):
    """When each periodic job last ran, so several workers don't all run it."""
    name = models.CharField(max_length=100, unique=True)
    last_run_at = models.DateTimeField()
