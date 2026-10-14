"""Delivery channels. SMS and WhatsApp go through Termii (https://developers.termii.com)."""
import re

import requests
from django.conf import settings
from django.core.mail import EmailMessage


class DeliveryError(Exception):
    pass


def normalize_phone(raw):
    """Nigerian numbers to international format: 0803 123 4567 -> 2348031234567."""
    digits = re.sub(r'\D', '', raw or '')
    if digits.startswith('0') and len(digits) == 11:
        digits = settings.DEFAULT_PHONE_COUNTRY_CODE + digits[1:]
    return digits if 10 <= len(digits) <= 15 else ''


def send_email(to, subject, body, attachments=()):
    message = EmailMessage(subject=subject, body=body, from_email=settings.DEFAULT_FROM_EMAIL, to=[to])
    for filename, content, mimetype in attachments:
        message.attach(filename, content, mimetype)
    message.send(fail_silently=False)
    return ''


def send_termii(to, text, channel):
    if not settings.TERMII_API_KEY:
        raise DeliveryError("Termii is not configured.")
    try:
        response = requests.post(f'{settings.TERMII_BASE_URL}/api/sms/send', timeout=15, json={
            'api_key': settings.TERMII_API_KEY, 'to': to, 'from': settings.TERMII_SENDER_ID, 'sms': text,
            'type': 'plain', 'channel': channel,
        })
    except requests.RequestException as e:
        raise DeliveryError(f"Termii unreachable: {e.__class__.__name__}")
    body = response.json() if response.content else {}
    if response.status_code >= 400:
        raise DeliveryError(f"Termii error: {body.get('message', response.status_code)}")
    return str(body.get('message_id', ''))


def send_sms(to, text):
    # 'dnd' routes to numbers on Nigeria's Do-Not-Disturb list (transactional messages only)
    return send_termii(to, text, 'dnd')


def send_whatsapp(to, text):
    return send_termii(to, text, 'whatsapp')
