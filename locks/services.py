from datetime import datetime, time

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from audit.models import AuditLog
from audit.services import record
from booking.models import Booking
from hotel.errors import ConflictError, DomainError

from .models import KeyCard
from .systems import lock_system

MAX_CARDS = 4


def _at(day, hhmm):
    return timezone.make_aware(datetime.combine(day, time.fromisoformat(hhmm)))


def issue_keys(booking, *, cards=1, request=None):
    """Encode key cards for an in-house guest, valid until check-out time."""
    if booking.status != Booking.Status.CHECKED_IN:
        raise ConflictError("Keys are issued at check-in, for in-house guests only.")
    if not 1 <= cards <= MAX_CARDS:
        raise DomainError(f"Issue between 1 and {MAX_CARDS} cards.", field='cards')
    valid_from = timezone.now()
    valid_until = _at(booking.check_out_date, settings.HOTEL_CHECK_OUT_TIME)
    external_ids = lock_system().issue(room_number=booking.room.room_number, valid_from=valid_from,
                                       valid_until=valid_until, guest_name=str(booking.guest), cards=cards)
    keys = KeyCard.objects.bulk_create(KeyCard(
        booking=booking, room=booking.room, external_id=external_id, valid_from=valid_from,
        valid_until=valid_until, issued_by=request.user if request else None,
    ) for external_id in external_ids)
    record(AuditLog.Action.KEY_ISSUED, request=request, target=booking,
           changes={'room': booking.room.room_number, 'cards': len(keys)})
    return keys


def revoke_keys(booking, *, reason, room=None, request=None):
    """Revoke the booking's active keys (optionally only those for `room`). Failures don't block the desk."""
    keys = KeyCard.objects.filter(booking=booking, status=KeyCard.Status.ACTIVE)
    if room is not None:
        keys = keys.filter(room=room)
    system = lock_system()
    revoked = 0
    for key in keys:
        try:
            system.revoke(key.external_id)
        except DomainError:
            # Keys expire at check-out time anyway; keep going and flag it
            continue
        with transaction.atomic():
            KeyCard.objects.filter(pk=key.pk).update(status=KeyCard.Status.REVOKED, revoked_at=timezone.now(),
                                                     revoke_reason=reason[:100])
        revoked += 1
    if revoked:
        record(AuditLog.Action.KEY_REVOKED, request=request, target=booking, changes={'cards': revoked, 'reason': reason})
    return revoked
