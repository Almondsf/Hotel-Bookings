from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase
from unittest import mock

from payments.testing import FakeGateway

from audit.models import AuditLog
from authentication.models import User
from booking.models import Booking, BookingNight, Guest, GuestIdentification
from rooms.models import Room, RoomPricing, RoomType

PASSPORT = {'document_type': 'PASSPORT', 'document_number': 'a 1234 5678', 'issuing_country': 'Nigeria'}


def make_room_type(name, price, adults=2):
    return RoomType.objects.create(
        name=name, description=name, base_price=Decimal(price), max_adults=adults, max_children=1,
        bed_type='KING', bed_count=1, size=300,
    )


class FrontDeskTestCase(APITestCase):
    def setUp(self):
        cache.clear()
        self.today = timezone.localdate()
        self.standard = make_room_type('Standard', '100.00')
        self.deluxe = make_room_type('Deluxe', '200.00')
        self.r101 = Room.objects.create(room_number='101', room_type=self.standard, floor_number=1)
        self.r102 = Room.objects.create(room_number='102', room_type=self.standard, floor_number=1)
        self.r201 = Room.objects.create(room_number='201', room_type=self.deluxe, floor_number=2)
        self.receptionist = User.objects.create_user('desk@hotel.com', 'Desk', 'Clerk', 'x', role='receptionist')
        self.manager = User.objects.create_user('gm@hotel.com', 'Gen', 'Manager', 'x', role='manager')
        self.client.force_authenticate(self.receptionist)

    def reserve(self, check_in=None, nights=2, room=None, room_type=None):
        check_in = check_in or self.today
        room_type = room_type or (room.room_type if room else self.standard)
        spec = {'room_type': room_type.id, 'number_of_adults': 1}
        if room:
            spec['room'] = room.id
        response = self.client.post(reverse('reservation-list'), {
            'guest': {'first_name': 'Chidi', 'last_name': 'Eze', 'email': 'chidi@example.com'},
            'check_in_date': check_in.isoformat(),
            'check_out_date': (check_in + timedelta(days=nights)).isoformat(),
            'rooms': [spec],
        }, format='json')
        assert response.status_code == 201, response.data
        return Booking.objects.get(pk=response.data[0]['id'])

    def act(self, booking, name, data=None):
        return self.client.post(reverse(f'reservation-{name}', args=[booking.pk]), data or {}, format='json')


class IdentificationTests(FrontDeskTestCase):
    def test_check_in_requires_id_and_accepts_it_inline(self):
        booking = self.reserve()
        refused = self.act(booking, 'check-in')
        self.assertEqual(refused.status_code, 400)
        self.assertIn('identification', refused.data)

        response = self.act(booking, 'check-in', {'identification': PASSPORT})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data['guest']['has_valid_identification'])

    def test_expired_document_rejected(self):
        booking = self.reserve()
        expired = {**PASSPORT, 'expiry_date': (self.today - timedelta(days=1)).isoformat()}
        self.assertEqual(self.act(booking, 'check-in', {'identification': expired}).status_code, 400)

    def test_number_encrypted_at_rest_and_masked_in_api(self):
        guest = Guest.objects.create(first_name='Ada', last_name='Obi', email='ada@example.com')
        response = self.client.post(reverse('guest-identifications', args=[guest.pk]), PASSPORT, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['masked_number'], '•••• 5678')
        self.assertNotIn('document_number', response.data)

        with connection.cursor() as cursor:
            cursor.execute("SELECT document_number FROM booking_guestidentification")
            stored = cursor.fetchone()[0]
        self.assertNotIn('A12345678', stored)
        self.assertEqual(GuestIdentification.objects.get().document_number, 'A12345678')

    def test_only_managers_can_reveal_and_reveals_are_audited(self):
        guest = Guest.objects.create(first_name='Ada', last_name='Obi', email='ada@example.com')
        id_pk = self.client.post(reverse('guest-identifications', args=[guest.pk]), PASSPORT, format='json').data['id']
        url = reverse('guest-reveal-identification', args=[guest.pk, id_pk])

        self.assertEqual(self.client.post(url).status_code, 403)
        self.client.force_authenticate(self.manager)
        response = self.client.post(url)
        self.assertEqual(response.data['document_number'], 'A12345678')
        entry = AuditLog.objects.get(action=AuditLog.Action.GUEST_ID_REVEALED)
        self.assertEqual(entry.actor, self.manager)
        self.assertNotIn('A12345678', str(entry.changes))

    def test_encrypted_field_cannot_be_filtered(self):
        with self.assertRaises(TypeError):
            list(GuestIdentification.objects.filter(document_number='A12345678'))


class WalkInTests(FrontDeskTestCase):
    def walk_in(self, **overrides):
        payload = {
            'guest': {'first_name': 'Musa', 'last_name': 'Bello', 'email': 'musa@example.com'},
            'room': {'room_type': self.deluxe.id, 'number_of_adults': 2},
            'check_out_date': (self.today + timedelta(days=1)).isoformat(),
            'identification': {'document_type': 'NATIONAL_ID', 'document_number': '12345678901'},
            **overrides,
        }
        return self.client.post(reverse('walk-in'), payload, format='json')

    def test_walk_in_books_and_checks_in(self):
        response = self.walk_in()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['status'], 'CHECKED_IN')
        self.assertEqual(response.data['source'], 'WALK_IN')
        self.r201.refresh_from_db()
        self.assertEqual(self.r201.status, Room.Status.OCCUPIED)

    def test_failed_check_in_leaves_nothing_behind(self):
        response = self.walk_in(identification=None)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Booking.objects.count(), 0)
        self.assertEqual(Guest.objects.count(), 0)


class RoomMoveTests(FrontDeskTestCase):
    def test_in_house_upgrade_keeps_rate_by_default(self):
        booking = self.reserve(room=self.r101)
        self.act(booking, 'check-in', {'identification': PASSPORT})
        response = self.act(booking, 'move-room', {'room': self.r201.id, 'reason': 'Complimentary upgrade'})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['room_number'], '201')
        self.assertEqual(Decimal(response.data['total_price']), Decimal('200.00'))

        self.r101.refresh_from_db()
        self.r201.refresh_from_db()
        self.assertEqual(self.r101.status, Room.Status.AVAILABLE)
        self.assertEqual(self.r201.status, Room.Status.OCCUPIED)
        self.assertEqual(AuditLog.objects.get(action=AuditLog.Action.BOOKING_ROOM_MOVED).changes['reason'], 'Complimentary upgrade')

    def test_paid_upgrade_reprices_remaining_nights_only(self):
        booking = self.reserve(room=self.r101, nights=3)
        self.act(booking, 'check-in', {'identification': PASSPORT})
        response = self.act(booking, 'move-room', {'room': self.r201.id, 'reason': 'Guest request', 'reprice': True})
        # In-house moves apply from tonight, so all 3 nights are at the new rate
        self.assertEqual(Decimal(response.data['total_price']), Decimal('600.00'))

    def test_move_needs_reason_and_free_room(self):
        booking = self.reserve(room=self.r101)
        self.reserve(room=self.r102)
        self.assertEqual(self.act(booking, 'move-room', {'room': self.r102.id}).status_code, 400)
        self.assertEqual(self.act(booking, 'move-room', {'room': self.r102.id, 'reason': 'Noise'}).status_code, 409)


class NightlyRateTests(FrontDeskTestCase):
    def test_each_night_stores_its_rate(self):
        RoomPricing.objects.create(room_type=self.standard, price_per_night=Decimal('150.00'),
                                   start_date=self.today + timedelta(days=1), end_date=self.today + timedelta(days=1))
        booking = self.reserve(nights=3)
        self.assertEqual(
            list(booking.nightly_rates.values_list('rate', flat=True)),
            [Decimal('100.00'), Decimal('150.00'), Decimal('100.00')],
        )
        self.assertEqual(booking.total_price, Decimal('350.00'))

    def test_extension_keeps_agreed_rates_even_if_prices_rise(self):
        booking = self.reserve(nights=2)
        RoomType.objects.filter(pk=self.standard.pk).update(base_price=Decimal('130.00'))
        response = self.client.patch(reverse('reservation-detail', args=[booking.pk]), {
            'check_out_date': (booking.check_out_date + timedelta(days=1)).isoformat(),
        }, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(Decimal(response.data['total_price']), Decimal('330.00'))  # 100 + 100 + 130
        self.assertEqual(BookingNight.objects.filter(booking=booking).count(), 3)


class RoomBoardTests(FrontDeskTestCase):
    def test_board_shows_in_house_arrivals_and_departures(self):
        staying = self.reserve(room=self.r101, nights=2)
        self.act(staying, 'check-in', {'identification': PASSPORT})
        self.reserve(room=self.r201, nights=1)  # arriving today

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse('room-board'))
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(queries), 6)  # constant, not per room

        board = {row['room_number']: row for row in response.data}
        self.assertEqual(board['101']['in_house']['confirmation_number'], staying.confirmation_number)
        self.assertEqual(board['101']['status'], 'OCCUPIED')
        self.assertIsNotNone(board['201']['arriving'])
        self.assertIsNone(board['102']['in_house'])

        tomorrow = self.client.get(reverse('room-board'), {'date': (self.today + timedelta(days=2)).isoformat()}).data
        self.assertTrue({r['room_number']: r for r in tomorrow}['101']['departing_today'])


class GuestProfileTests(FrontDeskTestCase):
    def test_profile_update_audits_field_names_only(self):
        guest = Guest.objects.create(first_name='Ada', last_name='Obi', email='ada@example.com')
        response = self.client.patch(reverse('guest-detail', args=[guest.pk]),
                                     {'is_vip': True, 'phone_number': '08031234567'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        entry = AuditLog.objects.get(action=AuditLog.Action.GUEST_UPDATED)
        self.assertEqual(entry.changes, {'fields': ['is_vip', 'phone_number']})

    def test_detail_includes_stay_history(self):
        booking = self.reserve()
        response = self.client.get(reverse('guest-detail', args=[booking.guest_id]))
        self.assertEqual(response.data['stays'][0]['confirmation_number'], booking.confirmation_number)

    def test_public_booking_cannot_set_vip(self):
        self.client.force_authenticate(None)
        patcher = mock.patch('payments.services.get_gateway', return_value=FakeGateway())
        patcher.start()
        self.addCleanup(patcher.stop)
        check_in = self.today + timedelta(days=3)
        self.client.post(reverse('create-booking'), {
            'guest': {'first_name': 'Sly', 'last_name': 'Fox', 'email': 'sly@example.com', 'is_vip': True, 'notes': 'x'},
            'room_type': self.standard.id, 'check_in_date': check_in.isoformat(),
            'check_out_date': (check_in + timedelta(days=1)).isoformat(),
            'number_of_adults': 1, 'number_of_children': 0, 'gateway': 'PAYSTACK',
        }, format='json')
        guest = Guest.objects.get(email='sly@example.com')
        self.assertFalse(guest.is_vip)
        self.assertEqual(guest.notes, '')
