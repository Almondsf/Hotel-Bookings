from django.conf import settings

from .base import GatewayError
from .flutterwave import FlutterwaveGateway
from .paystack import PaystackGateway

GATEWAYS = {gateway.code: gateway for gateway in (PaystackGateway, FlutterwaveGateway)}


def enabled_gateways():
    return [code for code in settings.PAYMENT_GATEWAYS if code in GATEWAYS]


def get_gateway(code):
    if code not in enabled_gateways():
        raise GatewayError(f"Payment gateway {code} is not enabled.")
    return GATEWAYS[code]()
