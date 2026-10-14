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


class EnabledGatewayTests(SimpleTestCase):
    @override_settings(PAYMENT_GATEWAYS=['PAYSTACK', 'FLUTTERWAVE'], PAYSTACK_SECRET_KEY='sk_test_x', FLUTTERWAVE_SECRET_KEY='')
    def test_gateways_without_credentials_are_not_offered(self):
        from payments.gateways import enabled_gateways
        self.assertEqual(enabled_gateways(), ['PAYSTACK'])

    @override_settings(PAYMENT_GATEWAYS=['PAYSTACK'], PAYSTACK_SECRET_KEY='')
    def test_no_credentials_means_no_online_payment(self):
        from payments.gateways import enabled_gateways
        self.assertEqual(enabled_gateways(), [])
