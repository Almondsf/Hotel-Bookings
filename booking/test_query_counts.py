"""
Query counts must not grow with the number of rows: list pages, searches and
whole-group actions run a fixed number of queries whether they touch two
rooms or twenty. Each test does the same thing for 3 and for 6 rooms (after
a 2-room warm-up that absorbs one-off setup such as creating the year's
invoice sequence) and requires the same count.
"""
from datetime import timedelta

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from authentication.models import User
from billing.models import Folio
from booking.models import Booking
from rooms.models import Room

from .test_reservations import ReservationTestCase, make_room_type

SIZES = (2, 3, 6)  # warm-up, then the two runs compared


class QueryCountTestCase(ReservationTestCase):
    def setUp(self):
        super().setUp()
        self.big = make_room_type('Big', '100.00', adults=2)
        for n in range(len(SIZES) * 6):
            Room.objects.create(room_number=f'9{n:02d}', room_type=self.big, floor_number=9)
        self.manager = User.objects.create_user('gm@hotel.com', 'G', 'M', 'x', role='manager')

    def queries(self, action):
        with CaptureQueriesContext(connection) as ctx:
            with self.captureOnCommitCallbacks(execute=True):
                response = action()
        if hasattr(response, 'status_code'):
            self.assertLess(response.status_code, 300, getattr(response, 'data', response))
        return len(ctx)

    def assertConstant(self, counts, what):
        _, small, large = counts
        self.assertEqual(small, large, f"{what}: query count grew with the rows ({small} -> {large})")

    def rooms(self, count):
        return [{'room_type': self.big.id, 'number_of_adults': 1}] * count

    def group(self, rooms, check_in, nights=2):
        response = self.reserve(check_in=check_in, nights=nights, rooms=self.rooms(rooms))
        self.assertEqual(response.status_code, 201, response.data)
        return response.data[0]['group_reference']


class GroupQueryCountTests(QueryCountTestCase):
    def test_creating_a_group(self):
        counts = [self.queries(lambda: self.reserve(check_in=self.today + timedelta(days=30 + 10 * i),
                                                    rooms=self.rooms(size)))
                  for i, size in enumerate(SIZES)]
        self.assertConstant(counts, 'create group')

    def test_reading_a_group(self):
        staff, guest, listing = [], [], []
        for i, size in enumerate(SIZES):
            reference = self.group(size, self.today + timedelta(days=30 + 10 * i))
            staff.append(self.queries(lambda: self.client.get(reverse('booking-group-detail', args=[reference]))))
            listing.append(self.queries(lambda: self.client.get(reverse('reservation-list'))))
            guest.append(self.queries(lambda: self.client.post(
                reverse('group-lookup'), {'reference': reference, 'email': 'chidi@example.com'}, format='json')))
        self.assertConstant(staff, 'staff group page')
        self.assertConstant(guest, 'guest group lookup')
        self.assertConstant(listing, 'reservation list')

    def test_cancelling_a_group(self):
        counts = []
        for i, size in enumerate(SIZES):
            reference = self.group(size, self.today + timedelta(days=30 + 10 * i))
            counts.append(self.queries(lambda: self.client.post(
                reverse('booking-group-cancel', args=[reference]), {'reason': 'x'}, format='json')))
        self.assertConstant(counts, 'cancel group')

    def test_checking_a_group_in_and_out(self):
        check_ins, check_outs = [], []
        for size in SIZES:
            Room.objects.update(housekeeping_status=Room.Housekeeping.CLEAN)  # cleaned after the last round
            reference = self.group(size, self.today, nights=1)
            check_ins.append(self.queries(lambda: self.client.post(reverse('booking-group-check-in', args=[reference]))))
            for folio in Folio.objects.filter(booking__group__reference=reference):  # settle each bill (setup only)
                self.act(folio.booking, 'post-room-charges')
                folio.refresh_from_db()
                self.client.post(reverse('folio-payments', args=[folio.pk]),
                                 {'method': 'CASH', 'amount': str(folio.balance)}, format='json')
            check_outs.append(self.queries(lambda: self.client.post(reverse('booking-group-check-out', args=[reference]))))
            self.assertEqual(set(Booking.objects.filter(group__reference=reference).values_list('status', flat=True)),
                             {'CHECKED_OUT'})
        self.assertConstant(check_ins, 'group check-in')
        self.assertConstant(check_outs, 'group check-out')


class ListQueryCountTests(QueryCountTestCase):
    def test_search_does_not_grow_with_room_types(self):
        def search():
            check_in = self.today + timedelta(days=5)
            return self.client.get(reverse('room-type-search'), {
                'check_in': check_in, 'check_out': check_in + timedelta(days=2), 'adults': 1})

        counts = []
        for size in SIZES:
            for n in range(size):
                room_type = make_room_type(f'Extra {size}-{n}', f'{150 + n}.00')
                Room.objects.create(room_number=f'8{size}{n}', room_type=room_type, floor_number=8)
            counts.append(self.queries(search))
        self.assertConstant(counts, 'availability search')

    def test_billing_lists_and_ledgers(self):
        folios, ledger = [], []
        self.client.force_authenticate(self.manager)
        for i, size in enumerate(SIZES):
            reference = self.group(size, self.today + timedelta(days=30 + 10 * i))
            for booking in Booking.objects.filter(group__reference=reference):
                Folio.objects.get_or_create(booking=booking, defaults={'guest_id': booking.guest_id})
            folios.append(self.queries(lambda: self.client.get(reverse('folio-list'))))
            ledger.append(self.queries(lambda: self.client.get(reverse('report-guest-ledger'))))
        self.assertConstant(folios, 'folio list')
        self.assertConstant(ledger, 'guest ledger')


class NightAuditQueryCountTests(QueryCountTestCase):
    def test_night_audit_posts_every_room_at_once(self):
        counts = []
        for size in SIZES:
            reference = self.group(size, self.today, nights=3)
            self.client.post(reverse('booking-group-check-in', args=[reference]))
            self.client.force_authenticate(self.manager)
            counts.append(self.queries(lambda: self.client.post(reverse('night-audit'), {}, format='json')))
            self.client.force_authenticate(self.receptionist)
            # Out of the next run, so each run posts only its own group's nights
            Booking.objects.filter(group__reference=reference).update(status='CHECKED_OUT')
            Room.objects.update(status=Room.Status.AVAILABLE, housekeeping_status=Room.Housekeeping.CLEAN)
            self.today += timedelta(days=1)
        self.assertConstant(counts, 'night audit')
