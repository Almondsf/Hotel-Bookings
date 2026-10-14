from django.conf import settings

from .base import GatewayError
from .flutterwave import FlutterwaveGateway
from .paystack import PaystackGateway

GATEWAYS = {gateway.code: gateway for gateway in (PaystackGateway, FlutterwaveGateway)}


SECRET_KEY_SETTINGS = {'PAYSTACK': 'PAYSTACK_SECRET_KEY', 'FLUTTERWAVE': 'FLUTTERWAVE_SECRET_KEY'}


def enabled_gateways():
    """Gateways switched on in settings that also have credentials; offering one without a key only fails later."""
    return [code for code in settings.PAYMENT_GATEWAYS
            if code in GATEWAYS and getattr(settings, SECRET_KEY_SETTINGS[code], '')]


def get_gateway(code):
    if code not in enabled_gateways():
        raise GatewayError(f"Payment gateway {code} is not enabled.")
    return GATEWAYS[code]()
