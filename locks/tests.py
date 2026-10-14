import hashlib
import hmac
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from authentication.models import User
from booking.models import Booking
from locks.models import KeyCard
from rooms.models import Room, RoomType


@override_settings(REQUIRE_GUEST_ID_AT_CHECK_IN=False, CHECKOUT_REQUIRES_SETTLED_FOLIO=False)
class KeyTests(APITestCase):
    def setUp(self):
        cache.clear()
        room_type = RoomType.objects.create(name='Std', description='', base_price=Decimal('50000'), max_adults=2,
                                            max_children=0, bed_type='KING', bed_count=1, size=300)
        self.r1 = Room.objects.create(room_number='101', room_type=room_type, floor_number=1)
        self.r2 = Room.objects.create(room_number='102', room_type=room_type, floor_number=1)
        self.client.force_authenticate(User.objects.create_user('desk@hotel.com', 'D', 'K', 'x', role='receptionist'))
        today = timezone.localdate()
        response = self.client.post(reverse('reservation-list'), {
            'guest': {'first_name': 'Ada', 'last_name': 'Obi', 'email': 'ada@example.com'},
            'check_in_date': today.isoformat(), 'check_out_date': (today + timedelta(days=2)).isoformat(),
            'rooms': [{'room_type': room_type.id, 'room': self.r1.id, 'number_of_adults': 1}],
        }, format='json')
        self.booking = Booking.objects.get(pk=response.data[0]['id'])

    def issue(self, cards=2):
        return self.client.post(reverse('booking-keys', args=[self.booking.pk]), {'cards': cards}, format='json')

    def test_keys_only_for_in_house_guests(self):
        self.assertEqual(self.issue().status_code, 409)
        self.client.post(reverse('reservation-check-in', args=[self.booking.pk]), {}, format='json')
        response = self.issue()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(len(response.data), 2)
        self.assertEqual(self.issue(cards=9).status_code, 400)

    def test_check_out_revokes_keys(self):
        self.client.post(reverse('reservation-check-in', args=[self.booking.pk]), {}, format='json')
        self.issue()
        self.client.post(reverse('reservation-check-out', args=[self.booking.pk]), {}, format='json')
        self.assertEqual(set(KeyCard.objects.values_list('status', flat=True)), {'REVOKED'})

    def test_room_move_revokes_old_room_keys(self):
        self.client.post(reverse('reservation-check-in', args=[self.booking.pk]), {}, format='json')
        self.issue(cards=1)
        self.client.post(reverse('reservation-move-room', args=[self.booking.pk]), {'room': self.r2.id, 'reason': 'Noise'},
                         format='json')
        self.assertEqual(KeyCard.objects.get().status, 'REVOKED')

    @override_settings(LOCK_SYSTEM='bridge', LOCK_BRIDGE_URL='http://locks.local', LOCK_BRIDGE_SECRET='s3cret')
    @mock.patch('locks.systems.requests.post')
    def test_bridge_requests_are_signed(self, post):
        post.return_value = mock.Mock(status_code=200, content=b'1', json=lambda: {'key_ids': ['K1']})
        self.client.post(reverse('reservation-check-in', args=[self.booking.pk]), {}, format='json')
        self.assertEqual(self.issue(cards=1).status_code, 201)
        body, headers = post.call_args.kwargs['data'], post.call_args.kwargs['headers']
        self.assertEqual(headers['X-Signature'], hmac.new(b's3cret', body, hashlib.sha256).hexdigest())
        self.assertEqual(KeyCard.objects.get().external_id, 'K1')

    @override_settings(LOCK_SYSTEM='bridge', LOCK_BRIDGE_URL='http://locks.local', LOCK_BRIDGE_SECRET='s3cret')
    @mock.patch('locks.systems.requests.post')
    def test_encoder_offline(self, post):
        import requests
        post.side_effect = requests.ConnectionError()
        self.client.post(reverse('reservation-check-in', args=[self.booking.pk]), {}, format='json')
        response = self.issue(cards=1)
        self.assertEqual(response.status_code, 502)
        self.assertIn('encoder', response.data['error'])
