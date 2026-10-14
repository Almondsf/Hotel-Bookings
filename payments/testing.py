"""Test double for the payment gateways, so tests never call real providers."""
from decimal import Decimal
from unittest import mock

from .gateways.base import GatewayError, Initialized, PaymentGateway, Verification


class FakeGateway(PaymentGateway):
    code = 'PAYSTACK'

    def __init__(self):
        self.expected = {}   # reference -> (amount, currency) from initialize
        self.paid = {}       # reference -> (amount, currency) the "customer" paid
        self.failed = set()
        self.refunds = []
        self.fail_initialize = False
        self.verify_calls = 0

    def initialize(self, *, reference, amount, currency, email, callback_url, customer_name='', description=''):
        if self.fail_initialize:
            raise GatewayError("Paystack error: service unavailable")
        self.expected[reference] = (Decimal(amount), currency)
        return Initialized(authorization_url=f'https://checkout.test/{reference}')

    def verify(self, reference):
        self.verify_calls += 1
        if reference in self.failed:
            return Verification(False, Decimal('0'), '', 'T1', 'failed')
        if reference not in self.paid:
            return Verification(False, Decimal('0'), '', '', 'pending')
        amount, currency = self.paid[reference]
        return Verification(True, amount, currency, f'T{reference[-6:]}', 'success', {'reference': reference})

    def refund(self, *, gateway_transaction_id, reference, amount, currency):
        self.refunds.append((reference, Decimal(amount)))
        return {'status': 'pending'}

    def pay(self, reference, amount=None, currency=None):
        expected_amount, expected_currency = self.expected[reference]
        self.paid[reference] = (Decimal(amount) if amount is not None else expected_amount,
                                currency or expected_currency)


class FakeGatewayMixin:
    """Patch every gateway lookup to return one FakeGateway (self.gateway)."""

    def setUp(self):
        super().setUp()
        self.gateway = FakeGateway()
        patcher = mock.patch('payments.services.get_gateway', return_value=self.gateway)
        patcher.start()
        self.addCleanup(patcher.stop)
