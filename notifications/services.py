"""
Guest messages. Call notify(...) from business code; delivery happens in a
background job after the surrounding transaction commits, so a slow or
failing provider never slows down or breaks the front desk.
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Prefetch
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
    statuses = GROUP_ROOMS[template]
    if hasattr(booking.group, 'all_rooms'):  # prefetched by deliver_batch
        return [room for room in booking.group.all_rooms if room.status in statuses]
    return list(booking.group.bookings.filter(status__in=statuses).select_related('room__room_type').order_by('pk'))


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
    notify_many(template, [booking])


def notify_many(template, bookings):
    """
    Queue `template` for each booking's guest on each configured channel, at
    most once per booking and channel. After the surrounding transaction
    commits: one query for what was already queued, one insert, one delivery
    job for the batch. Bookings should come with their guest loaded.
    """
    if template not in TEMPLATES:
        raise ValueError(f"Unknown notification template {template}")
    bookings = list(bookings)
    if template in GROUP_ROOMS and any(b.group_id is None for b in bookings):
        raise ValueError(f"{template} is for bookings in a group")

    def enqueue():
        wanted = [(booking, channel, recipient) for booking in bookings for channel in TEMPLATES[template]
                  if (recipient := _recipient(booking, channel))]
        if not wanted:
            return
        done = set(Notification.objects.filter(template=template, booking__in=bookings)
                   .values_list('booking_id', 'channel'))  # already sent / queued
        rows = [Notification(template=template, channel=channel, booking=booking, recipient=recipient)
                for booking, channel, recipient in wanted if (booking.pk, channel) not in done]
        if not rows:
            return
        try:
            with transaction.atomic():
                created = Notification.objects.bulk_create(rows)
        except IntegrityError:
            # Another worker queued some of these meanwhile; keep only what is still missing
            Notification.objects.bulk_create(rows, ignore_conflicts=True)
            created = list(Notification.objects.filter(template=template, booking__in=bookings,
                                                       status=Notification.Status.QUEUED, sent_at__isnull=True))
        deliver_batch.enqueue([n.pk for n in created])
    transaction.on_commit(enqueue)


@task
def deliver(notification_id):
    """Send one message (kept for jobs queued before batches existed)."""
    return deliver_batch.call([notification_id])


@task
def deliver_batch(notification_ids):
    """
    Send queued messages. Each one is its own call to the email/SMS provider;
    the database is read once and updated once for the whole batch. If any
    fail they are marked FAILED and the job is retried; sent ones are skipped.
    """
    notifications = list(
        Notification.objects.filter(pk__in=notification_ids).exclude(status=Notification.Status.SENT)
        .select_related('booking__guest', 'booking__room__room_type', 'booking__group')
        .prefetch_related(Prefetch('booking__group__bookings', to_attr='all_rooms',
                                   queryset=Booking.objects.select_related('room__room_type').order_by('pk')))
    )
    if not notifications:
        return 'already sent'
    failure = None
    for notification in notifications:
        try:
            _send(notification)
        except Exception as e:
            notification.status = Notification.Status.FAILED
            notification.error = str(e)[:500]
            failure = failure or e
        else:
            notification.status = Notification.Status.SENT
            notification.error = ''
            notification.sent_at = timezone.now()
    Notification.objects.bulk_update(notifications, ['status', 'error', 'sent_at', 'provider_message_id'])
    if failure is not None:
        raise failure  # let the worker retry with backoff
    return 'sent'


def _send(notification):
    booking = notification.booking
    context = _context(notification.template, booking)
    if notification.channel == Channel.EMAIL:
        subject = render_to_string(f'notifications/{notification.template}_subject.txt', context).strip()
        body = render_to_string(f'notifications/{notification.template}.txt', context)
        notification.provider_message_id = channels.send_email(
            notification.recipient, subject, body, attachments=_attachments(notification.template, booking))
    else:
        text = render_to_string(f'notifications/{notification.template}_sms.txt', context).strip()
        send = channels.send_sms if notification.channel == Channel.SMS else channels.send_whatsapp
        notification.provider_message_id = send(notification.recipient, text)


def _attachments(template, booking):
    """The final invoice goes with the check-out thank-you (every room's, for a group)."""
    if template not in ('checked_out', 'group_checked_out'):
        return ()
    from billing.models import Invoice
    from billing.pdf import render_invoice

    bookings = group_rooms(template, booking) if template == 'group_checked_out' else [booking]
    latest = {}  # each folio's latest invoice, all read in one query
    for invoice in Invoice.objects.filter(folio__booking__in=bookings).order_by('folio__booking_id', '-issued_at', '-pk'):
        latest.setdefault(invoice.folio_id, invoice)
    return [(f'{invoice.number}.pdf', render_invoice(invoice), 'application/pdf') for invoice in latest.values()]


@task
def send_pre_arrival_reminders():
    """
    Remind guests arriving tomorrow. Safe to run often: each booking is
    reminded once, and a group gets one reminder (on its first room) listing every room.
    """
    from hotel.clock import business_date

    tomorrow = business_date() + timedelta(days=1)
    bookings = list(Booking.objects.filter(status=Booking.Status.CONFIRMED, check_in_date=tomorrow)
                    .select_related('guest').order_by('pk'))
    # Groups are checked group-wide: the first room may have changed since an earlier run (one cancelled)
    reminded = set(Notification.objects.filter(template='group_pre_arrival', booking__group_id__in={
        b.group_id for b in bookings if b.group_id}).values_list('booking__group_id', flat=True))
    group_leads = {}
    for booking in bookings:
        if booking.group_id and booking.group_id not in reminded:
            group_leads.setdefault(booking.group_id, booking)
    notify_many('pre_arrival', [b for b in bookings if b.group_id is None])
    notify_many('group_pre_arrival', group_leads.values())
    return len(bookings)


@task
def expire_payment_holds():
    from booking.lifecycle import expire_holds
    return expire_holds()


@task
def generate_housekeeping_tasks():
    from housekeeping.services import generate_daily_tasks
    return generate_daily_tasks()
