"""
Guest messages. Call notify(...) from business code; delivery happens in a
background job after the surrounding transaction commits, so a slow or
failing provider never slows down or breaks the front desk.
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.tasks import task
from django.template.loader import render_to_string
from django.utils import timezone

from booking.models import Booking

from . import channels
from .models import Notification

logger = logging.getLogger(__name__)

Channel = Notification.Channel
# Which channels each message uses (email always; SMS/WhatsApp when enabled and the guest has a phone)
TEMPLATES = {
    'booking_confirmed': [Channel.EMAIL, Channel.SMS],
    'pre_arrival': [Channel.EMAIL, Channel.WHATSAPP],
    'checked_out': [Channel.EMAIL],
    'booking_cancelled': [Channel.EMAIL, Channel.SMS],
}


def _context(booking):
    return {'booking': booking, 'guest': booking.guest, 'hotel_name': settings.HOTEL_NAME,
            'hotel_phone': settings.HOTEL_PHONE, 'check_in_time': settings.HOTEL_CHECK_IN_TIME,
            'check_out_time': settings.HOTEL_CHECK_OUT_TIME}


def _recipient(booking, channel):
    if channel == Channel.EMAIL:
        return booking.guest.email
    if channel == Channel.SMS and not settings.SMS_ENABLED:
        return ''
    if channel == Channel.WHATSAPP and not settings.WHATSAPP_ENABLED:
        return ''
    if booking.guest.sms_opt_out:
        return ''
    return channels.normalize_phone(booking.guest.phone_number)


def notify(template, booking):
    """Queue `template` for the booking's guest on each configured channel (once per channel)."""
    if template not in TEMPLATES:
        raise ValueError(f"Unknown notification template {template}")

    def enqueue():
        for channel in TEMPLATES[template]:
            recipient = _recipient(booking, channel)
            if not recipient:
                continue
            try:
                with transaction.atomic():
                    notification = Notification.objects.create(
                        template=template, channel=channel, booking=booking, recipient=recipient)
            except IntegrityError:
                continue  # already sent / queued
            deliver.enqueue(notification.pk)
    transaction.on_commit(enqueue)


@task
def deliver(notification_id):
    notification = Notification.objects.select_related('booking__guest', 'booking__room__room_type').get(
        pk=notification_id)
    if notification.status == Notification.Status.SENT:
        return 'already sent'
    booking = notification.booking
    context = _context(booking)
    try:
        if notification.channel == Channel.EMAIL:
            subject = render_to_string(f'notifications/{notification.template}_subject.txt', context).strip()
            body = render_to_string(f'notifications/{notification.template}.txt', context)
            notification.provider_message_id = channels.send_email(
                notification.recipient, subject, body, attachments=_attachments(notification.template, booking))
        else:
            text = render_to_string(f'notifications/{notification.template}_sms.txt', context).strip()
            send = channels.send_sms if notification.channel == Channel.SMS else channels.send_whatsapp
            notification.provider_message_id = send(notification.recipient, text)
    except Exception as e:
        notification.status = Notification.Status.FAILED
        notification.error = str(e)[:500]
        notification.save(update_fields=['status', 'error'])
        raise  # let the worker retry with backoff
    notification.status = Notification.Status.SENT
    notification.error = ''
    notification.sent_at = timezone.now()
    notification.save(update_fields=['status', 'error', 'sent_at', 'provider_message_id'])
    return 'sent'


def _attachments(template, booking):
    """The final invoice goes with the check-out thank-you."""
    if template != 'checked_out':
        return ()
    from billing.models import Folio
    from billing.pdf import render_invoice

    folio = Folio.objects.filter(booking=booking).first()
    invoice = folio.invoices.order_by('-issued_at').first() if folio else None
    return [(f'{invoice.number}.pdf', render_invoice(invoice), 'application/pdf')] if invoice else ()


@task
def send_pre_arrival_reminders():
    """Remind guests arriving tomorrow. Safe to run often: each booking is reminded once."""
    from hotel.clock import business_date

    tomorrow = business_date() + timedelta(days=1)
    bookings = Booking.objects.filter(status=Booking.Status.CONFIRMED, check_in_date=tomorrow).select_related('guest')
    for booking in bookings:
        notify('pre_arrival', booking)
    return bookings.count()


@task
def expire_payment_holds():
    from booking.lifecycle import expire_holds
    return expire_holds()


@task
def generate_housekeeping_tasks():
    from housekeeping.services import generate_daily_tasks
    return generate_daily_tasks()
