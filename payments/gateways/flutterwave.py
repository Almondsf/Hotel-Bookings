"""Flutterwave v3 (https://developer.flutterwave.com/docs). Amounts are in the major unit."""
import hmac
import json
from decimal import Decimal

from django.conf import settings

from .base import Initialized, PaymentGateway, Verification, sanitize

API = 'https://api.flutterwave.com/v3'


class FlutterwaveGateway(PaymentGateway):
    code = 'FLUTTERWAVE'

    @property
    def _headers(self):
        return {'Authorization': f'Bearer {settings.FLUTTERWAVE_SECRET_KEY}', 'Content-Type': 'application/json'}

    def initialize(self, *, reference, amount, currency, email, callback_url, customer_name='', description=''):
        body = self._request('POST', f'{API}/payments', headers=self._headers, json={
            'tx_ref': reference,
            'amount': str(amount),
            'currency': currency,
            'redirect_url': callback_url,
            'customer': {'email': email, 'name': customer_name},
            'customizations': {'title': settings.HOTEL_NAME, 'description': description},
        })
        return Initialized(authorization_url=(body.get('data') or {})['link'])

    def verify(self, reference):
        body = self._request('GET', f'{API}/transactions/verify_by_reference', headers=self._headers,
                             params={'tx_ref': reference})
        data = body.get('data') or {}
        return Verification(
            succeeded=data.get('status') == 'successful',
            amount=Decimal(str(data.get('amount', 0))),
            currency=data.get('currency', ''),
            gateway_transaction_id=str(data.get('id', '')),
            status=data.get('status', ''),
            raw=sanitize(data),
        )

    def refund(self, *, gateway_transaction_id, reference, amount, currency):
        body = self._request('POST', f'{API}/transactions/{gateway_transaction_id}/refund', headers=self._headers,
                             json={'amount': str(amount)})
        return sanitize(body.get('data') or {})

    def webhook_reference(self, request):
        # Flutterwave sends the secret hash configured in its dashboard
        signature = request.headers.get('Verif-Hash', '')
        secret = settings.FLUTTERWAVE_WEBHOOK_HASH
        if not secret or not hmac.compare_digest(signature, secret):
            raise PermissionError("Invalid Flutterwave signature")
        event = json.loads(request.body or b'{}')
        if event.get('event') != 'charge.completed':
            return None
        return (event.get('data') or {}).get('tx_ref')
