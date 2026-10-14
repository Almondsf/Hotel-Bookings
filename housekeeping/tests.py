from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from audit.models import AuditLog
from authentication.models import User
from billing import services as billing
from booking.models import Booking
from housekeeping.models import HousekeepingTask
from housekeeping.services import generate_daily_tasks
from maintenance.models import MaintenanceTicket
from rooms.models import Room, RoomAvailabilityOverride, RoomType
from rooms.services import get_available_rooms_for_type


@override_settings(REQUIRE_GUEST_ID_AT_CHECK_IN=False, CHECKOUT_REQUIRES_SETTLED_FOLIO=False)
class OperationsTestCase(APITestCase):
    def setUp(self):
        cache.clear()
        self.today = timezone.localdate()
        self.room_type = RoomType.objects.create(
            name='Standard', description='', base_price=Decimal('50000'), max_adults=2, max_children=0,
            bed_type='KING', bed_count=1, size=300,
        )
        self.r101 = Room.objects.create(room_number='101', room_type=self.room_type, floor_number=1)
        self.r102 = Room.objects.create(room_number='102', room_type=self.room_type, floor_number=1)
        self.r103 = Room.objects.create(room_number='103', room_type=self.room_type, floor_number=1)
        self.manager = User.objects.create_user('gm@hotel.com', 'G', 'M', 'x', role='manager')
        self.desk = User.objects.create_user('desk@hotel.com', 'D', 'K', 'x', role='receptionist')
        self.attendant = User.objects.create_user('hk@hotel.com', 'Blessing', 'Udo', 'x', role='housekeeping')
        self.engineer = User.objects.create_user('eng@hotel.com', 'Sule', 'Garba', 'x', role='maintenance')
        self.client.force_authenticate(self.desk)

    def reserve(self, room, check_in=None, nights=2):
        check_in = check_in or self.today
        response = self.client.post(reverse('reservation-list'), {
            'guest': {'first_name': 'Ada', 'last_name': 'Obi', 'email': f'ada{room.pk}{nights}@example.com'},
            'check_in_date': check_in.isoformat(), 'check_out_date': (check_in + timedelta(days=nights)).isoformat(),
            'rooms': [{'room_type': self.room_type.id, 'room': room.id, 'number_of_adults': 1}],
        }, format='json')
        assert response.status_code == 201, response.data
        return Booking.objects.get(pk=response.data[0]['id'])

    def act(self, booking, name, data=None):
        return self.client.post(reverse(f'reservation-{name}', args=[booking.pk]), data or {}, format='json')


class RoomReadinessTests(OperationsTestCase):
    def test_check_out_dirties_room_and_blocks_next_check_in(self):
        first = self.reserve(self.r101, nights=1)
        self.act(first, 'check-in')
        self.act(first, 'check-out')
        self.r101.refresh_from_db()
        self.assertEqual(self.r101.housekeeping_status, 'DIRTY')

        second = self.reserve(self.r101, nights=1)
        response = self.act(second, 'check-in')
        self.assertEqual(response.status_code, 409)
        self.assertIn('housekeeping', response.data['error'])

        # Attendant cleans it, then check-in works
        generate_daily_tasks()
        task = HousekeepingTask.objects.get(room=self.r101)
        self.client.force_authenticate(self.attendant)
        self.client.post(reverse('housekeeping-task-complete', args=[task.pk]), {}, format='json')
        self.client.force_authenticate(self.desk)
        self.assertEqual(self.act(second, 'check-in').status_code, 200)

    @override_settings(REQUIRE_ROOM_INSPECTION=True)
    def test_inspection_required_mode(self):
        Room.objects.filter(pk=self.r101.pk).update(housekeeping_status='CLEAN')
        booking = self.reserve(self.r101, nights=1)
        self.assertEqual(self.act(booking, 'check-in').status_code, 409)
        self.client.force_authenticate(self.manager)
        self.client.post(reverse('housekeeping-room-status', args=[self.r101.pk]), {'housekeeping_status': 'INSPECTED'}, format='json')
        self.assertEqual(self.act(booking, 'check-in').status_code, 200)

    def test_in_house_room_move_dirties_old_room(self):
        booking = self.reserve(self.r101)
        self.act(booking, 'check-in')
        self.act(booking, 'move-room', {'room': self.r102.id, 'reason': 'AC fault'})
        self.r101.refresh_from_db()
        self.assertEqual(self.r101.housekeeping_status, 'DIRTY')


class TaskTests(OperationsTestCase):
    def test_daily_tasks_cover_departures_stayovers_and_rush_rooms(self):
        staying = self.reserve(self.r101, nights=3)
        self.act(staying, 'check-in')
        leaving = self.reserve(self.r102, nights=1)
        # Arrived yesterday, leaves today
        Booking.objects.filter(pk=leaving.pk).update(
            status='CHECKED_IN', check_in_date=self.today - timedelta(days=1), check_out_date=self.today)
        Room.objects.filter(pk=self.r103.pk).update(housekeeping_status='DIRTY')
        self.reserve(self.r103, nights=1)  # guest arriving into a dirty room

        self.assertEqual(generate_daily_tasks(), 3)
        self.assertEqual(generate_daily_tasks(), 0)  # idempotent
        tasks = {t.room.room_number: t for t in HousekeepingTask.objects.select_related('room')}
        self.assertEqual(tasks['101'].task_type, 'STAYOVER')
        self.assertEqual(tasks['102'].task_type, 'DEPARTURE_CLEAN')
        self.assertTrue(tasks['103'].is_rush)

    def test_attendant_workflow_and_permissions(self):
        Room.objects.filter(pk=self.r101.pk).update(housekeeping_status='DIRTY')
        self.client.force_authenticate(self.manager)
        self.client.post(reverse('housekeeping-task-generate'), {}, format='json')
        task = HousekeepingTask.objects.get()

        # Assignment is for supervisors, and only to housekeeping staff
        url = reverse('housekeeping-task-detail', args=[task.pk])
        self.assertEqual(self.client.patch(url, {'assigned_to': self.desk.pk}, format='json').status_code, 400)
        self.assertEqual(self.client.patch(url, {'assigned_to': self.attendant.pk}, format='json').status_code, 200)

        self.client.force_authenticate(self.desk)
        self.assertEqual(self.client.post(reverse('housekeeping-task-start', args=[task.pk])).status_code, 403)

        self.client.force_authenticate(self.attendant)
        mine = self.client.get(reverse('housekeeping-task-list'), {'mine': 'true'}).data
        self.assertEqual([t['room_number'] for t in mine], ['101'])
        self.assertEqual(self.client.post(reverse('housekeeping-task-start', args=[task.pk])).status_code, 200)
        done = self.client.post(reverse('housekeeping-task-complete', args=[task.pk]), {'notes': 'Changed linen'}, format='json')
        self.assertEqual(done.data['status'], 'DONE')
        self.assertEqual(done.data['room_status'], 'CLEAN')
        self.assertEqual(self.client.post(reverse('housekeeping-task-complete', args=[task.pk])).status_code, 409)

    def test_skip_needs_reason(self):
        booking = self.reserve(self.r101, nights=3)
        self.act(booking, 'check-in')
        generate_daily_tasks()
        task = HousekeepingTask.objects.get()
        self.client.force_authenticate(self.attendant)
        url = reverse('housekeeping-task-skip', args=[task.pk])
        self.assertEqual(self.client.post(url, {}, format='json').status_code, 400)
        self.assertEqual(self.client.post(url, {'reason': 'Do not disturb'}, format='json').status_code, 200)

    def test_room_status_board(self):
        Room.objects.filter(pk=self.r102.pk).update(housekeeping_status='DIRTY')
        data = self.client.get(reverse('housekeeping-rooms')).data
        self.assertEqual({r['room_number']: r['housekeeping_status'] for r in data}['102'], 'DIRTY')
        # Front desk can see, not change
        response = self.client.post(reverse('housekeeping-room-status', args=[self.r102.pk]),
                                    {'housekeeping_status': 'CLEAN'}, format='json')
        self.assertEqual(response.status_code, 403)
        self.client.force_authenticate(self.manager)
        self.client.post(reverse('housekeeping-room-status', args=[self.r102.pk]), {'housekeeping_status': 'CLEAN'}, format='json')
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.ROOM_HOUSEKEEPING_CHANGED).exists())


class MaintenanceTests(OperationsTestCase):
    def report(self, **extra):
        return self.client.post(reverse('maintenance-ticket-list'), {
            'room': self.r101.pk, 'title': 'AC leaking', 'category': 'HVAC', 'priority': 'HIGH', **extra,
        }, format='json')

    def test_any_staff_can_report(self):
        self.client.force_authenticate(self.attendant)
        response = self.report()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data['number'].startswith('MT-'))
        self.assertEqual(self.client.post(reverse('maintenance-ticket-start', args=[response.data['id']])).status_code, 403)

    def test_public_area_needs_location(self):
        response = self.client.post(reverse('maintenance-ticket-list'), {'title': 'Flickering light'}, format='json')
        self.assertEqual(response.status_code, 400)
        response = self.client.post(reverse('maintenance-ticket-list'), {'title': 'Flickering light', 'location': 'Lobby'},
                                    format='json')
        self.assertEqual(response.status_code, 201)

    def test_out_of_order_blocks_sales_and_lists_bookings_to_move(self):
        future = self.reserve(self.r101, check_in=self.today + timedelta(days=2), nights=2)
        response = self.report(out_of_order_until=(self.today + timedelta(days=5)).isoformat())
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual([b['confirmation_number'] for b in response.data['bookings_to_move']], [future.confirmation_number])

        self.r101.refresh_from_db()
        self.assertEqual(self.r101.status, 'MAINTENANCE')
        free = get_available_rooms_for_type(self.room_type, self.today + timedelta(days=3), self.today + timedelta(days=4))
        self.assertNotIn(self.r101, free)

        # Engineer fixes it: room back on sale, sent for cleaning
        self.client.force_authenticate(self.engineer)
        ticket_id = response.data['id']
        self.client.post(reverse('maintenance-ticket-start', args=[ticket_id]))
        self.assertEqual(self.client.post(reverse('maintenance-ticket-resolve', args=[ticket_id]), {}, format='json').status_code, 400)
        resolved = self.client.post(reverse('maintenance-ticket-resolve', args=[ticket_id]),
                                    {'resolution_notes': 'Replaced drain pipe'}, format='json')
        self.assertEqual(resolved.data['status'], 'RESOLVED')
        self.r101.refresh_from_db()
        self.assertEqual((self.r101.status, self.r101.housekeeping_status), ('AVAILABLE', 'DIRTY'))
        self.assertFalse(RoomAvailabilityOverride.objects.filter(end_date__gt=self.today).exists())
        self.assertEqual(self.client.post(reverse('maintenance-ticket-resolve', args=[ticket_id]),
                                          {'resolution_notes': 'x'}, format='json').status_code, 409)

    def test_occupied_room_stays_occupied_when_put_out_of_order(self):
        booking = self.reserve(self.r101)
        self.act(booking, 'check-in')
        self.report(out_of_order_until=(self.today + timedelta(days=3)).isoformat())
        self.r101.refresh_from_db()
        self.assertEqual(self.r101.status, 'OCCUPIED')
        self.assertEqual(MaintenanceTicket.objects.get().out_of_order.room, self.r101)

    def test_out_of_order_must_end_in_future(self):
        self.assertEqual(self.report(out_of_order_until=self.today.isoformat()).status_code, 400)


class BillingStillBalancesTests(OperationsTestCase):
    def test_folio_unaffected_by_housekeeping(self):
        booking = self.reserve(self.r101, nights=1)
        self.act(booking, 'check-in')
        self.assertEqual(billing.folio_for(booking).balance, Decimal('0.00'))
