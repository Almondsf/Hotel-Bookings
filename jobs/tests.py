from datetime import timedelta

from django.tasks import task
from django.test import TestCase, override_settings
from django.utils import timezone

from jobs.models import BackgroundJob, ScheduledRun
from jobs.worker import run_due_jobs, run_periodic

CALLS = []

TASKS = {
    'default': {'BACKEND': 'django.tasks.backends.immediate.ImmediateBackend'},
    'database': {'BACKEND': 'jobs.backend.DatabaseBackend'},
}


@task
def add(a, b):
    CALLS.append((a, b))
    return a + b


@task
def explode():
    raise RuntimeError("provider down")


@task
def tick():
    CALLS.append('tick')


@override_settings(TASKS=TASKS)
class DatabaseBackendTests(TestCase):
    def setUp(self):
        CALLS.clear()

    def test_enqueue_stores_job_and_worker_runs_it(self):
        result = add.using(backend='database').enqueue(2, 3)
        job = BackgroundJob.objects.get(pk=result.id)
        self.assertEqual((job.status, job.args, job.task_path), ('READY', [2, 3], 'jobs.tests.add'))
        self.assertEqual(CALLS, [])  # not run inline

        self.assertEqual(run_due_jobs(), 1)
        job.refresh_from_db()
        self.assertEqual((job.status, job.return_value, job.attempts), ('SUCCESSFUL', 5, 1))
        self.assertEqual(add.using(backend='database').get_result(result.id).return_value, 5)

    def test_deferred_jobs_wait(self):
        add.using(backend='database', run_after=timezone.now() + timedelta(hours=1)).enqueue(1, 1)
        self.assertEqual(run_due_jobs(), 0)

    def test_failures_retry_with_backoff_then_give_up(self):
        result = explode.using(backend='database').enqueue()
        run_due_jobs()
        job = BackgroundJob.objects.get(pk=result.id)
        self.assertEqual((job.status, job.attempts), ('READY', 1))
        self.assertGreater(job.run_after, timezone.now())
        self.assertIn('provider down', job.last_error)

        BackgroundJob.objects.filter(pk=job.pk).update(attempts=job.max_attempts - 1, run_after=None)
        run_due_jobs()
        job.refresh_from_db()
        self.assertEqual(job.status, 'FAILED')

    def test_rolled_back_transaction_drops_its_jobs(self):
        from django.db import transaction
        try:
            with transaction.atomic():
                add.using(backend='database').enqueue(1, 2)
                raise ValueError
        except ValueError:
            pass
        self.assertFalse(BackgroundJob.objects.exists())

    def test_periodic_jobs_run_once_per_interval(self):
        schedule = {'tick': (timedelta(minutes=5), 'jobs.tests.tick')}
        run_periodic(schedule)
        run_periodic(schedule)
        self.assertEqual(CALLS, ['tick'])  # immediate backend in this test: runs on enqueue
        ScheduledRun.objects.update(last_run_at=timezone.now() - timedelta(minutes=6))
        run_periodic(schedule)
        self.assertEqual(CALLS, ['tick', 'tick'])
