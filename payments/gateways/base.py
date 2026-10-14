from dataclasses import dataclass, field
from decimal import Decimal

import requests

from hotel.errors import DomainError


class GatewayError(DomainError):
    """The payment provider could not be reached or rejected the request."""
    status_code = 502


@dataclass
class Initialized:
    authorization_url: str
    gateway_reference: str = ''


@dataclass
class Verification:
    """The provider's view of a transaction, normalised across gateways."""
    succeeded: bool
    amount: Decimal
    currency: str
    gateway_transaction_id: str
    status: str
    raw: dict = field(default_factory=dict)


# Keys stripped from stored provider responses: reusable card authorisations,
# card details and customer PII don't belong in our database.
SENSITIVE_KEYS = {'authorization', 'card', 'customer', 'authorization_code', 'account', 'meta', 'ip', 'device_fingerprint'}


def sanitize(data):
    if isinstance(data, dict):
        return {k: sanitize(v) for k, v in data.items() if k not in SENSITIVE_KEYS}
    if isinstance(data, list):
        return [sanitize(v) for v in data]
    return data


class PaymentGateway:
    code = ''
    timeout = 20  # seconds

    def initialize(self, *, reference, amount, currency, email, callback_url, customer_name='', description=''):
        raise NotImplementedError

    def verify(self, reference):
        raise NotImplementedError

    def refund(self, *, gateway_transaction_id, reference, amount, currency):
        raise NotImplementedError

    def webhook_reference(self, request):
        """
        Validate a webhook's authenticity and return the transaction reference
        it concerns, or None if it should be ignored. Raises PermissionError
        if the signature is invalid.
        """
        raise NotImplementedError

    def _request(self, method, url, **kwargs):
        try:
            response = requests.request(method, url, timeout=self.timeout, **kwargs)
        except requests.RequestException as e:
            raise GatewayError(f"Could not reach {self.code.title()}: {e.__class__.__name__}")
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code >= 400:
            message = body.get('message') or f"HTTP {response.status_code}"
            raise GatewayError(f"{self.code.title()} error: {message}")
        return body
