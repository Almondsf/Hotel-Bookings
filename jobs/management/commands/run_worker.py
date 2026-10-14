import time

from django.conf import settings
from django.core.management.base import BaseCommand

from jobs.worker import run_due_jobs, run_periodic


class Command(BaseCommand):
    help = "Run background jobs (emails, SMS, scheduled tasks). Keep one or more running in production."

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help="Process what's due and exit (for cron).")
        parser.add_argument('--sleep', type=float, default=2.0, help="Seconds to wait when the queue is empty.")
        parser.add_argument('--queue', action='append', dest='queues', help="Queue(s) to work (default: default).")

    def handle(self, *args, once=False, sleep=2.0, queues=None, **options):
        queues = queues or ['default']
        self.stdout.write(f"Worker started on queues {', '.join(queues)}")
        while True:
            run_periodic(settings.PERIODIC_JOBS)
            done = run_due_jobs(queues)
            if once:
                self.stdout.write(f"Processed {done} job(s).")
                return
            if not done:
                time.sleep(sleep)
