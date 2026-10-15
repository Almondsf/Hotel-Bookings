import hashlib
import hmac
import json
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from authentication.models import User
from booking.lifecycle import expire_holds
from booking.models import Booking
from payments.gateways.base import GatewayError, sanitize
from payments.gateways.flutterwave import FlutterwaveGateway
from payments.gateways.paystack import PaystackGateway
from payments.models import PaymentTransaction
from payments.testing import FakeGatewayMixin
from rooms.models import Room, RoomType

PAYSTACK_SECRET = 'sk_test_secret'
FLW_HASH = 'flw-webhook-hash'


def fake_response(status_code=200, body=None):
    response = mock.Mock(status_code=status_code)
    response.json.return_value = body or {}
    return response


@override_settings(PAYSTACK_SECRET_KEY=PAYSTACK_SECRET, FLUTTERWAVE_SECRET_KEY='FLWSECK_TEST', HOTEL_NAME='Test Hotel')
class GatewayClientTests(SimpleTestCase):
    """The HTTP requests we send match each provider's API."""

    @mock.patch('payments.gateways.base.requests.request')
    def test_paystack_initialize_sends_kobo(self, request):
        request.return_value = fake_response(body={'data': {'authorization_url': 'https://checkout.paystack.com/x',
                                                            'access_code': 'ac'}})
        result = PaystackGateway().initialize(reference='PAY-1', amount=Decimal('53750.50'), currency='NGN',
                                              email='a@b.com', callback_url='https://h/cb')
        method, url = request.call_args.args
        payload = request.call_args.kwargs['json']
        self.assertEqual((method, url), ('POST', 'https://api.paystack.co/transaction/initialize'))
        self.assertEqual(payload['amount'], 5375050)
        self.assertEqual(request.call_args.kwargs['headers']['Authorization'], f'Bearer {PAYSTACK_SECRET}')
        self.assertEqual(result.authorization_url, 'https://checkout.paystack.com/x')

    @mock.patch('payments.gateways.base.requests.request')
    def test_paystack_verify_converts_and_strips_card_data(self, request):
        request.return_value = fake_response(body={'data': {
            'status': 'success', 'amount': 5375050, 'currency': 'NGN', 'id': 99, 'reference': 'PAY-1',
            'authorization': {'authorization_code': 'AUTH_reusable', 'last4': '4081'},
            'customer': {'email': 'a@b.com'},
        }})
        result = PaystackGateway().verify('PAY-1')
        self.assertTrue(result.succeeded)
        self.assertEqual(result.amount, Decimal('53750.50'))
        self.assertNotIn('authorization', result.raw)
        self.assertNotIn('customer', result.raw)

    @mock.patch('payments.gateways.base.requests.request')
    def test_flutterwave_verify(self, request):
        request.return_value = fake_response(body={'data': {
            'status': 'successful', 'amount': 53750.5, 'currency': 'NGN', 'id': 7, 'tx_ref': 'PAY-1',
            'card': {'first_6digits': '539983'},
        }})
        result = FlutterwaveGateway().verify('PAY-1')
        self.assertEqual(request.call_args.kwargs['params'], {'tx_ref': 'PAY-1'})
        self.assertTrue(result.succeeded)
        self.assertEqual(result.amount, Decimal('53750.5'))
        self.assertNotIn('card', result.raw)

    @mock.patch('payments.gateways.base.requests.request')
    def test_provider_errors_become_gateway_errors(self, request):
        request.return_value = fake_response(401, {'message': 'Invalid key'})
        with self.assertRaisesMessage(GatewayError, 'Invalid key'):
            PaystackGateway().verify('PAY-1')

    def test_sanitize_is_recursive(self):
        self.assertEqual(sanitize({'a': [{'card': 1, 'b': 2}]}), {'a': [{'b': 2}]})


@override_settings(REQUIRE_GUEST_ID_AT_CHECK_IN=False, PAYSTACK_SECRET_KEY=PAYSTACK_SECRET,
                   FLUTTERWAVE_WEBHOOK_HASH=FLW_HASH, BOOKING_HOLD_MINUTES=15)
class PaymentFlowTests(FakeGatewayMixin, APITestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.room_type = RoomType.objects.create(
            name='Standard', description='Standard', base_price=Decimal('50000.00'), max_adults=2, max_children=0,
            bed_type='KING', bed_count=1, size=300,
        )
        self.room = Room.objects.create(room_number='101', room_type=self.room_type, floor_number=1)
        self.check_in = timezone.localdate() + timedelta(days=5)

    def book(self, gateway='PAYSTACK', email='ada@example.com'):
        response = self.client.post(reverse('create-booking'), {
            'guest': {'first_name': 'Ada', 'last_name': 'Obi', 'email': email},
            'room_type': self.room_type.id, 'check_in_date': self.check_in.isoformat(),
            'check_out_date': (self.check_in + timedelta(days=1)).isoformat(),
            'number_of_adults': 1, 'gateway': gateway,
        }, format='json')
        assert response.status_code == 201, response.data
        return response.data['payment']['reference']

    def verify(self, reference):
        return self.client.post(reverse('payment-verify'), {'reference': reference}, format='json')

    def paystack_webhook(self, payload, secret=PAYSTACK_SECRET):
        body = json.dumps(payload).encode()
        signature = hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()
        return self.client.generic('POST', reverse('webhook-paystack'), body, content_type='application/json',
                                   HTTP_X_PAYSTACK_SIGNATURE=signature)

    def test_redirect_and_webhook_settle_once(self):
        reference = self.book()
        self.gateway.pay(reference)
        self.assertEqual(self.paystack_webhook({'event': 'charge.success', 'data': {'reference': reference}}).status_code, 200)
        self.assertEqual(self.verify(reference).data['status'], 'SUCCEEDED')
        self.assertEqual(self.verify(reference).data['status'], 'SUCCEEDED')

        txn = PaymentTransaction.objects.get(reference=reference)
        self.assertEqual(txn.folio.payments.count(), 1)
        self.assertEqual(self.gateway.verify_calls, 1)  # later calls see it's settled

    def test_webhook_with_bad_signature_is_rejected(self):
        reference = self.book()
        self.gateway.pay(reference)
        response = self.paystack_webhook({'event': 'charge.success', 'data': {'reference': reference}}, secret='wrong')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(PaymentTransaction.objects.get(reference=reference).status, 'INITIALIZED')

    def test_webhook_body_is_not_trusted(self):
        # A correctly signed webhook still only triggers verification with the gateway
        reference = self.book()
        self.paystack_webhook({'event': 'charge.success', 'data': {'reference': reference, 'amount': 5375000}})
        self.assertEqual(PaymentTransaction.objects.get(reference=reference).status, 'INITIALIZED')

    def test_flutterwave_webhook(self):
        reference = self.book(gateway='FLUTTERWAVE')
        self.gateway.pay(reference)
        url = reverse('webhook-flutterwave')
        body = json.dumps({'event': 'charge.completed', 'data': {'tx_ref': reference}})
        self.assertEqual(self.client.generic('POST', url, body, content_type='application/json',
                                             HTTP_VERIF_HASH='nope').status_code, 401)
        self.assertEqual(self.client.generic('POST', url, body, content_type='application/json',
                                             HTTP_VERIF_HASH=FLW_HASH).status_code, 200)
        self.assertEqual(PaymentTransaction.objects.get(reference=reference).status, 'SUCCEEDED')

    def test_underpayment_is_flagged_not_confirmed(self):
        reference = self.book()
        self.gateway.pay(reference, amount='100.00')
        self.assertEqual(self.verify(reference).data['status'], 'NEEDS_REVIEW')
        self.assertEqual(Booking.objects.get().status, 'PENDING')

    def test_wrong_currency_is_flagged(self):
        reference = self.book()
        self.gateway.pay(reference, currency='USD')
        self.assertEqual(self.verify(reference).data['status'], 'NEEDS_REVIEW')

    def test_failed_payment(self):
        reference = self.book()
        self.gateway.failed.add(reference)
        self.assertEqual(self.verify(reference).data['status'], 'FAILED')

    def test_malformed_and_unknown_references(self):
        self.assertEqual(self.verify('../../etc/passwd').status_code, 400)
        self.assertEqual(self.verify('PAY-' + '0' * 20).status_code, 404)

    def test_late_payment_reinstates_booking_if_room_still_free(self):
        reference = self.book()
        Booking.objects.update(hold_expires_at=timezone.now() - timedelta(minutes=1))
        expire_holds()
        self.assertEqual(Booking.objects.get().status, 'CANCELLED')

        self.gateway.pay(reference)
        self.assertEqual(self.verify(reference).data['booking']['status'], 'CONFIRMED')

    def test_late_payment_refunded_if_room_was_resold(self):
        reference = self.book()
        Booking.objects.update(hold_expires_at=timezone.now() - timedelta(minutes=1))
        expire_holds()
        other = self.book(email='bob@example.com')  # takes the only room
        self.assertNotEqual(other, reference)

        self.gateway.pay(reference)
        response = self.verify(reference)
        self.assertEqual(response.data['booking']['status'], 'CANCELLED')
        txn = PaymentTransaction.objects.get(reference=reference)
        self.assertEqual(txn.status, 'REFUNDED')
        self.assertEqual(self.gateway.refunds, [(reference, Decimal('53750.00'))])
        self.assertEqual(txn.folio.balance, Decimal('0.00'))


@override_settings(REQUIRE_GUEST_ID_AT_CHECK_IN=False)
class StaffPaymentTests(FakeGatewayMixin, APITestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        from billing import services as billing
        from billing.models import ChargeCategory
        self.folio = billing.open_non_guest_folio(name='Wedding party')
        billing.post_charge(self.folio, category=ChargeCategory.MISC, description='Hall hire', unit_price='200000')
        self.receptionist = User.objects.create_user('desk@hotel.com', 'D', 'C', 'x', role='receptionist')
        self.accountant = User.objects.create_user('acc@hotel.com', 'A', 'C', 'x', role='accountant')

    def test_payment_link_for_folio_balance_then_refund(self):
        self.client.force_authenticate(self.receptionist)
        response = self.client.post(reverse('payment-transaction-payment-link'), {
            'folio': self.folio.pk, 'gateway': 'PAYSTACK', 'email': 'bride@example.com',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['amount'], '215000.00')
        reference = response.data['reference']

        self.gateway.pay(reference)
        self.client.post(reverse('payment-verify'), {'reference': reference}, format='json')
        self.folio.refresh_from_db()
        self.assertEqual(self.folio.balance, Decimal('0.00'))

        txn = PaymentTransaction.objects.get(reference=reference)
        url = reverse('payment-transaction-refund', args=[txn.pk])
        self.assertEqual(self.client.post(url, {'amount': '1000', 'reason': 'x'}, format='json').status_code, 403)
        self.client.force_authenticate(self.accountant)
        # Can't refund more than the guest is owed (balance is 0)
        self.assertEqual(self.client.post(url, {'amount': '1000', 'reason': 'Goodwill'}, format='json').status_code, 400)
        self.assertEqual(self.gateway.refunds, [])

    def test_discount_after_online_payment_is_refunded_to_the_card(self):
        self.client.force_authenticate(self.receptionist)
        reference = self.client.post(reverse('payment-transaction-payment-link'), {
            'folio': self.folio.pk, 'gateway': 'PAYSTACK', 'email': 'bride@example.com',
        }, format='json').data['reference']
        self.gateway.pay(reference)
        self.client.post(reverse('payment-verify'), {'reference': reference}, format='json')

        # The folio shows which payment was online and how much of it can go back to the card
        detail = self.client.get(reverse('folio-detail', args=[self.folio.pk])).data
        online = [p['online'] for p in detail['payments'] if p['online']]
        self.assertEqual(len(online), 1)
        self.assertEqual((online[0]['gateway'], online[0]['refundable']), ('PAYSTACK', '215000.00'))

        # Receptionists can't give discounts; accountants can, which leaves the guest in credit
        allowance = {'category': 'ALLOWANCE', 'description': 'Discount: AC fault', 'unit_price': '-10000.00'}
        charges_url = reverse('folio-charges', args=[self.folio.pk])
        self.assertEqual(self.client.post(charges_url, allowance, format='json').status_code, 403)
        self.client.force_authenticate(self.accountant)
        self.assertEqual(self.client.post(charges_url, allowance, format='json').status_code, 201)
        self.folio.refresh_from_db()
        credit = -self.folio.balance
        self.assertGreater(credit, 0)

        response = self.client.post(reverse('payment-transaction-refund', args=[online[0]['transaction_id']]),
                                    {'amount': str(credit), 'reason': 'Discount for AC fault'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(self.gateway.refunds), 1)
        self.folio.refresh_from_db()
        self.assertEqual(self.folio.balance, Decimal('0.00'))


class EnabledGatewayTests(SimpleTestCase):
    @override_settings(PAYMENT_GATEWAYS=['PAYSTACK', 'FLUTTERWAVE'], PAYSTACK_SECRET_KEY='sk_test_x', FLUTTERWAVE_SECRET_KEY='')
    def test_gateways_without_credentials_are_not_offered(self):
        from payments.gateways import enabled_gateways
        self.assertEqual(enabled_gateways(), ['PAYSTACK'])

    @override_settings(PAYMENT_GATEWAYS=['PAYSTACK'], PAYSTACK_SECRET_KEY='')
    def test_no_credentials_means_no_online_payment(self):
        from payments.gateways import enabled_gateways
        self.assertEqual(enabled_gateways(), [])


@override_settings(REQUIRE_GUEST_ID_AT_CHECK_IN=False, PAYSTACK_SECRET_KEY=PAYSTACK_SECRET, BOOKING_HOLD_MINUTES=15)
class GroupBookingTests(FakeGatewayMixin, APITestCase):
    """A party too big for one room books a group plan: several rooms, one checkout."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.family = RoomType.objects.create(name='Family Suite', description='x', base_price=Decimal('200000.00'),
                                              max_adults=4, max_children=2, bed_type='KING', bed_count=2, size=600)
        self.deluxe = RoomType.objects.create(name='Deluxe Suite', description='x', base_price=Decimal('150000.00'),
                                              max_adults=3, max_children=2, bed_type='KING', bed_count=1, size=400)
        for n in range(3):
            Room.objects.create(room_number=f'30{n}', room_type=self.family, floor_number=3)
        for n in range(2):
            Room.objects.create(room_number=f'20{n}', room_type=self.deluxe, floor_number=2)
        self.check_in = timezone.localdate() + timedelta(days=5)
        self.check_out = self.check_in + timedelta(days=2)

    def search(self, adults, children):
        return self.client.get(reverse('room-type-search'), {
            'check_in': self.check_in, 'check_out': self.check_out, 'adults': adults, 'children': children}).data

    def book_plan(self, plan):
        return self.client.post(reverse('create-group-booking'), {
            'guest': {'first_name': 'Tunde', 'last_name': 'Bakare', 'email': 'tunde@example.com'},
            'check_in_date': self.check_in.isoformat(), 'check_out_date': self.check_out.isoformat(),
            'rooms': [{'room_type': r['room_type_id'], 'number_of_adults': r['number_of_adults'],
                       'number_of_children': r['number_of_children']} for r in plan['rooms']],
            'gateway': 'PAYSTACK',
        }, format='json')

    def test_large_party_gets_group_plans_and_the_regular_list(self):
        data = self.search(10, 4)
        self.assertEqual(data['room_types'], [])  # no single room fits
        self.assertTrue(data['other_room_types'])  # but every room on sale is still listed
        plans = data['group_plans']
        self.assertTrue(1 <= len(plans) <= 3)
        self.assertEqual(plans[0]['label'], 'Best value')
        for plan in plans:
            self.assertEqual(sum(r['number_of_adults'] for r in plan['rooms']), 10)
            self.assertEqual(sum(r['number_of_children'] for r in plan['rooms']), 4)
            self.assertTrue(all(r['number_of_adults'] >= 1 for r in plan['rooms']))
        self.assertEqual(len({tuple(sorted(r['room_type_id'] for r in p['rooms'])) for p in plans}), len(plans))
        # Parties that fit one room get no plans
        self.assertIsNone(self.search(2, 0)['group_plans'])

    def test_group_plan_is_held_paid_once_and_confirmed_together(self):
        plan = self.search(10, 4)['group_plans'][0]
        response = self.book_plan(plan)
        self.assertEqual(response.status_code, 201, response.data)
        reference = response.data['payment']['reference']
        bookings = Booking.objects.filter(group__reference=response.data['group_reference'])
        self.assertEqual(bookings.count(), len(plan['rooms']))
        self.assertEqual(set(bookings.values_list('status', flat=True)), {'PENDING'})
        self.assertEqual(len(set(bookings.values_list('room_id', flat=True))), bookings.count())

        self.gateway.pay(reference)
        verified = self.client.post(reverse('payment-verify'), {'reference': reference}, format='json').data
        self.assertEqual(verified['status'], 'SUCCEEDED')
        self.assertEqual({b['status'] for b in verified['group']['bookings']}, {'CONFIRMED'})

        # One payment, split so every room's bill holds exactly its own prepayment
        txn = PaymentTransaction.objects.get(reference=reference)
        from booking.services import amount_due_online
        total = Decimal('0.00')
        for booking in bookings:
            paid = booking.folio.payments_total
            self.assertEqual(paid, amount_due_online(booking))
            total += paid
        self.assertEqual(total, txn.amount)

    def test_group_that_lost_a_room_is_refunded_in_full(self):
        plan = self.search(10, 4)['group_plans'][0]
        reference = self.book_plan(plan).data['payment']['reference']
        expire_holds(now=timezone.now() + timedelta(minutes=16))
        # Meanwhile every room of one type in the plan is sold to someone else
        taken_type = plan['rooms'][0]['room_type_id']
        for room in Room.objects.filter(room_type_id=taken_type):
            Booking.objects.create(
                guest=Booking.objects.first().guest, room=room, number_of_adults=1, price_per_night=1, total_price=2,
                status='CONFIRMED', confirmation_number=f'BK-X{room.pk}', check_in_date=self.check_in,
                check_out_date=self.check_out)

        self.gateway.pay(reference)
        self.client.post(reverse('payment-verify'), {'reference': reference}, format='json')
        txn = PaymentTransaction.objects.get(reference=reference)
        self.assertEqual(sum(amount for _, amount in self.gateway.refunds), txn.amount)
        group = Booking.objects.get(pk=txn.booking_id).group
        self.assertFalse(group.bookings.filter(status='CONFIRMED').exists())

    def test_invalid_group_requests_are_refused(self):
        plan = self.search(10, 4)['group_plans'][0]
        one_room = {**plan, 'rooms': plan['rooms'][:1]}
        self.assertEqual(self.book_plan(one_room).status_code, 400)
        no_adult = {**plan, 'rooms': [{**plan['rooms'][0], 'number_of_adults': 0}] + plan['rooms'][1:]}
        self.assertEqual(self.book_plan(no_adult).status_code, 400)


@override_settings(REQUIRE_GUEST_ID_AT_CHECK_IN=False, PAYSTACK_SECRET_KEY=PAYSTACK_SECRET, BOOKING_HOLD_MINUTES=15,
                   FREE_CANCELLATION_HOURS=48, CANCELLATION_PENALTY_NIGHTS=1)
class CancellationRefundTests(FakeGatewayMixin, APITestCase):
    """Cancelling a booking paid online sends what's left after the fee back to the card."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.room_type = RoomType.objects.create(name='Standard', description='x', base_price=Decimal('50000.00'),
                                                 max_adults=2, max_children=0, bed_type='KING', bed_count=1, size=300)
        for n in range(3):
            Room.objects.create(room_number=f'10{n}', room_type=self.room_type, floor_number=1)

    def book_and_pay(self, days_ahead, nights=2):
        check_in = timezone.localdate() + timedelta(days=days_ahead)
        response = self.client.post(reverse('create-booking'), {
            'guest': {'first_name': 'Ada', 'last_name': 'Obi', 'email': 'ada@example.com'},
            'room_type': self.room_type.id, 'check_in_date': check_in.isoformat(),
            'check_out_date': (check_in + timedelta(days=nights)).isoformat(), 'number_of_adults': 1, 'gateway': 'PAYSTACK',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        reference = response.data['payment']['reference']
        self.gateway.pay(reference)
        self.client.post(reverse('payment-verify'), {'reference': reference}, format='json')
        return PaymentTransaction.objects.get(reference=reference)

    def guest_cancels(self, booking):
        return self.client.post(reverse('booking-cancel'), {
            'confirmation_number': booking.confirmation_number, 'email': booking.guest.email}, format='json')

    def test_free_cancellation_refunds_everything_to_the_card(self):
        txn = self.book_and_pay(days_ahead=10)
        response = self.guest_cancels(txn.booking)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['refunded'], str(txn.amount))  # the guest is told what's coming back
        self.assertEqual(self.gateway.refunds, [(txn.reference, txn.amount)])
        txn.refresh_from_db()
        self.assertEqual((txn.status, txn.refunded_amount), ('REFUNDED', txn.amount))
        self.assertEqual(txn.folio.balance, Decimal('0.00'))

    def test_late_cancellation_refunds_all_but_the_fee(self):
        txn = self.book_and_pay(days_ahead=1)  # inside the 48-hour window: one night is charged
        self.guest_cancels(txn.booking)
        booking = Booking.objects.get(pk=txn.booking_id)
        self.assertEqual(booking.penalty_amount, Decimal('50000.00'))
        self.assertEqual(self.gateway.refunds, [(txn.reference, txn.amount - Decimal('50000.00'))])
        self.assertEqual(txn.folio.balance, Decimal('0.00'))  # fee paid from the prepayment, nothing owed either way

    def test_a_failed_refund_leaves_the_credit_for_staff(self):
        txn = self.book_and_pay(days_ahead=10)
        with mock.patch.object(self.gateway, 'refund', side_effect=GatewayError('Paystack error: try again later')):
            self.assertEqual(self.guest_cancels(txn.booking).status_code, 200)  # the cancellation still happens
        self.assertEqual(Booking.objects.get(pk=txn.booking_id).status, 'CANCELLED')
        txn.refresh_from_db()
        self.assertEqual(txn.refunded_amount, Decimal('0.00'))
        self.assertEqual(-txn.folio.balance, txn.amount)  # still owed to the guest, visible on the folio

    def test_cancelling_one_room_of_a_group_refunds_only_that_room(self):
        check_in = timezone.localdate() + timedelta(days=10)
        response = self.client.post(reverse('create-group-booking'), {
            'guest': {'first_name': 'Tunde', 'last_name': 'Bakare', 'email': 'tunde@example.com'},
            'check_in_date': check_in.isoformat(), 'check_out_date': (check_in + timedelta(days=2)).isoformat(),
            'rooms': [{'room_type': self.room_type.id, 'number_of_adults': 2}] * 3, 'gateway': 'PAYSTACK',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        reference = response.data['payment']['reference']
        self.gateway.pay(reference)
        self.client.post(reverse('payment-verify'), {'reference': reference}, format='json')

        rooms = list(Booking.objects.filter(group__reference=response.data['group_reference']).order_by('pk'))
        lead, cancelled = rooms[0], rooms[1]
        share = cancelled.folio.payments_total
        self.guest_cancels(cancelled)
        self.assertEqual(self.gateway.refunds, [(reference, share)])
        self.assertEqual(Booking.objects.get(pk=cancelled.pk).folio.balance, Decimal('0.00'))
        self.assertEqual(-Booking.objects.get(pk=lead.pk).folio.balance, lead.folio.payments_total)  # lead's money untouched
        self.assertEqual(Booking.objects.filter(pk__in=[lead.pk, rooms[2].pk], status='CONFIRMED').count(), 2)
