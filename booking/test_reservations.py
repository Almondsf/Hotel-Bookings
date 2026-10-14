from datetime import datetime, timedelta
from io import StringIO
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from audit.models import AuditLog
from payments.testing import FakeGatewayMixin
from authentication.models import User
from booking.lifecycle import expire_holds
from booking.models import Booking, Guest
from booking.policies import cancellation_penalty
from rooms.models import Room, RoomType
from rooms.services import get_available_rooms_for_type


def make_room_type(name, price, adults=2, children=1):
    return RoomType.objects.create(
        name=name, description=name, base_price=Decimal(price), max_adults=adults, max_children=children,
        bed_type='KING', bed_count=1, size=300,
    )


@override_settings(REQUIRE_GUEST_ID_AT_CHECK_IN=False)
class ReservationTestCase(APITestCase):
    def setUp(self):
        cache.clear()
        self.today = timezone.localdate()
        self.standard = make_room_type('Standard', '100.00')
        self.deluxe = make_room_type('Deluxe', '200.00')
        self.r101 = Room.objects.create(room_number='101', room_type=self.standard, floor_number=1)
        self.r102 = Room.objects.create(room_number='102', room_type=self.standard, floor_number=1)
        self.r201 = Room.objects.create(room_number='201', room_type=self.deluxe, floor_number=2)
        self.receptionist = User.objects.create_user('desk@hotel.com', 'Desk', 'Clerk', 'x', role='receptionist')
        self.accountant = User.objects.create_user('acc@hotel.com', 'Acc', 'Ountant', 'x', role='accountant')
        self.client.force_authenticate(self.receptionist)

    def reserve(self, check_in=None, nights=2, rooms=None, **extra):
        check_in = check_in or self.today + timedelta(days=7)
        payload = {
            'guest': {'first_name': 'Chidi', 'last_name': 'Eze', 'email': 'chidi@example.com', 'phone_number': '08030000000'},
            'check_in_date': check_in.isoformat(),
            'check_out_date': (check_in + timedelta(days=nights)).isoformat(),
            'rooms': rooms or [{'room_type': self.standard.id, 'number_of_adults': 2}],
            'source': 'PHONE',
            **extra,
        }
        return self.client.post(reverse('reservation-list'), payload, format='json')

    def booking(self, response):
        return Booking.objects.get(pk=response.data[0]['id'])

    def act(self, booking, name, **data):
        return self.client.post(reverse(f'reservation-{name}', args=[booking.pk]), data, format='json')


class StaffReservationTests(ReservationTestCase):
    def test_staff_reservation_is_confirmed_and_audited(self):
        response = self.reserve()
        self.assertEqual(response.status_code, 201, response.data)
        data = response.data[0]
        self.assertEqual(data['status'], 'CONFIRMED')
        self.assertEqual(data['source'], 'PHONE')
        self.assertEqual(data['created_by'], 'desk@hotel.com')
        self.assertEqual(Decimal(data['total_price']), Decimal('200.00'))
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.BOOKING_CREATED, actor=self.receptionist).exists())

    def test_group_reservation_allocates_distinct_rooms(self):
        response = self.reserve(rooms=[
            {'room_type': self.standard.id, 'number_of_adults': 2},
            {'room_type': self.standard.id, 'number_of_adults': 1, 'number_of_children': 1},
            {'room_type': self.deluxe.id, 'number_of_adults': 2},
        ])
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(sorted(r['room_number'] for r in response.data), ['101', '102', '201'])
        self.assertEqual(len({r['group_reference'] for r in response.data}), 1)
        self.assertTrue(response.data[0]['group_reference'].startswith('GR-'))

    def test_group_reservation_is_all_or_nothing(self):
        response = self.reserve(rooms=[{'room_type': self.standard.id, 'number_of_adults': 1}] * 3)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(Booking.objects.count(), 0)
        self.assertEqual(Guest.objects.count(), 0)

    def test_specific_room_request(self):
        response = self.reserve(rooms=[{'room_type': self.standard.id, 'room': self.r102.id, 'number_of_adults': 1}])
        self.assertEqual(response.data[0]['room_number'], '102')
        wrong_type = self.reserve(rooms=[{'room_type': self.standard.id, 'room': self.r201.id, 'number_of_adults': 1}])
        self.assertEqual(wrong_type.status_code, 400)

    def test_existing_guest_reused(self):
        guest = Guest.objects.create(first_name='Ngozi', last_name='Okafor', email='ngozi@example.com')
        response = self.reserve(guest=None, guest_id=guest.id)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data[0]['guest']['id'], guest.id)
        self.assertEqual(self.reserve(guest_id=guest.id).status_code, 400)  # both given

    def test_capacity_and_dates_validated(self):
        self.assertEqual(self.reserve(rooms=[{'room_type': self.standard.id, 'number_of_adults': 3}]).status_code, 400)
        self.assertEqual(self.reserve(check_in=self.today - timedelta(days=1)).status_code, 400)

    def test_permissions(self):
        self.client.force_authenticate(self.accountant)
        self.assertEqual(self.client.get(reverse('reservation-list')).status_code, 200)
        self.assertEqual(self.reserve().status_code, 403)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(reverse('reservation-list')).status_code, 401)

    def test_list_filters_and_search(self):
        self.reserve(check_in=self.today)
        self.reserve(check_in=self.today + timedelta(days=10), guest={'first_name': 'Bola', 'last_name': 'Ade', 'email': 'bola@example.com'})
        url = reverse('reservation-list')
        self.assertEqual(self.client.get(url, {'arrival': self.today.isoformat()}).data['count'], 1)
        self.assertEqual(self.client.get(url, {'q': 'bola'}).data['count'], 1)
        self.assertEqual(self.client.get(url, {'status': 'confirmed'}).data['count'], 2)
        self.assertEqual(self.client.get(url, {'arrival': 'not-a-date'}).status_code, 400)


class LifecycleTests(ReservationTestCase):
    def test_check_in_and_out(self):
        booking = self.booking(self.reserve(check_in=self.today))
        response = self.act(booking, 'check-in')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['status'], 'CHECKED_IN')
        booking.room.refresh_from_db()
        self.assertEqual(booking.room.status, Room.Status.OCCUPIED)

        self.assertEqual(self.act(booking, 'check-in').status_code, 409)  # twice

        # Can't leave owing money; the bill is brought up to date and paid first
        self.assertEqual(self.act(booking, 'check-out').status_code, 400)
        folio = self.act(booking, 'post-room-charges').data['folio']
        self.assertEqual(folio['balance'], '107.50')  # 1 night + 7.5% VAT
        self.client.post(reverse('folio-payments', args=[folio['id']]), {'method': 'CASH', 'amount': '107.50'}, format='json')
        self.assertEqual(self.act(booking, 'check-out').status_code, 200)
        booking.room.refresh_from_db()
        self.assertEqual(booking.room.status, Room.Status.AVAILABLE)
        self.assertEqual(self.act(booking, 'cancel').status_code, 409)  # terminal

    def test_cannot_check_in_before_arrival_date(self):
        booking = self.booking(self.reserve(check_in=self.today + timedelta(days=1)))
        self.assertEqual(self.act(booking, 'check-in').status_code, 400)

    def test_cannot_check_in_to_out_of_service_room(self):
        booking = self.booking(self.reserve(check_in=self.today))
        Room.objects.filter(pk=booking.room_id).update(status=Room.Status.OUT_OF_SERVICE)
        self.assertEqual(self.act(booking, 'check-in').status_code, 409)

    def test_free_cancellation_well_before_arrival(self):
        booking = self.booking(self.reserve(check_in=self.today + timedelta(days=10)))
        response = self.act(booking, 'cancel', reason='Plans changed')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'CANCELLED')
        self.assertEqual(Decimal(response.data['penalty_amount']), Decimal('0.00'))
        # Room is free again
        self.assertTrue(get_available_rooms_for_type(self.standard, booking.check_in_date, booking.check_out_date).filter(pk=booking.room_id).exists())

    def test_late_cancellation_charges_one_night_unless_waived(self):
        late = self.booking(self.reserve(check_in=self.today + timedelta(days=1), nights=3))
        response = self.act(late, 'cancel', reason='Flight cancelled')
        self.assertEqual(Decimal(response.data['penalty_amount']), Decimal('100.00'))

        waived = self.booking(self.reserve(check_in=self.today + timedelta(days=1), nights=3))
        self.assertEqual(self.act(waived, 'cancel', waive_penalty=True).status_code, 400)  # reason required
        response = self.act(waived, 'cancel', waive_penalty=True, reason='Loyal corporate client')
        self.assertEqual(Decimal(response.data['penalty_amount']), Decimal('0.00'))
        self.assertTrue(response.data['penalty_waived'])
        entry = AuditLog.objects.filter(action=AuditLog.Action.BOOKING_CANCELLED).latest('id')
        self.assertEqual(entry.changes['policy_penalty'], '100.00')
        self.assertTrue(entry.changes['waived'])

    def test_penalty_boundary_is_48_hours_before_check_in_time(self):
        booking = self.booking(self.reserve(check_in=self.today + timedelta(days=5)))
        arrival = timezone.make_aware(datetime.combine(booking.check_in_date, datetime.strptime('14:00', '%H:%M').time()))
        self.assertEqual(cancellation_penalty(booking, at=arrival - timedelta(hours=48)), Decimal('0.00'))
        self.assertEqual(cancellation_penalty(booking, at=arrival - timedelta(hours=47, minutes=59)), Decimal('100.00'))

    def test_no_show(self):
        future = self.booking(self.reserve(check_in=self.today + timedelta(days=3)))
        self.assertEqual(self.act(future, 'no-show').status_code, 400)
        today = self.booking(self.reserve(check_in=self.today))
        response = self.act(today, 'no-show')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'NO_SHOW')
        self.assertEqual(Decimal(response.data['penalty_amount']), Decimal('100.00'))


class ModificationTests(ReservationTestCase):
    def modify(self, booking, **changes):
        return self.client.patch(reverse('reservation-detail', args=[booking.pk]), changes, format='json')

    def test_extend_stay_keeps_room_and_reprices(self):
        booking = self.booking(self.reserve(nights=2))
        response = self.modify(booking, check_out_date=(booking.check_out_date + timedelta(days=1)).isoformat())
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['room_number'], booking.room.room_number)
        self.assertEqual(Decimal(response.data['total_price']), Decimal('300.00'))
        entry = AuditLog.objects.get(action=AuditLog.Action.BOOKING_MODIFIED)
        self.assertEqual(entry.changes['total_price'], {'from': '200.00', 'to': '300.00'})

    def test_date_change_moves_to_free_room_when_own_room_is_taken(self):
        booking = self.booking(self.reserve(nights=2, rooms=[{'room_type': self.standard.id, 'room': self.r101.id, 'number_of_adults': 1}]))
        # Someone else has 101 the night after
        self.reserve(check_in=booking.check_out_date, nights=1,
                     rooms=[{'room_type': self.standard.id, 'room': self.r101.id, 'number_of_adults': 1}])
        response = self.modify(booking, check_out_date=(booking.check_out_date + timedelta(days=1)).isoformat())
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['room_number'], '102')

    def test_upgrade_room_type(self):
        booking = self.booking(self.reserve(nights=2))
        response = self.modify(booking, room_type=self.deluxe.id)
        self.assertEqual(response.data['room_number'], '201')
        self.assertEqual(Decimal(response.data['total_price']), Decimal('400.00'))

    def test_modification_unavailable(self):
        booking = self.booking(self.reserve(nights=2))
        self.reserve(rooms=[{'room_type': self.deluxe.id, 'number_of_adults': 1}])
        self.assertEqual(self.modify(booking, room_type=self.deluxe.id).status_code, 409)

    def test_in_house_guest_can_extend_but_not_change_arrival(self):
        booking = self.booking(self.reserve(check_in=self.today))
        self.act(booking, 'check-in')
        self.assertEqual(self.modify(booking, check_in_date=(self.today + timedelta(days=1)).isoformat()).status_code, 400)
        self.assertEqual(self.modify(booking, check_out_date=(booking.check_out_date + timedelta(days=1)).isoformat()).status_code, 200)

    def test_cannot_modify_cancelled_booking(self):
        booking = self.booking(self.reserve())
        self.act(booking, 'cancel')
        self.assertEqual(self.modify(booking, number_of_adults=1).status_code, 409)


class HoldExpiryTests(FakeGatewayMixin, ReservationTestCase):
    def online_booking(self):
        self.client.force_authenticate(None)
        check_in = self.today + timedelta(days=5)
        response = self.client.post(reverse('create-booking'), {
            'guest': {'first_name': 'Ada', 'last_name': 'Obi', 'email': 'ada@example.com'},
            'room_type': self.deluxe.id,
            'check_in_date': check_in.isoformat(),
            'check_out_date': (check_in + timedelta(days=1)).isoformat(),
            'number_of_adults': 1, 'number_of_children': 0, 'gateway': 'PAYSTACK',
        }, format='json')
        return Booking.objects.get(confirmation_number=response.data['confirmation_number'])

    def test_pending_hold_blocks_until_expiry(self):
        booking = self.online_booking()
        self.assertEqual(booking.status, 'PENDING')
        self.assertIsNotNone(booking.hold_expires_at)
        available = lambda: get_available_rooms_for_type(self.deluxe, booking.check_in_date, booking.check_out_date).exists()
        self.assertFalse(available())

        Booking.objects.filter(pk=booking.pk).update(hold_expires_at=timezone.now() - timedelta(seconds=1))
        self.assertTrue(available())  # an expired hold no longer blocks, even before cleanup

        call_command('expire_holds', stdout=StringIO())
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'CANCELLED')
        self.assertEqual(booking.cancellation_reason, 'Payment hold expired')
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.BOOKING_HOLD_EXPIRED).exists())

    def test_unexpired_holds_are_kept(self):
        booking = self.online_booking()
        self.assertEqual(expire_holds(), 0)
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'PENDING')


class GuestSelfServiceTests(ReservationTestCase):
    def test_guest_can_cancel_with_confirmation_and_email(self):
        booking = self.booking(self.reserve(check_in=self.today + timedelta(days=10)))
        self.client.force_authenticate(None)
        url = reverse('booking-cancel')
        wrong = self.client.post(url, {'confirmation_number': booking.confirmation_number, 'email': 'x@example.com'}, format='json')
        self.assertEqual(wrong.status_code, 404)

        response = self.client.post(url, {'confirmation_number': booking.confirmation_number, 'email': 'chidi@example.com'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'CANCELLED')
        entry = AuditLog.objects.get(action=AuditLog.Action.BOOKING_CANCELLED)
        self.assertEqual(entry.actor_email, 'chidi@example.com')
        self.assertTrue(entry.changes['by_guest'])

    def test_lookup_shows_cancellation_terms(self):
        booking = self.booking(self.reserve(check_in=self.today + timedelta(days=1)))
        self.client.force_authenticate(None)
        response = self.client.post(reverse('booking-lookup'), {
            'confirmation_number': booking.confirmation_number, 'email': 'chidi@example.com',
        }, format='json')
        self.assertEqual(response.data['cancellation_fee_if_cancelled_now'], '100.00')
        self.assertIn('48 hours', response.data['cancellation_policy'])


class SummaryTests(ReservationTestCase):
    def test_front_desk_summary(self):
        arriving = self.booking(self.reserve(check_in=self.today, nights=1))
        self.reserve(check_in=self.today, nights=2, rooms=[{'room_type': self.deluxe.id, 'number_of_adults': 1}])
        self.act(arriving, 'check-in')
        Room.objects.filter(pk=self.r102.pk).update(status=Room.Status.OUT_OF_SERVICE)

        data = self.client.get(reverse('reservation-summary')).data
        self.assertEqual(data['arrivals_expected'], 1)
        self.assertEqual(data['arrivals_checked_in'], 1)
        self.assertEqual(data['in_house'], 1)
        self.assertEqual(data['sellable_rooms'], 2)
        self.assertEqual(data['occupied_tonight'], 2)
        self.assertEqual(data['occupancy_percent'], 100.0)


class GuestSearchTests(ReservationTestCase):
    def test_guest_search_requires_query(self):
        Guest.objects.create(first_name='Ngozi', last_name='Okafor', email='ngozi@example.com')
        url = reverse('guest-list')
        self.assertEqual(self.client.get(url).data['count'], 0)
        self.assertEqual(self.client.get(url, {'q': 'okaf'}).data['count'], 1)
