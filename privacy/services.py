"""
Nigeria Data Protection Act 2023: guests' rights over their data.

- Access / portability: export everything held about a guest.
- Erasure: anonymise the guest. Bookings and invoices stay (tax and accounting
  law require them) but no longer identify the person.
- Storage limitation: a retention job anonymises guests who haven't stayed for
  GUEST_RETENTION_DAYS and deletes ID documents GUEST_ID_RETENTION_DAYS after
  the stay they were captured for.
"""
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.tasks import task
from django.utils import timezone

from audit.models import AuditLog
from audit.services import record
from billing.models import Folio
from booking.models import Booking, Guest, GuestIdentification
from hotel.errors import ConflictError

ACTIVE = [Booking.Status.PENDING, Booking.Status.CONFIRMED, Booking.Status.CHECKED_IN]
ANONYMISED_NAME = 'Anonymised'


def export_guest(guest, *, request=None):
    """Everything held about a guest, as JSON-ready data (the NDPA right of access)."""
    bookings = guest.bookings.select_related('room__room_type').order_by('check_in_date')
    folios = Folio.objects.filter(guest=guest).prefetch_related('charges', 'payments')
    data = {
        'exported_at': timezone.now().isoformat(),
        'controller': {'name': settings.HOTEL_NAME, 'email': settings.HOTEL_EMAIL, 'address': settings.HOTEL_ADDRESS},
        'profile': {
            'first_name': guest.first_name, 'last_name': guest.last_name, 'email': guest.email,
            'phone_number': guest.phone_number, 'address': guest.address, 'country': guest.country,
            'nationality': guest.nationality, 'date_of_birth': str(guest.date_of_birth) if guest.date_of_birth else None,
            'company_name': guest.company_name, 'notes': guest.notes, 'accepts_marketing': guest.accepts_marketing,
            'sms_opt_out': guest.sms_opt_out, 'created_at': guest.created_at.isoformat(),
        },
        # Document numbers are included masked; the full number is available on request in person
        'identity_documents': [{
            'type': doc.get_document_type_display(), 'number': doc.masked_number, 'issuing_country': doc.issuing_country,
            'expiry_date': str(doc.expiry_date) if doc.expiry_date else None, 'captured_at': doc.captured_at.isoformat(),
        } for doc in guest.identifications.all()],
        'stays': [{
            'confirmation_number': b.confirmation_number, 'status': b.status, 'room_type': b.room.room_type.name,
            'check_in_date': str(b.check_in_date), 'check_out_date': str(b.check_out_date),
            'adults': b.number_of_adults, 'children': b.number_of_children, 'special_requests': b.special_requests,
            'total_price': str(b.total_price),
        } for b in bookings],
        'bills': [{
            'folio': f.number,
            'charges': [{'date': str(c.service_date), 'description': c.description, 'total': str(c.total_amount)}
                        for c in f.charges.all() if not c.is_void],
            'payments': [{'date': str(p.service_date), 'method': p.get_method_display(), 'amount': str(p.amount)}
                         for p in f.payments.all() if not p.is_void],
        } for f in folios],
        'messages_sent': [{
            'template': n.template, 'channel': n.channel, 'sent_at': n.sent_at.isoformat() if n.sent_at else None,
        } for b in bookings for n in b.notifications.all()],
    }
    record(AuditLog.Action.GUEST_DATA_EXPORTED, request=request, target=guest)
    return data


def anonymise_guest(guest, *, request=None, reason='Guest request'):
    """Erase personal data. Refused while the guest has an active booking or an open bill."""
    with transaction.atomic():
        guest = Guest.objects.select_for_update().get(pk=guest.pk)
        if guest.first_name == ANONYMISED_NAME:
            raise ConflictError("This guest has already been anonymised.")
        if guest.bookings.filter(status__in=ACTIVE).exists():
            raise ConflictError("The guest has a current or upcoming booking; cancel or complete it first.")
        if Folio.objects.filter(guest=guest, status=Folio.Status.OPEN).exists():
            raise ConflictError("The guest has an open bill; settle it first.")

        guest.first_name = ANONYMISED_NAME
        guest.last_name = f'Guest {guest.pk}'
        guest.email = f'anonymised-{guest.pk}@invalid.example'
        guest.phone_number = None
        guest.address = None
        guest.country = None
        guest.nationality = ''
        guest.date_of_birth = None
        guest.company_name = ''
        guest.notes = ''
        guest.is_vip = False
        guest.accepts_marketing = False
        guest.sms_opt_out = True
        guest.save()
        guest.identifications.all().delete()
        guest.bookings.update(special_requests='')
        Folio.objects.filter(guest=guest, name__gt='').update(name=f'Guest {guest.pk}')
        from notifications.models import Notification
        Notification.objects.filter(booking__guest=guest).update(recipient='')
    record(AuditLog.Action.GUEST_ANONYMISED, request=request, target=guest, changes={'reason': reason})
    return guest


def apply_retention(now=None):
    """Storage limitation. Returns (guests anonymised, ID documents deleted)."""
    today = (now or timezone.now()).date()
    id_cutoff = today - timedelta(days=settings.GUEST_ID_RETENTION_DAYS)
    stale_ids = GuestIdentification.objects.exclude(guest__bookings__status__in=ACTIVE).filter(
        captured_at__date__lt=id_cutoff)
    ids_deleted, _ = stale_ids.delete()

    guest_cutoff = today - timedelta(days=settings.GUEST_RETENTION_DAYS)
    candidates = (Guest.objects.exclude(first_name=ANONYMISED_NAME)
                  .annotate(last_stay=Max('bookings__check_out_date'))
                  .filter(last_stay__lt=guest_cutoff))
    anonymised = 0
    for guest in candidates:
        try:
            anonymise_guest(guest, reason='Retention period ended')
            anonymised += 1
        except ConflictError:
            continue
    if anonymised or ids_deleted:
        record(AuditLog.Action.RETENTION_APPLIED, changes={'guests_anonymised': anonymised, 'ids_deleted': ids_deleted})
    return anonymised, ids_deleted


@task
def retention_job():
    anonymised, ids_deleted = apply_retention()
    return {'guests_anonymised': anonymised, 'ids_deleted': ids_deleted}
