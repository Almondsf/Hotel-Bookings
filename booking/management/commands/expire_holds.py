from django.core.management.base import BaseCommand

from booking.lifecycle import expire_holds


class Command(BaseCommand):
    help = "Cancel unpaid bookings whose room hold has expired. Run every minute (cron/scheduler)."

    def handle(self, *args, **options):
        count = expire_holds()
        self.stdout.write(f"Expired {count} booking hold(s).")
