from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from audit.models import AuditLog
from authentication.models import User
from billing.models import CorporateAccount
from booking.models import Booking
from booking.policies import cancellation_penalty
from payments.testing import FakeGatewayMixin
from rates.engine import STAFF, WEBSITE, quote_plans
from rates.models import RatePlan, RatePlanPrice, RateRestriction
from rooms.models import Room, RoomType


@override_settings(REQUIRE_GUEST_ID_AT_CHECK_IN=False)
class RatesTestCase(FakeGatewayMixin, APITestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.today = timezone.localdate()
        self.check_in = self.today + timedelta(days=10)
        self.check_out = self.check_in + timedelta(days=2)
        self.standard = RoomType.objects.create(
            name='Standard', description='', base_price=Decimal('100000'), max_adults=2, max_children=1,
            bed_type='KING', bed_count=1, size=300,
        )
        self.suite = RoomType.objects.create(
            name='Suite', description='', base_price=Decimal('300000'), max_adults=2, max_children=1,
            bed_type='KING', bed_count=1, size=600,
        )
        Room.objects.create(room_number='101', room_type=self.standard, floor_number=1)
        Room.objects.create(room_number='501', room_type=self.suite, floor_number=5)
        self.bar = RatePlan.objects.get(code='BAR')
        self.bb = RatePlan.objects.create(code='bb', name='Bed & Breakfast', meal_plan='BB', adjustment_percent=Decimal('12'))
        self.nonref = RatePlan.objects.create(code='saver', name='Advance Saver', adjustment_percent=Decimal('-15'),
                                              is_refundable=False, min_advance_days=7)
        self.manager = User.objects.create_user('gm@hotel.com', 'G', 'M', 'x', role='manager')
        self.receptionist = User.objects.create_user('desk@hotel.com', 'D', 'K', 'x', role='receptionist')

    def codes(self, room_type=None, **kwargs):
        return [q.plan.code for q in quote_plans(room_type or self.standard, self.check_in, self.check_out, **kwargs)]


class PricingTests(RatesTestCase):
    def test_derived_plans_and_ordering(self):
        quotes = quote_plans(self.standard, self.check_in, self.check_out)
        self.assertEqual([(q.plan.code, q.total) for q in quotes], [
            ('saver', Decimal('170000.00')), ('BAR', Decimal('200000.00')), ('bb', Decimal('224000.00')),
        ])

    def test_fixed_plan_needs_a_price_for_every_night(self):
        package = RatePlan.objects.create(code='honeymoon', name='Honeymoon', pricing='FIXED')
        package.room_types.add(self.suite)
        RatePlanPrice.objects.create(rate_plan=package, room_type=self.suite, start_date=self.check_in,
                                     end_date=self.check_in, price=Decimal('250000'))
        self.assertNotIn('honeymoon', self.codes(self.suite))  # second night unpriced
        RatePlanPrice.objects.create(rate_plan=package, room_type=self.suite, start_date=self.check_in + timedelta(days=1),
                                     end_date=self.check_out, price=Decimal('260000'))
        quote = next(q for q in quote_plans(self.suite, self.check_in, self.check_out) if q.plan.code == 'honeymoon')
        self.assertEqual(quote.total, Decimal('510000'))
        self.assertNotIn('honeymoon', self.codes(self.standard))  # suites only

    def test_advance_purchase_and_stay_length(self):
        self.check_in = self.today + timedelta(days=3)
        self.check_out = self.check_in + timedelta(days=1)
        self.assertNotIn('saver', self.codes())
        self.bb.min_stay = 2
        self.bb.save()
        self.assertNotIn('bb', self.codes())


class AccessTests(RatesTestCase):
    def test_promo_codes(self):
        RatePlan.objects.create(code='detty', name='Detty December', adjustment_percent=Decimal('-20'), promo_code='detty25')
        self.assertNotIn('detty', self.codes())
        self.assertIn('detty', self.codes(promo_code=' Detty25 '))

    def test_corporate_rates_only_for_that_company(self):
        shell = CorporateAccount.objects.create(code='shell', name='Shell Nigeria')
        other = CorporateAccount.objects.create(code='mtn', name='MTN')
        RatePlan.objects.create(code='shell-corp', name='Shell negotiated', adjustment_percent=Decimal('-25'),
                                corporate_account=shell, is_public=False)
        self.assertNotIn('shell-corp', self.codes(channel=STAFF))
        self.assertNotIn('shell-corp', self.codes(channel=STAFF, account=other))
        self.assertIn('shell-corp', self.codes(channel=STAFF, account=shell))

    def test_private_plans_hidden_online(self):
        self.bb.is_public = False
        self.bb.save()
        self.assertNotIn('bb', self.codes(channel=WEBSITE))
        self.assertIn('bb', self.codes(channel=STAFF))


class RestrictionTests(RatesTestCase):
    def test_stop_sell_closes_website_but_not_staff(self):
        RateRestriction.objects.create(start_date=self.check_in + timedelta(days=1), end_date=self.check_in + timedelta(days=1),
                                       stop_sell=True, note='Hotel buyout')
        self.assertEqual(self.codes(channel=WEBSITE), [])
        self.assertEqual(len(self.codes(channel=STAFF)), 3)

    def test_closed_to_arrival_and_departure(self):
        RateRestriction.objects.create(start_date=self.check_in, end_date=self.check_in, closed_to_arrival=True)
        self.assertEqual(self.codes(), [])
        RateRestriction.objects.all().delete()
        RateRestriction.objects.create(start_date=self.check_out, end_date=self.check_out, closed_to_departure=True,
                                       rate_plan=self.bb)
        self.assertEqual(self.codes(), ['saver', 'BAR'])

    def test_restriction_min_stay(self):
        RateRestriction.objects.create(start_date=self.check_in, end_date=self.check_in, min_stay=3, room_type=self.standard)
        self.assertEqual(self.codes(), [])
        self.assertEqual(len(self.codes(self.suite)), 3)


class BookingIntegrationTests(RatesTestCase):
    def search(self, **params):
        return self.client.get(reverse('room-type-search'), {
            'check_in': self.check_in.isoformat(), 'check_out': self.check_out.isoformat(), 'adults': 1, **params,
        })

    def test_search_lists_plans_with_taxes(self):
        standard = next(r for r in self.search().data['room_types'] if r['name'] == 'Standard')
        self.assertEqual([p['code'] for p in standard['rate_plans']], ['saver', 'BAR', 'bb'])
        self.assertEqual(standard['rate_plans'][0]['total_with_taxes'], '182750.00')  # 170,000 + 7.5%
        self.assertFalse(standard['rate_plans'][0]['is_refundable'])

    def book_online(self, plan_code, **extra):
        return self.client.post(reverse('create-booking'), {
            'guest': {'first_name': 'Ada', 'last_name': 'Obi', 'email': 'ada@example.com'},
            'room_type': self.standard.id, 'check_in_date': self.check_in.isoformat(),
            'check_out_date': self.check_out.isoformat(), 'number_of_adults': 1, 'gateway': 'PAYSTACK',
            'rate_plan': plan_code, **extra,
        }, format='json')

    def test_online_booking_on_a_plan(self):
        response = self.book_online('bb')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['rate_plan']['code'], 'bb')
        self.assertEqual(response.data['total_price'], '224000.00')
        self.assertEqual(response.data['payment']['amount'], '240800.00')

    def test_online_booking_rejects_ineligible_plan(self):
        RatePlan.objects.create(code='secret', name='Secret', promo_code='VIP')
        response = self.book_online('secret')
        self.assertEqual(response.status_code, 400)
        self.assertIn('rate_plan', response.data)
        self.assertEqual(self.book_online('secret', promo_code='vip').status_code, 201)

    def test_non_refundable_cancellation_forfeits_stay(self):
        response = self.book_online('saver')
        booking = Booking.objects.get(confirmation_number=response.data['confirmation_number'])
        booking.status = Booking.Status.CONFIRMED
        self.assertEqual(cancellation_penalty(booking), Decimal('170000.00'))
        self.assertIn('Non-refundable', response.data['cancellation_policy'])

    def test_plan_specific_free_cancellation_window(self):
        flexible = RatePlan.objects.create(code='flex', name='Flexible', free_cancellation_hours=2)
        booking = Booking(rate_plan=flexible, check_in_date=self.today + timedelta(days=1),
                          check_out_date=self.today + timedelta(days=2), price_per_night=Decimal('100000'),
                          total_price=Decimal('100000'))
        self.assertEqual(cancellation_penalty(booking), Decimal('0.00'))  # 48h default would charge

    def reserve(self, **extra):
        return self.client.post(reverse('reservation-list'), {
            'guest': {'first_name': 'Musa', 'last_name': 'Bello', 'email': 'musa@example.com'},
            'check_in_date': self.check_in.isoformat(), 'check_out_date': self.check_out.isoformat(),
            'rooms': [{'room_type': self.standard.id, 'number_of_adults': 1}], **extra,
        }, format='json')

    def test_rate_override_requires_manager_and_reason(self):
        self.client.force_authenticate(self.receptionist)
        self.assertEqual(self.reserve(rate_override='60000', override_reason='Regular').status_code, 400)
        self.client.force_authenticate(self.manager)
        self.assertEqual(self.reserve(rate_override='60000').status_code, 400)  # no reason
        response = self.reserve(rate_override='60000', override_reason='Long-standing client')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data[0]['total_price'], '120000.00')
        entry = AuditLog.objects.filter(action=AuditLog.Action.BOOKING_CREATED).latest('id')
        self.assertEqual(entry.changes['override_reason'], 'Long-standing client')

    def test_extension_keeps_plan_pricing(self):
        self.client.force_authenticate(self.manager)
        booking_id = self.reserve(rate_plan=self.bb.pk).data[0]['id']
        response = self.client.patch(reverse('reservation-detail', args=[booking_id]), {
            'check_out_date': (self.check_out + timedelta(days=1)).isoformat(),
        }, format='json')
        self.assertEqual(response.data['total_price'], '336000.00')  # 3 x 112,000

    def test_corporate_booking_on_negotiated_rate(self):
        shell = CorporateAccount.objects.create(code='shell', name='Shell Nigeria')
        corp = RatePlan.objects.create(code='shell-corp', name='Shell', adjustment_percent=Decimal('-25'),
                                       corporate_account=shell, is_public=False)
        self.client.force_authenticate(self.receptionist)
        self.assertEqual(self.reserve(rate_plan=corp.pk).status_code, 400)
        response = self.reserve(rate_plan=corp.pk, corporate_account=shell.pk)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data[0]['total_price'], '150000.00')


class ManagementTests(RatesTestCase):
    def test_only_managers_change_rates_and_changes_are_audited(self):
        url = reverse('rate-plan-list')
        payload = {'code': 'weekend', 'name': 'Weekend', 'adjustment_percent': '-10'}
        self.client.force_authenticate(self.receptionist)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.post(url, payload, format='json').status_code, 403)
        self.client.force_authenticate(self.manager)
        self.assertEqual(self.client.post(url, payload, format='json').status_code, 201)
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.RATES_CHANGED).exists())

    def test_bar_cannot_be_discounted(self):
        self.client.force_authenticate(self.manager)
        response = self.client.patch(reverse('rate-plan-detail', args=[self.bar.pk]), {'adjustment_percent': '-5'},
                                     format='json')
        self.assertEqual(response.status_code, 400)
