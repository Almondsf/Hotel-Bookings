from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from audit.models import AuditLog
from authentication.models import User
from billing import services
from payments.testing import FakeGatewayMixin
from billing.models import Charge, ChargeCategory, CorporateAccount, ExchangeRate, Folio, Invoice, TaxRule
from booking.models import Booking
from rooms.models import Room, RoomType


@override_settings(REQUIRE_GUEST_ID_AT_CHECK_IN=False)
class BillingTestCase(APITestCase):
    def setUp(self):
        cache.clear()
        self.today = timezone.localdate()
        self.room_type = RoomType.objects.create(
            name='Standard', description='Standard', base_price=Decimal('50000.00'), max_adults=2, max_children=1,
            bed_type='KING', bed_count=1, size=300,
        )
        Room.objects.create(room_number='101', room_type=self.room_type, floor_number=1)
        Room.objects.create(room_number='102', room_type=self.room_type, floor_number=1)
        self.receptionist = User.objects.create_user('desk@hotel.com', 'Desk', 'Clerk', 'x', role='receptionist')
        self.accountant = User.objects.create_user('acc@hotel.com', 'Acc', 'Ountant', 'x', role='accountant')
        self.client.force_authenticate(self.receptionist)

    def reserve(self, check_in=None, nights=2):
        check_in = check_in or self.today
        response = self.client.post(reverse('reservation-list'), {
            'guest': {'first_name': 'Tunde', 'last_name': 'Bakare', 'email': 'tunde@example.com'},
            'check_in_date': check_in.isoformat(),
            'check_out_date': (check_in + timedelta(days=nights)).isoformat(),
            'rooms': [{'room_type': self.room_type.id, 'number_of_adults': 1}],
        }, format='json')
        assert response.status_code == 201, response.data
        return Booking.objects.get(pk=response.data[0]['id'])

    def in_house(self, nights=2):
        booking = self.reserve(nights=nights)
        self.client.post(reverse('reservation-check-in', args=[booking.pk]), {}, format='json')
        return booking

    def folio_url(self, folio, action=None, **kwargs):
        if action is None:
            return reverse('folio-detail', args=[folio.pk])
        return reverse(f'folio-{action}', args=[folio.pk, *kwargs.values()])

    def pay(self, folio, amount, method='CASH', **extra):
        return self.client.post(self.folio_url(folio, 'payments'),
                                {'method': method, 'amount': str(amount), **extra}, format='json')


class TaxTests(BillingTestCase):
    def test_vat_applies_by_default_and_other_levies_when_enabled(self):
        folio = services.open_non_guest_folio(name='Walk-in diner')
        charge = services.post_charge(folio, category=ChargeCategory.FOOD, description='Jollof', unit_price='10000')
        self.assertEqual(charge.tax_amount, Decimal('750.00'))
        self.assertEqual(charge.total_amount, Decimal('10750.00'))

        TaxRule.objects.filter(code='service-charge').update(is_active=True)
        charge = services.post_charge(folio, category=ChargeCategory.FOOD, description='Suya', unit_price='10000')
        self.assertEqual(charge.tax_amount, Decimal('1750.00'))  # 7.5% + 10% on net, no tax-on-tax
        self.assertEqual([line['code'] for line in charge.tax_lines], ['vat', 'service-charge'])

    def test_rate_change_does_not_rewrite_history(self):
        folio = services.open_non_guest_folio(name='Bar tab')
        old = services.post_charge(folio, category=ChargeCategory.BEVERAGE, description='Chapman', unit_price='4000')
        TaxRule.objects.filter(code='vat').update(rate=Decimal('0.1000'))
        old.refresh_from_db()
        self.assertEqual(old.tax_amount, Decimal('300.00'))
        self.assertEqual(old.tax_lines[0]['rate'], '0.0750')

    def test_penalties_are_not_taxed(self):
        folio = services.open_non_guest_folio(name='x')
        charge = services.post_charge(folio, category=ChargeCategory.PENALTY, description='Fee', unit_price='5000')
        self.assertEqual(charge.tax_amount, Decimal('0.00'))

    def test_tax_rule_management(self):
        rule = TaxRule.objects.get(code='vat')
        url = reverse('tax-rule-detail', args=[rule.pk])
        self.assertEqual(self.client.patch(url, {'rate': '0.08'}, format='json').status_code, 403)
        self.client.force_authenticate(self.accountant)
        self.assertEqual(self.client.patch(url, {'categories': ['ROOM', 'NOPE']}, format='json').status_code, 400)
        self.assertEqual(self.client.patch(url, {'rate': '0.08'}, format='json').status_code, 200)
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.BILLING_CONFIGURED).exists())


class ChargeTests(BillingTestCase):
    def test_room_charges_post_each_night_once(self):
        booking = self.in_house(nights=3)
        services.post_room_charges(booking, through_date=self.today + timedelta(days=2))
        services.post_room_charges(booking, through_date=self.today + timedelta(days=2))
        folio = booking.folio
        self.assertEqual(folio.charges.count(), 3)
        self.assertEqual(folio.balance, Decimal('161250.00'))  # 3 x 50,000 + 7.5%

    def test_database_rejects_double_posting_a_night(self):
        booking = self.in_house(nights=1)
        services.post_room_charges(booking, through_date=self.today)
        night = booking.nightly_rates.get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Charge.objects.create(folio=booking.folio, category='ROOM', description='dup', unit_price=1,
                                  net_amount=1, total_amount=1, service_date=self.today, booking_night=night)

    def test_void_requires_adjust_capability_and_reason(self):
        folio = services.open_non_guest_folio(name='x')
        charge = services.post_charge(folio, category=ChargeCategory.MINIBAR, description='Water', unit_price='1500')
        url = self.folio_url(folio, 'void-charge', charge_id=charge.pk)
        self.assertEqual(self.client.post(url, {'reason': 'Wrong room'}, format='json').status_code, 403)
        self.client.force_authenticate(self.accountant)
        self.assertEqual(self.client.post(url, {}, format='json').status_code, 400)
        response = self.client.post(url, {'reason': 'Wrong room'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Decimal(response.data['balance']), Decimal('0.00'))
        self.assertTrue(Charge.objects.get(pk=charge.pk).is_void)  # kept, not deleted

    def test_allowances(self):
        folio = services.open_non_guest_folio(name='x')
        services.post_charge(folio, category=ChargeCategory.FOOD, description='Dinner', unit_price='20000')
        url = self.folio_url(folio, 'charges')
        allowance = {'category': 'ALLOWANCE', 'description': 'Service recovery', 'unit_price': '-5000'}
        self.assertEqual(self.client.post(url, allowance, format='json').status_code, 403)
        self.assertEqual(self.client.post(url, {**allowance, 'category': 'FOOD'}, format='json').status_code, 400)
        self.client.force_authenticate(self.accountant)
        self.assertEqual(self.client.post(url, allowance, format='json').status_code, 201)
        folio.refresh_from_db()
        self.assertEqual(folio.balance, Decimal('16125.00'))  # (20,000 - 5,000) x 1.075

    def test_staff_cannot_post_room_or_penalty_charges_by_hand(self):
        folio = services.open_non_guest_folio(name='x')
        for category in ['ROOM', 'PENALTY']:
            response = self.client.post(self.folio_url(folio, 'charges'),
                                        {'category': category, 'description': 'x', 'unit_price': '1'}, format='json')
            self.assertEqual(response.status_code, 400)

    def test_split_bill_by_transferring_a_charge(self):
        company_part = services.open_non_guest_folio(name='Company')
        guest_part = services.open_non_guest_folio(name='Guest extras')
        charge = services.post_charge(company_part, category=ChargeCategory.SPA, description='Massage', unit_price='30000')
        self.client.force_authenticate(self.accountant)
        response = self.client.post(self.folio_url(company_part, 'transfer-charge', charge_id=charge.pk),
                                    {'to_folio': guest_part.pk, 'reason': 'Personal expense'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(guest_part.balance, Decimal('32250.00'))
        self.assertEqual(company_part.balance, Decimal('0.00'))


class PaymentTests(BillingTestCase):
    def setUp(self):
        super().setUp()
        self.folio = services.open_non_guest_folio(name='Event client')
        services.post_charge(self.folio, category=ChargeCategory.MISC, description='Hall', unit_price='100000')

    def test_cash_payment(self):
        response = self.pay(self.folio, '107500')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(self.folio.balance, Decimal('0.00'))

    def test_card_and_transfer_need_reference(self):
        self.assertEqual(self.pay(self.folio, '1000', method='CARD_TERMINAL').status_code, 400)
        self.assertEqual(self.pay(self.folio, '1000', method='CARD_TERMINAL', reference='RRN 1234').status_code, 201)

    def test_staff_cannot_record_gateway_payments_by_hand(self):
        self.assertEqual(self.pay(self.folio, '1000', method='PAYSTACK').status_code, 400)

    def test_foreign_currency_converted_at_current_rate(self):
        self.assertEqual(self.client.post(self.folio_url(self.folio, 'payments'), {
            'method': 'CASH', 'currency': 'USD', 'tendered_amount': '50',
        }, format='json').status_code, 400)  # no rate yet

        self.client.force_authenticate(self.accountant)
        self.client.post(reverse('exchange-rate-list'), {'currency': 'usd', 'rate': '1500'}, format='json')
        self.client.post(reverse('exchange-rate-list'), {'currency': 'USD', 'rate': '1550'}, format='json')
        response = self.client.post(self.folio_url(self.folio, 'payments'), {
            'method': 'CASH', 'currency': 'USD', 'tendered_amount': '50',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Decimal(response.data['amount']), Decimal('77500.00'))
        self.assertEqual(Decimal(response.data['exchange_rate']), Decimal('1550'))
        self.assertEqual(ExchangeRate.objects.count(), 2)  # history kept

    def test_refund_limited_to_credit_and_to_finance_roles(self):
        self.pay(self.folio, '120000')  # overpaid by 12,500
        url = self.folio_url(self.folio, 'refunds')
        refund = {'amount': '12500', 'method': 'CASH', 'reason': 'Overpayment'}
        self.assertEqual(self.client.post(url, refund, format='json').status_code, 403)
        self.client.force_authenticate(self.accountant)
        self.assertEqual(self.client.post(url, {**refund, 'amount': '12500.01'}, format='json').status_code, 400)
        self.assertEqual(self.client.post(url, refund, format='json').status_code, 201)
        self.assertEqual(self.folio.balance, Decimal('0.00'))


class SettlementTests(BillingTestCase):
    def test_settle_issues_sequential_immutable_invoices(self):
        numbers = []
        for name in ['A', 'B']:
            folio = services.open_non_guest_folio(name=name)
            services.post_charge(folio, category=ChargeCategory.FOOD, description='Lunch', unit_price='10000')
            url = self.folio_url(folio, 'settle')
            self.assertEqual(self.client.post(url).status_code, 400)  # balance due
            self.pay(folio, '10750')
            response = self.client.post(url)
            self.assertEqual(response.status_code, 200, response.data)
            numbers.append(response.data['number'])

        year = timezone.localdate().year
        self.assertEqual(numbers, [f'INV-{year}-000001', f'INV-{year}-000002'])
        invoice = Invoice.objects.get(number=numbers[0])
        with self.assertRaises(RuntimeError):
            invoice.save()
        self.assertEqual(invoice.snapshot['totals']['balance'], '0.00')

        # Closed folios accept no more postings
        response = self.client.post(self.folio_url(invoice.folio, 'charges'),
                                    {'category': 'FOOD', 'description': 'Late', 'unit_price': '100'}, format='json')
        self.assertEqual(response.status_code, 409)

    def test_invoice_pdf(self):
        folio = services.open_non_guest_folio(name='<b>Mallory</b> & Co')
        services.post_charge(folio, category=ChargeCategory.FOOD, description='Fish <script>', unit_price='10000')
        self.pay(folio, '10750')
        invoice_id = Invoice.objects.get(number=self.client.post(self.folio_url(folio, 'settle')).data['number']).pk
        response = self.client.get(reverse('invoice-pdf', args=[invoice_id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_full_stay_check_out(self):
        booking = self.in_house(nights=2)
        # Early departure after 1 night: only that night is billed
        folio = self.client.post(reverse('reservation-post-room-charges', args=[booking.pk])).data['folio']
        self.assertEqual(Decimal(folio['balance']), Decimal('53750.00'))
        self.pay(Folio.objects.get(pk=folio['id']), '53750')
        response = self.client.post(reverse('reservation-check-out', args=[booking.pk]), {}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['folio']['status'], 'SETTLED')


class CityLedgerTests(BillingTestCase):
    def setUp(self):
        super().setUp()
        self.company = CorporateAccount.objects.create(code='dangote', name='Dangote Group', credit_limit=Decimal('100000'))

    def test_check_out_to_company_account(self):
        booking = self.in_house(nights=1)
        response = self.client.post(reverse('reservation-check-out', args=[booking.pk]),
                                    {'transfer_to_account': self.company.pk}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['folio']['status'], 'TRANSFERRED')
        self.assertEqual(self.company.balance, Decimal('53750.00'))

        self.client.force_authenticate(self.accountant)
        self.client.post(reverse('account-payments', args=[self.company.pk]),
                         {'amount': '53750', 'method': 'BANK_TRANSFER', 'reference': 'TRF-889'}, format='json')
        self.assertEqual(self.company.balance, Decimal('0.00'))
        statement = self.client.get(reverse('account-statement', args=[self.company.pk])).data
        self.assertEqual(len(statement['folios']), 1)

    def test_credit_limit_enforced(self):
        booking = self.in_house(nights=1)
        CorporateAccount.objects.filter(pk=self.company.pk).update(credit_limit=Decimal('50000'))
        response = self.client.post(reverse('reservation-check-out', args=[booking.pk]),
                                    {'transfer_to_account': self.company.pk}, format='json')
        self.assertEqual(response.status_code, 400)
        booking.refresh_from_db()
        self.assertEqual(booking.status, 'CHECKED_IN')  # nothing half-done

    def test_receptionist_cannot_create_accounts(self):
        self.assertEqual(self.client.post(reverse('account-list'), {'code': 'x', 'name': 'X'}, format='json').status_code, 403)


class PolicyIntegrationTests(FakeGatewayMixin, BillingTestCase):
    def test_late_cancellation_fee_posted_to_folio(self):
        booking = self.reserve(check_in=self.today + timedelta(days=1), nights=2)
        self.client.post(reverse('reservation-cancel', args=[booking.pk]), {'reason': 'Changed plans'}, format='json')
        booking.refresh_from_db()
        charge = booking.folio.charges.get()
        self.assertEqual(charge.category, 'PENALTY')
        self.assertEqual(charge.total_amount, Decimal('50000.00'))

    def test_online_prepayment_includes_taxes_and_lands_on_folio(self):
        self.client.force_authenticate(None)
        check_in = self.today + timedelta(days=10)
        response = self.client.post(reverse('create-booking'), {
            'guest': {'first_name': 'Ada', 'last_name': 'Obi', 'email': 'ada@example.com'},
            'room_type': self.room_type.id, 'check_in_date': check_in.isoformat(),
            'check_out_date': (check_in + timedelta(days=1)).isoformat(),
            'number_of_adults': 1, 'number_of_children': 0, 'gateway': 'FLUTTERWAVE',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['total_with_taxes'], '53750.00')
        self.gateway.pay(response.data['payment']['reference'])
        self.client.post(reverse('payment-verify'), {'reference': response.data['payment']['reference']}, format='json')
        folio = Booking.objects.get(confirmation_number=response.data['confirmation_number']).folio
        self.assertEqual(folio.payments_total, Decimal('53750.00'))
        self.assertEqual(folio.balance, Decimal('-53750.00'))  # credit until the night is posted
