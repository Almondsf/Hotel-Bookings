from datetime import timedelta
from decimal import Decimal

from django.core import mail
from django.urls import reverse

from booking.models import Booking
from notifications.models import Notification
from notifications.services import send_pre_arrival_reminders
from rooms.models import Room

from .test_reservations import ReservationTestCase


class GroupTestCase(ReservationTestCase):
    """A three-room group booked by phone: two standards and a deluxe."""

    def reserve_group(self, check_in=None, nights=2):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.reserve(check_in=check_in, nights=nights, rooms=[
                {'room_type': self.standard.id, 'number_of_adults': 2},
                {'room_type': self.standard.id, 'number_of_adults': 1, 'number_of_children': 1},
                {'room_type': self.deluxe.id, 'number_of_adults': 2},
            ])
        self.assertEqual(response.status_code, 201, response.data)
        return response.data[0]['group_reference']

    def group_action(self, reference, name, **data):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse(f'booking-group-{name}', args=[reference]), data, format='json')

    def statuses(self, reference):
        return set(Booking.objects.filter(group__reference=reference).values_list('status', flat=True))


class GroupMessageTests(GroupTestCase):
    def test_one_confirmation_lists_every_room(self):
        reference = self.reserve_group()
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertIn(reference, message.subject)
        for booking in Booking.objects.filter(group__reference=reference):
            self.assertIn(booking.confirmation_number, message.body)
        self.assertIn('Rooms total:     NGN 800.00', message.body)
        self.assertFalse(Notification.objects.filter(template='booking_confirmed').exists())

    def test_single_rooms_keep_their_own_confirmation(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.reserve()
        self.assertEqual(list(Notification.objects.values_list('template', flat=True)), ['booking_confirmed'])

    def test_group_gets_one_pre_arrival_reminder(self):
        reference = self.reserve_group(check_in=self.today + timedelta(days=1))
        for _ in range(2):  # the job runs often; still one reminder
            with self.captureOnCommitCallbacks(execute=True):
                send_pre_arrival_reminders.call()
        reminders = Notification.objects.filter(template__in=['pre_arrival', 'group_pre_arrival'], channel='EMAIL')
        self.assertEqual(list(reminders.values_list('template', flat=True)), ['group_pre_arrival'])
        self.assertIn(reference, mail.outbox[-1].body)


class StaffGroupTests(GroupTestCase):
    def test_group_view_shows_every_room_and_totals(self):
        reference = self.reserve_group()
        response = self.client.get(reverse('booking-group-detail', args=[reference.lower()]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['reference'], reference)
        self.assertEqual(response.data['booker']['email'], 'chidi@example.com')
        self.assertEqual(sorted(b['room_number'] for b in response.data['bookings']), ['101', '102', '201'])
        totals = response.data['totals']
        self.assertEqual((totals['rooms'], totals['adults'], totals['children']), (3, 5, 1))
        self.assertEqual(Decimal(totals['total_price']), Decimal('800.00'))
        self.assertEqual(self.client.get(reverse('booking-group-detail', args=['GR-NOPE00'])).status_code, 404)

    def test_permissions(self):
        reference = self.reserve_group()
        self.client.force_authenticate(self.accountant)
        self.assertEqual(self.client.get(reverse('booking-group-detail', args=[reference])).status_code, 200)
        self.assertEqual(self.group_action(reference, 'cancel').status_code, 403)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(reverse('booking-group-detail', args=[reference])).status_code, 401)

    def test_check_in_whole_group_reports_a_room_that_is_not_ready(self):
        reference = self.reserve_group(check_in=self.today)
        Room.objects.filter(room_number='102').update(housekeeping_status=Room.Housekeeping.DIRTY)
        response = self.group_action(reference, 'check-in')
        self.assertEqual(response.status_code, 200, response.data)
        results = {r['room_number']: r for r in response.data['results']}
        self.assertTrue(results['101']['ok'] and results['201']['ok'])
        self.assertFalse(results['102']['ok'])
        self.assertIn('dirty', results['102']['error'])
        self.assertEqual(response.data['group']['totals']['by_status'], {'CHECKED_IN': 2, 'CONFIRMED': 1})

        # Once housekeeping is done, checking in again picks up the room left behind
        Room.objects.filter(room_number='102').update(housekeeping_status=Room.Housekeeping.CLEAN)
        self.assertEqual([r['room_number'] for r in self.group_action(reference, 'check-in').data['results']], ['102'])
        self.assertEqual(self.statuses(reference), {'CHECKED_IN'})

    def test_check_in_before_arrival_is_refused(self):
        reference = self.reserve_group()
        response = self.group_action(reference, 'check-in')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.statuses(reference), {'CONFIRMED'})

    def test_check_out_whole_group_sends_one_thank_you_with_every_invoice(self):
        reference = self.reserve_group(check_in=self.today, nights=1)
        self.group_action(reference, 'check-in')
        # Two rooms settle their bills; the third still owes, so it stays in house
        for booking in Booking.objects.filter(group__reference=reference).exclude(room__room_number='201'):
            folio = self.act(booking, 'post-room-charges').data['folio']
            self.client.post(reverse('folio-payments', args=[folio['id']]),
                             {'method': 'CASH', 'amount': folio['balance']}, format='json')
        mail.outbox.clear()

        response = self.group_action(reference, 'check-out')
        self.assertEqual(response.status_code, 200, response.data)
        results = {r['room_number']: r['ok'] for r in response.data['results']}
        self.assertEqual(results, {'101': True, '102': True, '201': False})
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual([a[2] for a in mail.outbox[0].attachments], ['application/pdf'] * 2)
        self.assertFalse(Notification.objects.filter(template='checked_out').exists())

    def test_cancel_whole_group_sends_one_message(self):
        reference = self.reserve_group()
        mail.outbox.clear()
        response = self.group_action(reference, 'cancel', reason='Event postponed')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(all(r['ok'] for r in response.data['results']))
        self.assertEqual(self.statuses(reference), {'CANCELLED'})
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(reference, mail.outbox[0].subject)
        self.assertEqual(self.group_action(reference, 'cancel').status_code, 409)  # nothing left to cancel


class GuestGroupTests(GroupTestCase):
    def setUp(self):
        super().setUp()
        self.reference = self.reserve_group()
        self.client.force_authenticate(None)

    def staff_reserves(self, **kwargs):
        self.client.force_authenticate(self.receptionist)
        reference = self.reserve_group(**kwargs)
        self.client.force_authenticate(None)
        return reference

    def post(self, name, **data):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse(f'group-{name}'), data, format='json')

    def test_lookup_needs_the_bookers_email(self):
        self.assertEqual(self.post('lookup', reference=self.reference, email='someone@else.com').status_code, 404)
        self.assertEqual(self.post('lookup', reference='GR-NOPE00', email='chidi@example.com').status_code, 404)
        self.assertEqual(self.post('lookup', reference=self.reference).status_code, 400)
        response = self.post('lookup', reference=self.reference.lower(), email='CHIDI@example.com')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['bookings']), 3)
        self.assertEqual(response.data['bookings'][0]['group_reference'], self.reference)
        self.assertEqual(response.data['totals']['cancellable_rooms'], 3)
        self.assertEqual(Decimal(response.data['totals']['cancellation_fee_if_cancelled_now']), Decimal('0.00'))

    def test_guest_cancels_the_whole_group(self):
        mail.outbox.clear()
        response = self.post('cancel', reference=self.reference, email='chidi@example.com', reason='Plans changed')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual({b['status'] for b in response.data['bookings']}, {'CANCELLED'})
        self.assertIsNone(response.data['totals']['cancellation_fee_if_cancelled_now'])
        self.assertEqual(len(mail.outbox), 1)
        # Wrong email can't cancel anything
        other = self.staff_reserves(check_in=self.today + timedelta(days=20))
        self.assertEqual(self.post('cancel', reference=other, email='x@example.com').status_code, 404)
        self.assertEqual(self.statuses(other), {'CONFIRMED'})

    def test_late_cancellation_charges_each_room_under_the_policy(self):
        late = self.staff_reserves(check_in=self.today + timedelta(days=1))
        fee = Decimal(self.post('lookup', reference=late, email='chidi@example.com').data['totals']
                      ['cancellation_fee_if_cancelled_now'])
        self.assertEqual(fee, Decimal('400.00'))  # one night of each room: 100 + 100 + 200
        self.post('cancel', reference=late, email='chidi@example.com')
        penalties = Booking.objects.filter(group__reference=late).values_list('penalty_amount', flat=True)
        self.assertEqual(sum(penalties), fee)
        self.assertIn('NGN 400.00', mail.outbox[-1].body)
