from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from authentication.models import User
from booking.models import Booking
from notifications.channels import normalize_phone
from notifications.models import Notification
from notifications.services import deliver, notify, send_pre_arrival_reminders
from rooms.models import Room, RoomType


@override_settings(REQUIRE_GUEST_ID_AT_CHECK_IN=False, HOTEL_NAME='Lagos Grand')
class NotificationTestCase(APITestCase):
    def setUp(self):
        cache.clear()
        self.today = timezone.localdate()
        self.room_type = RoomType.objects.create(
            name='Deluxe', description='', base_price=Decimal('120000'), max_adults=2, max_children=0,
            bed_type='KING', bed_count=1, size=400,
        )
        Room.objects.create(room_number='201', room_type=self.room_type, floor_number=2)
        self.desk = User.objects.create_user('desk@hotel.com', 'D', 'K', 'x', role='receptionist')
        self.client.force_authenticate(self.desk)

    def reserve(self, check_in=None, phone='0803 123 4567', last_name="O'Brien"):
        check_in = check_in or self.today + timedelta(days=3)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('reservation-list'), {
                'guest': {'first_name': 'Sean', 'last_name': last_name, 'email': 'sean@example.com', 'phone_number': phone},
                'check_in_date': check_in.isoformat(), 'check_out_date': (check_in + timedelta(days=1)).isoformat(),
                'rooms': [{'room_type': self.room_type.id, 'number_of_adults': 1}],
            }, format='json')
        assert response.status_code == 201, response.data
        return Booking.objects.get(pk=response.data[0]['id'])


class ConfirmationTests(NotificationTestCase):
    def test_confirmation_email_is_plain_text_and_unescaped(self):
        booking = self.reserve()
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertIn(booking.confirmation_number, message.subject)
        self.assertIn('Lagos Grand', message.subject)
        self.assertNotIn('&#x27;', message.body)
        self.assertIn('valid ID', message.body)
        self.assertEqual(Notification.objects.get(channel='EMAIL').status, 'SENT')
        self.assertFalse(Notification.objects.filter(channel='SMS').exists())  # SMS disabled

    @override_settings(SMS_ENABLED=True, TERMII_API_KEY='tk', TERMII_SENDER_ID='LagosGrand')
    @mock.patch('notifications.channels.requests.post')
    def test_sms_via_termii_with_normalized_number(self, post):
        post.return_value = mock.Mock(status_code=200, content=b'1', json=lambda: {'message_id': 'T-1'})
        self.reserve()
        payload = post.call_args.kwargs['json']
        self.assertEqual((payload['to'], payload['channel'], payload['from']), ('2348031234567', 'dnd', 'LagosGrand'))
        sms = Notification.objects.get(channel='SMS')
        self.assertEqual((sms.status, sms.provider_message_id), ('SENT', 'T-1'))

    @override_settings(SMS_ENABLED=True, TERMII_API_KEY='tk')
    @mock.patch('notifications.channels.requests.post')
    def test_opted_out_guests_get_no_sms(self, post):
        post.return_value = mock.Mock(status_code=200, content=b'1', json=lambda: {'message_id': 'T-1'})
        booking = self.reserve()
        Notification.objects.all().delete()
        booking.guest.sms_opt_out = True
        booking.guest.save()
        with self.captureOnCommitCallbacks(execute=True):
            notify('booking_cancelled', booking)
        self.assertEqual(list(Notification.objects.values_list('channel', flat=True)), ['EMAIL'])

    def test_each_message_sent_once(self):
        booking = self.reserve()
        with self.captureOnCommitCallbacks(execute=True):
            notify('booking_confirmed', booking)
        self.assertEqual(Notification.objects.filter(template='booking_confirmed').count(), 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_failed_delivery_is_recorded_and_retried_by_worker(self):
        booking = self.reserve()
        notification = Notification.objects.create(template='booking_cancelled', channel='EMAIL', booking=booking,
                                                   recipient='sean@example.com')
        with mock.patch('notifications.channels.EmailMessage.send', side_effect=OSError('SMTP down')):
            with self.assertRaises(OSError):
                deliver.call(notification.pk)
        notification.refresh_from_db()
        self.assertEqual((notification.status, notification.error), ('FAILED', 'SMTP down'))


class LifecycleMessageTests(NotificationTestCase):
    def test_cancellation_and_checkout_messages(self):
        booking = self.reserve()
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('reservation-cancel', args=[booking.pk]), {'reason': 'x'}, format='json')
        self.assertIn('cancelled', mail.outbox[-1].subject)

        stay = self.reserve(check_in=self.today)
        self.client.post(reverse('reservation-check-in', args=[stay.pk]), {}, format='json')
        folio = self.client.post(reverse('reservation-post-room-charges', args=[stay.pk])).data['folio']
        self.client.post(reverse('folio-payments', args=[folio['id']]), {'method': 'CASH', 'amount': folio['balance']}, format='json')
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('reservation-check-out', args=[stay.pk]), {}, format='json')
        thank_you = mail.outbox[-1]
        self.assertIn('Thank you', thank_you.subject)
        self.assertEqual(thank_you.attachments[0][2], 'application/pdf')

    def test_pre_arrival_reminders(self):
        tomorrow = self.reserve(check_in=self.today + timedelta(days=1))
        self.reserve(check_in=self.today + timedelta(days=5))
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(send_pre_arrival_reminders.call(), 1)
        reminder = Notification.objects.get(template='pre_arrival')
        self.assertEqual(reminder.booking, tomorrow)


class PhoneTests(NotificationTestCase):
    def test_normalization(self):
        self.assertEqual(normalize_phone('0803-123-4567'), '2348031234567')
        self.assertEqual(normalize_phone('+234 803 123 4567'), '2348031234567')
        self.assertEqual(normalize_phone('12'), '')
