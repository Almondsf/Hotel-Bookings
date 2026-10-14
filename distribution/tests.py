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
from distribution import services
from distribution.models import ChannelBooking, ChannelConnection, RatePlanMapping, RoomTypeMapping
from rates.models import RatePlan, RateRestriction
from rooms.models import Room, RoomAvailabilityOverride, RoomType


def revision(rev_id, booking_id, status='new', arrival=None, nights=2, room_type='EXT-STD', days_price='50000',
             currency='NGN', rooms=1):
    arrival = arrival or timezone.localdate() + timedelta(days=5)
    days = {str(arrival + timedelta(days=i)): days_price for i in range(nights)}
    return {'id': rev_id, 'attributes': {
        'booking_id': booking_id, 'status': status, 'ota_name': 'Booking.com', 'ota_reservation_code': f'BDC-{booking_id}',
        'arrival_date': str(arrival), 'departure_date': str(arrival + timedelta(days=nights)), 'currency': currency,
        'customer': {'name': 'Lars', 'surname': 'Jensen', 'mail': 'lars@guest.booking.com', 'phone': '+4512345678'},
        'rooms': [{'room_type_id': room_type, 'rate_plan_id': 'EXT-BAR', 'occupancy': {'adults': 2, 'children': 0},
                   'days': days}] * rooms,
    }}


class DistributionTestCase(APITestCase):
    def setUp(self):
        cache.clear()
        self.today = timezone.localdate()
        self.standard = RoomType.objects.create(name='Standard', description='', base_price=Decimal('50000'),
                                                max_adults=2, max_children=0, bed_type='KING', bed_count=1, size=300)
        self.r1 = Room.objects.create(room_number='101', room_type=self.standard, floor_number=1)
        self.r2 = Room.objects.create(room_number='102', room_type=self.standard, floor_number=1)
        self.connection = ChannelConnection.objects.create(provider='CHANNEX', is_active=True, api_key='key',
                                                           property_id='PROP-1', webhook_secret='hook-secret', sync_days=10)
        RoomTypeMapping.objects.create(connection=self.connection, room_type=self.standard, external_id='EXT-STD')
        self.bar = RatePlan.objects.get(code='BAR')
        RatePlanMapping.objects.create(connection=self.connection, room_type=self.standard, rate_plan=self.bar,
                                       external_id='EXT-BAR')


class OutboundTests(DistributionTestCase):
    def test_availability_compressed_into_ranges(self):
        start = self.today
        RoomAvailabilityOverride.objects.create(room=self.r1, start_date=start + timedelta(days=3),
                                                end_date=start + timedelta(days=5), reason='MAINTENANCE')
        availability, _ = services.build_ari(self.connection, start, start + timedelta(days=10))
        self.assertEqual([(a['date_from'], a['date_to'], a['availability']) for a in availability], [
            (str(start), str(start + timedelta(days=2)), 2),
            (str(start + timedelta(days=3)), str(start + timedelta(days=4)), 1),
            (str(start + timedelta(days=5)), str(start + timedelta(days=9)), 2),
        ])
        self.assertTrue(all(a['room_type_id'] == 'EXT-STD' for a in availability))

    def test_rates_and_restrictions(self):
        start = self.today
        RateRestriction.objects.create(start_date=start + timedelta(days=2), end_date=start + timedelta(days=2),
                                       stop_sell=True)  # hotel-wide (no plan / room type)
        _, restrictions = services.build_ari(self.connection, start, start + timedelta(days=4))
        self.assertEqual([(r['date_from'], r['stop_sell'], r['rate']) for r in restrictions], [
            (str(start), False, '50000.00'), (str(start + timedelta(days=2)), True, '50000.00'),
            (str(start + timedelta(days=3)), False, '50000.00'),
        ])

    @mock.patch('distribution.channex.requests.request')
    def test_push_sends_property_scoped_values(self, request):
        request.return_value = mock.Mock(status_code=200, content=b'{}', json=lambda: {})
        services.push_ari.call()
        calls = {c.args[1].rsplit('/', 1)[-1]: c.kwargs['json'] for c in request.call_args_list}
        self.assertEqual(calls['availability']['values'][0]['property_id'], 'PROP-1')
        self.assertEqual(request.call_args.kwargs['headers']['user-api-key'], 'key')
        self.connection.refresh_from_db()
        self.assertIsNotNone(self.connection.last_full_sync_at)


class InboundTests(DistributionTestCase):
    def test_new_booking_imported_once(self):
        cb = services.import_revision(self.connection, revision('r1', 'B1'))
        self.assertEqual(cb.status, 'IMPORTED')
        booking = cb.bookings.get()
        self.assertEqual((booking.source, booking.status, booking.total_price), ('OTA', 'CONFIRMED', Decimal('100000.00')))
        self.assertEqual(booking.guest.last_name, 'Jensen')
        services.import_revision(self.connection, revision('r1', 'B1'))
        self.assertEqual(Booking.objects.count(), 1)

    def test_foreign_currency_needs_rate(self):
        cb = services.import_revision(self.connection, revision('r1', 'B1', currency='EUR', days_price='60'))
        self.assertEqual(cb.status, 'NEEDS_ATTENTION')
        self.assertFalse(Booking.objects.exists())

    def test_overbooking_is_flagged_not_forced(self):
        cb = services.import_revision(self.connection, revision('r1', 'B1', rooms=3))
        self.assertEqual(cb.status, 'NEEDS_ATTENTION')
        self.assertIn('No Standard rooms', cb.problem)
        self.assertFalse(Booking.objects.exists())  # all or nothing

    def test_unmapped_room_type_flagged(self):
        cb = services.import_revision(self.connection, revision('r1', 'B1', room_type='EXT-UNKNOWN'))
        self.assertEqual(cb.status, 'NEEDS_ATTENTION')

    def test_modification_and_cancellation(self):
        services.import_revision(self.connection, revision('r1', 'B1'))
        cb = services.import_revision(self.connection, revision('r2', 'B1', status='modified', nights=3))
        self.assertEqual(cb.bookings.get().nights, 3)
        self.assertEqual(Booking.objects.filter(status='CANCELLED').count(), 1)

        cb = services.import_revision(self.connection, revision('r3', 'B1', status='cancelled'))
        self.assertEqual(cb.status, 'CANCELLED')
        self.assertFalse(Booking.objects.exclude(status='CANCELLED').exists())
        self.assertEqual(Booking.objects.filter(penalty_amount__gt=0).count(), 0)  # OTA handles fees

    @mock.patch('distribution.channex.requests.request')
    def test_pull_acknowledges_processed_revisions(self, request):
        feed = {'data': [revision('r1', 'B1')]}
        request.side_effect = [mock.Mock(status_code=200, content=b'1', json=lambda: feed),
                               mock.Mock(status_code=200, content=b'', json=lambda: {})]
        self.assertEqual(services.pull_bookings.call(), 1)
        self.assertTrue(request.call_args_list[1].args[1].endswith('/booking_revisions/r1/ack'))


@override_settings(TASKS={'default': {'BACKEND': 'django.tasks.backends.dummy.DummyBackend'}})
class WebhookAndStatusTests(DistributionTestCase):
    def test_webhook_requires_secret(self):
        url = reverse('webhook-channex')
        self.assertEqual(self.client.post(url, {}, format='json').status_code, 401)
        self.assertEqual(self.client.post(url, {}, format='json', HTTP_X_WEBHOOK_SECRET='hook-secret').status_code, 202)

    def test_status_lists_bookings_needing_attention(self):
        services.import_revision(self.connection, revision('r1', 'B1', rooms=3))
        staff = User.objects.create_user('desk@hotel.com', 'D', 'K', 'x', role='receptionist')
        self.client.force_authenticate(staff)
        data = self.client.get(reverse('channel-status')).data
        self.assertEqual(len(data['needs_attention']), 1)
        cb = ChannelBooking.objects.get()
        self.client.post(reverse('channel-booking-resolve', args=[cb.pk]))
        self.assertEqual(self.client.get(reverse('channel-status')).data['needs_attention'], [])
