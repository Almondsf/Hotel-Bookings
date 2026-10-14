from django.core.management.base import BaseCommand

from privacy.services import apply_retention


class Command(BaseCommand):
    help = "Anonymise guests past the retention period and delete old ID documents (also runs daily in the worker)."

    def handle(self, *args, **options):
        anonymised, ids_deleted = apply_retention()
        self.stdout.write(f"Anonymised {anonymised} guest(s); deleted {ids_deleted} ID document(s).")
