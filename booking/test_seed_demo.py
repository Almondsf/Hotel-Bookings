from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from billing.models import Folio
from booking.models import Booking
from nightaudit.models import BusinessDay


class SeedDemoTests(TestCase):
    @override_settings(DEBUG=False)
    def test_refuses_outside_debug(self):
        with self.assertRaises(CommandError):
            call_command('seed_demo', stdout=StringIO())

    @override_settings(DEBUG=True)
    def test_simulates_a_consistent_fortnight(self):
        call_command('seed_demo', stdout=StringIO())

        self.assertEqual(BusinessDay.objects.filter(status=BusinessDay.Status.CLOSED).count(), 14)
        self.assertEqual(BusinessDay.objects.filter(status=BusinessDay.Status.OPEN).count(), 1)
        for status in [Booking.Status.CHECKED_OUT, Booking.Status.CHECKED_IN, Booking.Status.CONFIRMED]:
            self.assertTrue(Booking.objects.filter(status=status).exists(), status)
        # Every checked-out stay was billed and closed through the folio
        for booking in Booking.objects.filter(status=Booking.Status.CHECKED_OUT):
            self.assertNotEqual(booking.folio.status, Folio.Status.OPEN, booking.confirmation_number)
        # Nobody is in two rooms at once (group bookings aside)
        live = list(Booking.objects.blocking().filter(group__isnull=True))
        for a in live:
            for b in live:
                if a.pk < b.pk and a.guest_id == b.guest_id:
                    self.assertFalse(a.check_in_date < b.check_out_date and b.check_in_date < a.check_out_date)

        with self.assertRaises(CommandError):
            call_command('seed_demo', stdout=StringIO())  # data exists: needs --reset
        call_command('seed_demo', '--reset', stdout=StringIO())
        self.assertEqual(BusinessDay.objects.filter(status=BusinessDay.Status.CLOSED).count(), 14)
