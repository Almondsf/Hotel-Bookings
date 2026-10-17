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
    # One message for a whole group (sent against its lead booking) instead of one per room
    'group_confirmed': [Channel.EMAIL, Channel.SMS],
    'group_pre_arrival': [Channel.EMAIL, Channel.WHATSAPP],
    'group_checked_out': [Channel.EMAIL],
    'group_cancelled': [Channel.EMAIL, Channel.SMS],
}
Status = Booking.Status
# Which of the group's rooms each group message lists
GROUP_ROOMS = {
    'group_confirmed': [Status.CONFIRMED, Status.CHECKED_IN, Status.CHECKED_OUT],
    'group_pre_arrival': [Status.CONFIRMED],
    'group_checked_out': [Status.CHECKED_OUT],
    'group_cancelled': [Status.CANCELLED],
}


def group_rooms(template, booking):
    return list(booking.group.bookings.filter(status__in=GROUP_ROOMS[template])
                .select_related('room__room_type').order_by('pk'))


def _context(template, booking):
    context = {'booking': booking, 'guest': booking.guest, 'hotel_name': settings.HOTEL_NAME,
               'hotel_phone': settings.HOTEL_PHONE, 'check_in_time': settings.HOTEL_CHECK_IN_TIME,
               'check_out_time': settings.HOTEL_CHECK_OUT_TIME}
    if template in GROUP_ROOMS:
        rooms = group_rooms(template, booking)
        context.update(group=booking.group, rooms=rooms, rooms_total=sum(r.total_price for r in rooms),
                       penalty_total=sum(r.penalty_amount for r in rooms))
    return context


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
    if template in GROUP_ROOMS and booking.group_id is None:
        raise ValueError(f"{template} is for bookings in a group")

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
    notification = Notification.objects.select_related(
        'booking__guest', 'booking__room__room_type', 'booking__group').get(pk=notification_id)
    if notification.status == Notification.Status.SENT:
        return 'already sent'
    booking = notification.booking
    context = _context(notification.template, booking)
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
    """The final invoice goes with the check-out thank-you (every room's, for a group)."""
    if template not in ('checked_out', 'group_checked_out'):
        return ()
    from billing.models import Folio
    from billing.pdf import render_invoice

    bookings = group_rooms(template, booking) if template == 'group_checked_out' else [booking]
    attachments = []
    for folio in Folio.objects.filter(booking__in=bookings).order_by('booking_id'):
        invoice = folio.invoices.order_by('-issued_at').first()
        if invoice:
            attachments.append((f'{invoice.number}.pdf', render_invoice(invoice), 'application/pdf'))
    return attachments


@task
def send_pre_arrival_reminders():
    """
    Remind guests arriving tomorrow. Safe to run often: each booking is
    reminded once, and a group gets one reminder (on its first room) listing every room.
    """
    from hotel.clock import business_date

    tomorrow = business_date() + timedelta(days=1)
    bookings = (Booking.objects.filter(status=Booking.Status.CONFIRMED, check_in_date=tomorrow)
                .select_related('guest').order_by('pk'))
    reminded_groups = set()
    for booking in bookings:
        if booking.group_id is None:
            notify('pre_arrival', booking)
        elif booking.group_id not in reminded_groups:
            reminded_groups.add(booking.group_id)
            # Checked group-wide: the first room may have changed since an earlier run (one cancelled)
            if not Notification.objects.filter(template='group_pre_arrival', booking__group_id=booking.group_id).exists():
                notify('group_pre_arrival', booking)
    return bookings.count()


@task
def expire_payment_holds():
    from booking.lifecycle import expire_holds
    return expire_holds()


@task
def generate_housekeeping_tasks():
    from housekeeping.services import generate_daily_tasks
    return generate_daily_tasks()
