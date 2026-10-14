"""Paystack (https://paystack.com/docs/api/). Amounts are in the minor unit (kobo)."""
import hashlib
import hmac
import json
from decimal import Decimal

from django.conf import settings

from .base import Initialized, PaymentGateway, Verification, sanitize

API = 'https://api.paystack.co'


def to_minor(amount):
    return int((Decimal(amount) * 100).to_integral_value())


class PaystackGateway(PaymentGateway):
    code = 'PAYSTACK'

    @property
    def _headers(self):
        return {'Authorization': f'Bearer {settings.PAYSTACK_SECRET_KEY}', 'Content-Type': 'application/json'}

    def initialize(self, *, reference, amount, currency, email, callback_url, customer_name='', description=''):
        body = self._request('POST', f'{API}/transaction/initialize', headers=self._headers, json={
            'reference': reference,
            'amount': to_minor(amount),
            'currency': currency,
            'email': email,
            'callback_url': callback_url,
            'metadata': {'customer_name': customer_name, 'description': description},
        })
        data = body.get('data') or {}
        return Initialized(authorization_url=data['authorization_url'], gateway_reference=data.get('access_code', ''))

    def verify(self, reference):
        body = self._request('GET', f'{API}/transaction/verify/{reference}', headers=self._headers)
        data = body.get('data') or {}
        return Verification(
            succeeded=data.get('status') == 'success',
            amount=Decimal(data.get('amount', 0)) / 100,
            currency=data.get('currency', ''),
            gateway_transaction_id=str(data.get('id', '')),
            status=data.get('status', ''),
            raw=sanitize(data),
        )

    def refund(self, *, gateway_transaction_id, reference, amount, currency):
        body = self._request('POST', f'{API}/refund', headers=self._headers, json={
            'transaction': reference, 'amount': to_minor(amount), 'currency': currency,
        })
        return sanitize(body.get('data') or {})

    def webhook_reference(self, request):
        signature = request.headers.get('X-Paystack-Signature', '')
        expected = hmac.new(settings.PAYSTACK_SECRET_KEY.encode(), request.body, hashlib.sha512).hexdigest()
        if not settings.PAYSTACK_SECRET_KEY or not hmac.compare_digest(signature, expected):
            raise PermissionError("Invalid Paystack signature")
        event = json.loads(request.body or b'{}')
        if event.get('event') != 'charge.success':
            return None
        return (event.get('data') or {}).get('reference')
