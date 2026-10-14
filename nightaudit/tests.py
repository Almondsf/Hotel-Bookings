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
from billing.models import ChargeCategory, CorporateAccount, Folio
from booking.models import Booking
from hotel.clock import business_date
from nightaudit.models import BusinessDay
from rooms.models import Room, RoomAvailabilityOverride, RoomType


@override_settings(REQUIRE_GUEST_ID_AT_CHECK_IN=False)
class NightAuditTestCase(APITestCase):
    def setUp(self):
        cache.clear()
        self.today = timezone.localdate()
        self.room_type = RoomType.objects.create(
            name='Standard', description='', base_price=Decimal('100000'), max_adults=2, max_children=0,
            bed_type='KING', bed_count=1, size=300,
        )
        self.rooms = [Room.objects.create(room_number=str(100 + i), room_type=self.room_type, floor_number=1)
                      for i in range(1, 5)]
        self.manager = User.objects.create_user('gm@hotel.com', 'G', 'M', 'x', role='manager')
        self.desk = User.objects.create_user('desk@hotel.com', 'D', 'K', 'x', role='receptionist')
        self.client.force_authenticate(self.manager)

    def reserve(self, room, check_in=None, nights=2, email='ada@example.com'):
        check_in = check_in or business_date()
        response = self.client.post(reverse('reservation-list'), {
            'guest': {'first_name': 'Ada', 'last_name': 'Obi', 'email': email},
            'check_in_date': check_in.isoformat(), 'check_out_date': (check_in + timedelta(days=nights)).isoformat(),
            'rooms': [{'room_type': self.room_type.id, 'room': room.id, 'number_of_adults': 1}],
        }, format='json')
        assert response.status_code == 201, response.data
        return Booking.objects.get(pk=response.data[0]['id'])

    def check_in(self, booking):
        response = self.client.post(reverse('reservation-check-in', args=[booking.pk]), {}, format='json')
        assert response.status_code == 200, response.data

    def audit(self, **data):
        return self.client.post(reverse('night-audit'), data, format='json')


class NightAuditTests(NightAuditTestCase):
    def test_audit_posts_room_charges_and_rolls_the_business_date(self):
        booking = self.reserve(self.rooms[0], nights=3)
        self.check_in(booking)
        response = self.audit()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['room_charges_posted'], 1)
        self.assertEqual(business_date(), self.today + timedelta(days=1))
        self.assertEqual(booking.folio.charges.get().service_date, self.today)

        # Next night's audit posts the next night only
        self.audit()
        self.assertEqual(booking.folio.charges.count(), 2)
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.NIGHT_AUDIT_RUN).exists())

    def test_pending_arrivals_block_unless_marked_no_show(self):
        late = self.reserve(self.rooms[1], nights=2)
        blocked = self.audit()
        self.assertEqual(blocked.status_code, 409)
        exceptions = self.client.get(reverse('night-audit')).data['exceptions']
        self.assertEqual([b['confirmation_number'] for b in exceptions['pending_arrivals']], [late.confirmation_number])

        self.assertEqual(self.audit(auto_no_show=True).data['no_shows'], 1)
        late.refresh_from_db()
        self.assertEqual(late.status, 'NO_SHOW')
        self.assertEqual(late.folio.charges.get().category, 'PENALTY')

    def test_unchecked_departures_block(self):
        booking = self.reserve(self.rooms[0], nights=1)
        self.check_in(booking)
        self.audit()  # closes today; booking now due out on the new business date
        self.assertEqual(self.audit().status_code, 409)

    def test_late_arrival_after_midnight_belongs_to_business_day(self):
        # Before the audit runs the business date is still "today", whatever the clock says
        BusinessDay.objects.create(date=self.today - timedelta(days=1), status='OPEN')
        self.assertEqual(business_date(), self.today - timedelta(days=1))
        booking = self.reserve(self.rooms[2], check_in=self.today - timedelta(days=1), nights=2)
        self.check_in(booking)
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'CHECKED_IN')

    def test_permissions(self):
        self.client.force_authenticate(self.desk)
        self.assertEqual(self.client.get(reverse('night-audit')).status_code, 200)
        self.assertEqual(self.client.get(reverse('report-flash')).status_code, 403)


class ReportTests(NightAuditTestCase):
    def test_occupancy_adr_revpar_for_a_closed_day(self):
        for room in self.rooms[:2]:
            self.check_in(self.reserve(room, nights=2, email=f'{room.room_number}@example.com'))
        RoomAvailabilityOverride.objects.create(room=self.rooms[3], start_date=self.today,
                                                end_date=self.today + timedelta(days=1), reason='MAINTENANCE')
        self.audit()

        row = self.client.get(reverse('report-occupancy'), {'from': self.today.isoformat(), 'to': self.today.isoformat()}).data[0]
        self.assertTrue(row['actual'])
        self.assertEqual((row['rooms_available'], row['rooms_sold']), (3, 2))
        self.assertEqual(row['occupancy_percent'], 66.67)
        self.assertEqual(row['room_revenue'], Decimal('200000.00'))
        self.assertEqual(row['adr'], Decimal('100000.00'))
        self.assertEqual(row['revpar'], Decimal('66666.67'))

        flash = self.client.get(reverse('report-flash'), {'date': self.today.isoformat()}).data
        self.assertEqual(flash['source'], 'night_audit')
        self.assertEqual(flash['rooms_sold'], 2)
        self.assertEqual(flash['in_house'], 2)

    def test_forecast_from_bookings_on_the_books(self):
        future = self.today + timedelta(days=5)
        self.reserve(self.rooms[0], check_in=future, nights=2)
        row = self.client.get(reverse('report-occupancy'), {'from': future.isoformat(), 'to': future.isoformat()}).data[0]
        self.assertFalse(row['actual'])
        self.assertEqual(row['rooms_sold'], 1)
        self.assertEqual(row['room_revenue'], Decimal('100000.00'))

    def test_revenue_and_vat_report(self):
        folio = billing.open_non_guest_folio(name='Conference')
        billing.post_charge(folio, category=ChargeCategory.FOOD, description='Lunch', unit_price='200000')
        billing.post_charge(folio, category=ChargeCategory.BEVERAGE, description='Drinks', unit_price='50000')
        data = self.client.get(reverse('report-revenue')).data
        self.assertEqual({c['category']: c['net'] for c in data['categories']},
                         {'FOOD': Decimal('200000.00'), 'BEVERAGE': Decimal('50000.00')})
        self.assertEqual(data['taxes'], [{'code': 'vat', 'name': 'VAT', 'amount': Decimal('18750.00')}])

    def test_cashier_report_and_csv_export(self):
        folio = billing.open_non_guest_folio(name='=HYPERLINK("http://evil")')
        billing.post_charge(folio, category=ChargeCategory.FOOD, description='Dinner', unit_price='10000')
        billing.record_payment(folio, method='CASH', amount='10750', actor=self.desk)
        data = self.client.get(reverse('report-payments')).data
        self.assertEqual(data['total'], Decimal('10750.00'))
        self.assertEqual(data['by_staff'][0]['staff'], 'desk@hotel.com')

        ledger_csv = self.client.get(reverse('report-guest-ledger'), {'export': 'csv'})
        self.assertEqual(ledger_csv['Content-Type'], 'text/csv')
        self.assertIn("'=HYPERLINK", ledger_csv.content.decode())  # formula neutralised

    def test_city_ledger_aging(self):
        company = CorporateAccount.objects.create(code='mtn', name='MTN', credit_limit=Decimal('10000000'))
        folio = billing.open_non_guest_folio(name='MTN event')
        billing.post_charge(folio, category=ChargeCategory.MISC, description='Hall', unit_price='100000')
        billing.transfer_to_account(folio, company)
        Folio.objects.filter(pk=folio.pk).update(transferred_at=timezone.now() - timedelta(days=45))
        account = self.client.get(reverse('report-city-ledger')).data['accounts'][0]
        self.assertEqual((account['current'], account['31_60']), (Decimal('0.00'), Decimal('107500.00')))

    def test_report_range_limits(self):
        response = self.client.get(reverse('report-occupancy'), {'from': '2020-01-01', 'to': '2026-01-01'})
        self.assertEqual(response.status_code, 400)
