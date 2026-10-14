"""Executes queued jobs and runs periodic jobs. See `manage.py run_worker`."""
import logging
import socket
import traceback
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.json import normalize_json
from django.utils.module_loading import import_string

from .models import BackgroundJob, ScheduledRun

logger = logging.getLogger(__name__)

WORKER_ID = f"{socket.gethostname()}-{get_random_string(8)}"
Status = BackgroundJob.Status


def claim_next(queues):
    """Take the next due job, skipping rows another worker has locked."""
    now = timezone.now()
    with transaction.atomic():
        job = (BackgroundJob.objects
               .select_for_update(skip_locked=True)
               .filter(status=Status.READY, queue_name__in=queues)
               .exclude(run_after__gt=now)
               .order_by('-priority', 'enqueued_at')
               .first())
        if job is None:
            return None
        job.status = Status.RUNNING
        job.started_at = now
        job.attempts += 1
        job.worker_id = WORKER_ID
        job.save(update_fields=['status', 'started_at', 'attempts', 'worker_id'])
    return job


def execute(job):
    try:
        task = import_string(job.task_path)
        value = task.call(*job.args, **job.kwargs)
    except Exception as e:
        job.last_error = ''.join(traceback.format_exception(e))[-5000:]
        job.finished_at = timezone.now()
        if job.attempts < job.max_attempts:
            # Exponential backoff: 1, 2, 4, 8... minutes
            job.status = Status.READY
            job.run_after = timezone.now() + timedelta(minutes=2 ** (job.attempts - 1))
            logger.warning("Job %s (%s) failed, retrying: %s", job.pk, job.task_path, e)
        else:
            job.status = Status.FAILED
            logger.error("Job %s (%s) failed permanently: %s", job.pk, job.task_path, e)
        job.save(update_fields=['status', 'run_after', 'last_error', 'finished_at'])
        return False
    job.status = Status.SUCCESSFUL
    job.return_value = normalize_json(value)
    job.finished_at = timezone.now()
    job.save(update_fields=['status', 'return_value', 'finished_at'])
    return True


def run_due_jobs(queues=('default',), limit=100):
    done = 0
    while done < limit:
        job = claim_next(queues)
        if job is None:
            break
        execute(job)
        done += 1
    return done


def run_periodic(schedule):
    """
    `schedule` maps a name to (interval, task path). Each periodic job is
    enqueued at most once per interval across all workers.
    """
    now = timezone.now()
    for name, (interval, task_path) in schedule.items():
        with transaction.atomic():
            run, created = ScheduledRun.objects.select_for_update().get_or_create(
                name=name, defaults={'last_run_at': now})
            if not created and run.last_run_at + interval > now:
                continue
            run.last_run_at = now
            run.save(update_fields=['last_run_at'])
            import_string(task_path).enqueue()
