from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from audit.models import AuditLog
from authentication.models import User
from booking.models import Booking, Guest
from rooms.models import Room, RoomAvailabilityOverride, RoomPricing, RoomType
from rooms.services import (
    calculate_average_price_per_night,
    calculate_total_price,
    generate_booking_plans,
    get_available_rooms_for_type,
)


def make_room_type(name, price, adults=2, children=0):
    return RoomType.objects.create(
        name=name, description=name, base_price=Decimal(price),
        max_adults=adults, max_children=children,
        bed_type='KING', bed_count=1, size=300,
    )


def make_booking(room, check_in, check_out, status='CONFIRMED'):
    guest = Guest.objects.create(first_name='Ada', last_name='Obi', email='ada@example.com')
    return Booking.objects.create(
        guest=guest, room=room, number_of_adults=1, number_of_children=0,
        price_per_night=room.room_type.base_price, total_price=room.room_type.base_price,
        status=status, confirmation_number=f'BK-{Booking.objects.count():06d}',
        check_in_date=check_in, check_out_date=check_out,
    )


class AvailabilityTests(APITestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.check_in = self.today + timedelta(days=10)
        self.check_out = self.today + timedelta(days=13)
        self.standard = make_room_type('Standard', '100.00')
        self.room = Room.objects.create(room_number='101', room_type=self.standard, floor_number=1)

    def available(self):
        return list(get_available_rooms_for_type(self.standard, self.check_in, self.check_out))

    def test_free_room_is_available(self):
        self.assertEqual(self.available(), [self.room])

    def test_overlapping_active_booking_blocks_room(self):
        for status in ['PENDING', 'CONFIRMED', 'CHECKED_IN']:
            booking = make_booking(self.room, self.check_in + timedelta(days=1), self.check_out + timedelta(days=2), status)
            self.assertEqual(self.available(), [], status)
            booking.delete()

    def test_cancelled_booking_does_not_block_room(self):
        make_booking(self.room, self.check_in, self.check_out, 'CANCELLED')
        self.assertEqual(self.available(), [self.room])

    def test_back_to_back_stays_do_not_overlap(self):
        # Previous guest checks out the day the new guest checks in
        make_booking(self.room, self.check_in - timedelta(days=2), self.check_in)
        self.assertEqual(self.available(), [self.room])

    def test_override_blocks_room(self):
        RoomAvailabilityOverride.objects.create(
            room=self.room, start_date=self.check_in, end_date=self.check_in + timedelta(days=1), reason='MAINTENANCE'
        )
        self.assertEqual(self.available(), [])

    def test_unsellable_room_is_unavailable(self):
        for status in Room.UNSELLABLE_STATUSES:
            self.room.status = status
            self.room.save()
            self.assertEqual(self.available(), [], status)

    def test_currently_occupied_room_can_be_sold_for_future_dates(self):
        self.room.status = Room.Status.OCCUPIED
        self.room.save()
        self.assertEqual(self.available(), [self.room])


class PricingTests(APITestCase):
    def setUp(self):
        self.standard = make_room_type('Standard', '100.00')
        self.check_in = timezone.localdate() + timedelta(days=10)

    def test_base_price_without_seasonal_rates(self):
        check_out = self.check_in + timedelta(days=3)
        self.assertEqual(calculate_total_price(self.standard, self.check_in, check_out), Decimal('300.00'))

    def test_stay_spanning_seasonal_rate(self):
        # Nights 2 and 3 are at the seasonal rate
        RoomPricing.objects.create(
            room_type=self.standard, price_per_night=Decimal('150.00'), reason='Detty December',
            start_date=self.check_in + timedelta(days=1), end_date=self.check_in + timedelta(days=2),
        )
        check_out = self.check_in + timedelta(days=4)
        self.assertEqual(calculate_total_price(self.standard, self.check_in, check_out), Decimal('500.00'))
        self.assertEqual(calculate_average_price_per_night(self.standard, self.check_in, check_out), Decimal('125.00'))


class BookingPlanTests(APITestCase):
    def setUp(self):
        self.check_in = timezone.localdate() + timedelta(days=10)
        self.check_out = self.check_in + timedelta(days=2)
        self.single = make_room_type('Single', '50.00', adults=1)
        self.double = make_room_type('Double', '80.00', adults=2)
        Room.objects.create(room_number='101', room_type=self.single, floor_number=1)
        Room.objects.create(room_number='102', room_type=self.single, floor_number=1)
        Room.objects.create(room_number='201', room_type=self.double, floor_number=2)

    def plan_summaries(self, plans):
        return [
            (sorted((rt.name, n) for rt, n in p['rooms'].items()), p['total_price'])
            for p in plans
        ]

    def test_no_inventory_returns_empty_plans(self):
        Room.objects.all().delete()
        self.assertEqual(
            generate_booking_plans(self.check_in, self.check_out, 3, 0),
            {'budget_friendly': [], 'convenience': []},
        )

    def test_plans_respect_availability_and_are_minimal(self):
        plans = generate_booking_plans(self.check_in, self.check_out, 3, 0)
        # Only one double exists, so "two doubles" must not be suggested.
        self.assertEqual(
            self.plan_summaries(plans['budget_friendly']),
            [
                ([('Double', 1), ('Single', 1)], Decimal('260.00')),
            ],
        )

    def test_party_too_large_for_hotel_returns_no_plans(self):
        plans = generate_booking_plans(self.check_in, self.check_out, 10, 0)
        self.assertEqual(plans['budget_friendly'], [])

    def test_large_inventory_does_not_explode(self):
        for i in range(8):
            rt = make_room_type(f'Type {i}', f'{60 + i}.00', adults=1)
            for n in range(10):
                Room.objects.create(room_number=f'T{i}-{n}', room_type=rt, floor_number=3)
        plans = generate_booking_plans(self.check_in, self.check_out, 10, 0)
        self.assertTrue(plans['budget_friendly'])


class RoomApiTests(APITestCase):
    def setUp(self):
        cache.clear()  # reset throttle counters
        self.standard = make_room_type('Standard', '100.00', adults=2, children=1)
        Room.objects.create(room_number='101', room_type=self.standard, floor_number=1)
        self.check_in = timezone.localdate() + timedelta(days=10)
        self.check_out = self.check_in + timedelta(days=2)

    def search(self, adults, children=0):
        return self.client.get(reverse('room-type-search'), {
            'check_in': self.check_in.isoformat(), 'check_out': self.check_out.isoformat(),
            'adults': adults, 'children': children,
        })

    def test_search_returns_fitting_room_type(self):
        response = self.search(2, 1)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([r['name'] for r in response.data['room_types']], ['Standard'])
        self.assertEqual(response.data['room_types'][0]['total_price'], Decimal('200.00'))
        self.assertIsNone(response.data['booking_plans'])

    def test_search_with_no_fit_and_no_inventory_does_not_crash(self):
        Room.objects.all().delete()
        response = self.search(5)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['booking_plans'], {'budget_friendly': [], 'convenience': []})

    def test_search_rejects_past_dates(self):
        self.check_in = timezone.localdate() - timedelta(days=1)
        self.assertEqual(self.search(1).status_code, 400)

    def test_search_rejects_overlong_stay_and_huge_party(self):
        self.check_out = self.check_in + timedelta(days=365)
        self.assertEqual(self.search(1).status_code, 400)
        self.check_out = self.check_in + timedelta(days=2)
        self.assertEqual(self.search(10_000).status_code, 400)

    def test_search_rejects_missing_or_malformed_params(self):
        url = reverse('room-type-search')
        self.assertEqual(self.client.get(url).status_code, 400)
        self.assertEqual(self.client.get(url, {
            'check_in': 'tomorrow', 'check_out': self.check_out.isoformat(), 'adults': 'two',
        }).status_code, 400)

    def test_room_type_create_requires_admin(self):
        payload = {
            'name': 'Suite', 'description': 'Suite', 'base_price': '300.00', 'max_adults': 2,
            'max_children': 2, 'bed_type': 'KING', 'bed_count': 1, 'size': 600,
        }
        url = reverse('create-room-type')
        self.assertEqual(self.client.post(url, payload).status_code, 401)

        staff = User.objects.create_user('staff@example.com', 'Staff', 'User', 'pw', role='receptionist')
        self.client.force_authenticate(staff)
        self.assertEqual(self.client.post(url, payload).status_code, 403)

        manager = User.objects.create_user('manager@example.com', 'Man', 'Ager', 'pw', role='manager')
        self.client.force_authenticate(manager)
        self.assertEqual(self.client.post(url, payload).status_code, 201)
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.ROOM_TYPE_CREATED, actor=manager).exists())

    def test_admin_can_create_room(self):
        admin = User.objects.create_superuser('Admin', 'User', 'admin@example.com', 'pw')
        self.client.force_authenticate(admin)
        response = self.client.post(reverse('create-room'), {
            'room_number': '102', 'room_type': self.standard.id, 'floor_number': 1,
        })
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['room_type_detail']['name'], 'Standard')


class RoomEditingTests(APITestCase):
    def setUp(self):
        self.room_type = make_room_type('Deluxe', '150000')
        self.room = Room.objects.create(room_number='201', room_type=self.room_type, floor_number=2)
        self.manager = User.objects.create_user('manager@example.com', 'Man', 'Ager', 'pw', role='manager')
        self.client.force_authenticate(self.manager)

    def test_manager_changes_room_type_price_and_it_is_audited(self):
        url = reverse('room-type-update', args=[self.room_type.pk])
        response = self.client.patch(url, {'base_price': '165000.00', 'description': 'Renovated'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.room_type.refresh_from_db()
        self.assertEqual(self.room_type.base_price, Decimal('165000.00'))
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.ROOM_TYPE_UPDATED, actor=self.manager).exists())

    def test_receptionist_cannot_edit_rooms(self):
        self.client.force_authenticate(User.objects.create_user('desk@example.com', 'De', 'Sk', 'pw', role='receptionist'))
        self.assertEqual(self.client.patch(reverse('room-type-update', args=[self.room_type.pk]),
                                           {'base_price': '1.00'}, format='json').status_code, 403)
        self.assertEqual(self.client.patch(reverse('room-update', args=[self.room.pk]),
                                           {'status': 'OUT_OF_SERVICE'}, format='json').status_code, 403)

    def test_room_can_be_taken_out_of_service_and_back(self):
        url = reverse('room-update', args=[self.room.pk])
        self.assertEqual(self.client.patch(url, {'status': 'OUT_OF_SERVICE', 'notes': 'Renovation'}, format='json').status_code, 200)
        self.room.refresh_from_db()
        self.assertEqual((self.room.status, self.room.notes), ('OUT_OF_SERVICE', 'Renovation'))
        self.assertEqual(self.client.patch(url, {'status': 'AVAILABLE'}, format='json').status_code, 200)

    def test_occupancy_and_maintenance_are_not_editable_here(self):
        url = reverse('room-update', args=[self.room.pk])
        self.assertEqual(self.client.patch(url, {'status': 'OCCUPIED'}, format='json').status_code, 400)
        Room.objects.filter(pk=self.room.pk).update(status=Room.Status.OCCUPIED)
        response = self.client.patch(url, {'status': 'OUT_OF_SERVICE'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.patch(url, {'room_number': '999'}, format='json').status_code, 200)
        self.room.refresh_from_db()
        self.assertEqual(self.room.room_number, '201')  # room numbers are fixed once created


class SearchRankingTests(APITestCase):
    """Check availability lists the closest fit for the party first, then the cheapest."""

    def setUp(self):
        for name, price, adults, children in [
            ('Executive Suite', '350000', 2, 1), ('Family Suite', '220000', 4, 3), ('Classic Single', '40000', 1, 0),
            ('Deluxe Suite', '150000', 3, 2), ('Standard Room', '85000', 2, 1),
        ]:
            room_type = make_room_type(name, price, adults, children)
            Room.objects.create(room_number=name[:3].upper(), room_type=room_type, floor_number=1)
        self.check_in = timezone.localdate() + timedelta(days=10)

    def search(self, adults, children=0):
        response = self.client.get(reverse('room-type-search'), {
            'check_in': self.check_in, 'check_out': self.check_in + timedelta(days=2),
            'adults': adults, 'children': children,
        })
        self.assertEqual(response.status_code, 200, response.data)
        return [r['name'] for r in response.data['room_types']]

    def test_single_traveller_sees_the_single_room_first(self):
        self.assertEqual(self.search(1), ['Classic Single', 'Standard Room', 'Executive Suite', 'Deluxe Suite', 'Family Suite'])

    def test_couple_sees_doubles_cheapest_first_before_suites(self):
        self.assertEqual(self.search(2), ['Standard Room', 'Executive Suite', 'Deluxe Suite', 'Family Suite'])

    def test_family_sees_the_suite_that_fits_them_first(self):
        self.assertEqual(self.search(2, 2), ['Deluxe Suite', 'Family Suite'])
        self.assertEqual(self.search(4, 1), ['Family Suite'])


class CancellationTermsInSearchTests(APITestCase):
    """Search tells guests when free cancellation ends for their dates, before they pay."""

    def setUp(self):
        room_type = make_room_type('Standard', '50000', 2, 0)
        Room.objects.create(room_number='101', room_type=room_type, floor_number=1)

    def plan_terms(self, days_ahead):
        check_in = timezone.localdate() + timedelta(days=days_ahead)
        response = self.client.get(reverse('room-type-search'), {
            'check_in': check_in, 'check_out': check_in + timedelta(days=1), 'adults': 1})
        return response.data['room_types'][0]['rate_plans'][0]

    def test_last_minute_stay_is_already_past_free_cancellation(self):
        terms = self.plan_terms(days_ahead=1)  # inside the default 48-hour window
        self.assertTrue(terms['free_cancellation_passed'])
        self.assertIsNotNone(terms['free_cancellation_until'])

    def test_stay_further_out_shows_the_deadline(self):
        terms = self.plan_terms(days_ahead=10)
        self.assertFalse(terms['free_cancellation_passed'])
        self.assertIn('T14:00:00', terms['free_cancellation_until'])  # 48 hours before the 14:00 check-in
