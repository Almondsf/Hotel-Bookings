from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.core import mail
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from booking.models import Booking
from payments.testing import FakeGatewayMixin
from rooms.models import Room, RoomType


class BookingApiTests(FakeGatewayMixin, APITestCase):
    def setUp(self):
        super().setUp()
        cache.clear()  # reset throttle counters
        self.room_type = RoomType.objects.create(
            name='Standard', description='Standard', base_price=Decimal('100.00'),
            max_adults=2, max_children=1, bed_type='KING', bed_count=1, size=300,
        )
        self.room = Room.objects.create(room_number='101', room_type=self.room_type, floor_number=1)
        self.check_in = timezone.localdate() + timedelta(days=5)
        self.check_out = self.check_in + timedelta(days=3)

    def payload(self, **overrides):
        data = {
            'guest': {'first_name': 'Ada', 'last_name': 'Obi', 'email': 'Ada@Example.com'},
            'room_type': self.room_type.id,
            'check_in_date': self.check_in.isoformat(),
            'check_out_date': self.check_out.isoformat(),
            'number_of_adults': 2,
            'number_of_children': 0,
            'gateway': 'PAYSTACK',
        }
        data.update(overrides)
        return data

    def book(self, **overrides):
        return self.client.post(reverse('create-booking'), self.payload(**overrides), format='json')

    def verify(self, reference):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse('payment-verify'), {'reference': reference}, format='json')

    def test_booking_holds_room_until_paid_then_confirms(self):
        response = self.book()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['status'], 'PENDING')
        self.assertRegex(response.data['confirmation_number'], r'^BK-[A-Z0-9]{6}$')
        payment = response.data['payment']
        self.assertEqual(payment['amount'], '322.50')  # 3 nights + 7.5% VAT
        self.assertTrue(payment['authorization_url'].startswith('https://checkout.test/'))

        # Not paid yet: verifying changes nothing
        self.assertEqual(self.verify(payment['reference']).data['status'], 'INITIALIZED')

        self.gateway.pay(payment['reference'])
        verified = self.verify(payment['reference'])
        self.assertEqual(verified.data['status'], 'SUCCEEDED')
        self.assertEqual(verified.data['booking']['status'], 'CONFIRMED')

        booking = Booking.objects.get()
        self.assertEqual(booking.folio.payments_total, Decimal('322.50'))
        self.assertEqual(len(mail.outbox), 1)

    def test_second_booking_for_same_dates_is_rejected(self):
        self.assertEqual(self.book().status_code, 201)
        self.assertEqual(self.book().status_code, 400)  # the unpaid hold still blocks the room
        self.assertEqual(Booking.objects.count(), 1)

    def test_rejects_past_check_in(self):
        response = self.book(check_in_date=(timezone.localdate() - timedelta(days=1)).isoformat())
        self.assertEqual(response.status_code, 400)
        self.assertIn('check_in_date', response.data)

    def test_rejects_party_over_capacity(self):
        response = self.book(number_of_adults=3)
        self.assertEqual(response.status_code, 400)
        self.assertIn('number_of_adults', response.data)

    def test_rejects_check_out_before_check_in(self):
        self.assertEqual(self.book(check_out_date=self.check_in.isoformat()).status_code, 400)

    def test_rejects_unknown_gateway(self):
        self.assertEqual(self.book(gateway='PAYPAL').status_code, 400)

    def test_room_taken_between_validation_and_creation(self):
        # Simulates a concurrent request grabbing the last room after this
        # request passed validation: the locked re-check must catch it.
        with mock.patch('booking.serializers.get_available_rooms_for_type') as validation_check:
            validation_check.return_value.exists.return_value = True
            self.assertEqual(self.book().status_code, 201)
            response = self.book()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(Booking.objects.count(), 1)

    def test_gateway_down_releases_room(self):
        self.gateway.fail_initialize = True
        response = self.book()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(Booking.objects.get().status, 'CANCELLED')
        self.gateway.fail_initialize = False
        self.assertEqual(self.book().status_code, 201)


class BookingLookupTests(FakeGatewayMixin, APITestCase):
    def setUp(self):
        super().setUp()
        cache.clear()  # reset throttle counters
        room_type = RoomType.objects.create(
            name='Standard', description='Standard', base_price=Decimal('100.00'),
            max_adults=2, max_children=0, bed_type='KING', bed_count=1, size=300,
        )
        Room.objects.create(room_number='101', room_type=room_type, floor_number=1)
        check_in = timezone.localdate() + timedelta(days=5)
        response = self.client.post(reverse('create-booking'), {
            'guest': {'first_name': 'Ada', 'last_name': 'Obi', 'email': 'ada@example.com'},
            'room_type': room_type.id,
            'check_in_date': check_in.isoformat(),
            'check_out_date': (check_in + timedelta(days=1)).isoformat(),
            'number_of_adults': 1, 'number_of_children': 0, 'gateway': 'PAYSTACK',
        }, format='json')
        self.confirmation_number = response.data['confirmation_number']

    def lookup(self, confirmation_number, email):
        return self.client.post(reverse('booking-lookup'), {
            'confirmation_number': confirmation_number, 'email': email,
        }, format='json')

    def test_lookup_is_case_insensitive(self):
        response = self.lookup(self.confirmation_number.lower(), ' ADA@example.com ')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['confirmation_number'], self.confirmation_number)

    def test_wrong_email_looks_the_same_as_missing_booking(self):
        wrong_email = self.lookup(self.confirmation_number, 'someone@else.com')
        missing = self.lookup('BK-NOPE00', 'ada@example.com')
        self.assertEqual(wrong_email.status_code, 404)
        self.assertEqual(wrong_email.data, missing.data)

    def test_requires_both_fields(self):
        self.assertEqual(self.lookup(self.confirmation_number, '').status_code, 400)

    def test_non_string_input_does_not_crash(self):
        self.assertEqual(self.lookup(12345, ['ada@example.com']).status_code, 400)

    def test_lookup_is_rate_limited(self):
        statuses = [self.lookup('BK-NOPE00', 'x@example.com').status_code for _ in range(12)]
        self.assertIn(429, statuses)
