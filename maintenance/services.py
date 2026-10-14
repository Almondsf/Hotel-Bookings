from django.db import transaction
from django.utils import timezone

from audit.models import AuditLog
from audit.services import record
from booking.models import Booking
from hotel.clock import business_date
from hotel.errors import ConflictError, DomainError
from rooms.models import Room, RoomAvailabilityOverride

from .models import MaintenanceTicket

Ticket = MaintenanceTicket
ACTIVE = [Ticket.Status.OPEN, Ticket.Status.IN_PROGRESS, Ticket.Status.ON_HOLD]


def affected_bookings(room, start, end):
    """Bookings that hold this room during [start, end) and need moving."""
    return list(Booking.objects.blocking().overlapping(start, end).filter(room=room)
                .select_related('guest').order_by('check_in_date'))


def report(*, request, room=None, location='', title, description='', category, priority,
           out_of_order_until=None):
    """
    Log a fault. With `out_of_order_until` the room is taken off sale from
    today until that date; bookings in that window are returned so the desk
    can move them.
    """
    if room is None and not location:
        raise DomainError("Give a room or a location.", field='location')
    if out_of_order_until is not None:
        if room is None:
            raise DomainError("Only rooms can be put out of order.", field='out_of_order_until')
        if out_of_order_until <= business_date():
            raise DomainError("Out-of-order must end after today.", field='out_of_order_until')

    with transaction.atomic():
        ticket = Ticket.objects.create(
            room=room, location=location, title=title, description=description, category=category,
            priority=priority, reported_by=request.user,
        )
        conflicts = []
        if out_of_order_until is not None:
            conflicts = _take_out_of_order(ticket, out_of_order_until, request)
    record(AuditLog.Action.MAINTENANCE_TICKET_UPDATED, request=request, target=ticket,
           changes={'event': 'reported', 'priority': priority,
                    'out_of_order_until': str(out_of_order_until) if out_of_order_until else None})
    return ticket, conflicts


def _take_out_of_order(ticket, until, request):
    start = business_date()
    ticket.out_of_order = RoomAvailabilityOverride.objects.create(
        room=ticket.room, start_date=start, end_date=until, reason='MAINTENANCE', note=f"{ticket.number}: {ticket.title}",
    )
    ticket.save(update_fields=['out_of_order'])
    # Off the floor right away unless a guest is still in it
    occupied = Booking.objects.filter(room=ticket.room, status=Booking.Status.CHECKED_IN).exists()
    if not occupied:
        Room.objects.filter(pk=ticket.room_id).update(status=Room.Status.MAINTENANCE, updated_at=timezone.now())
    return [b for b in affected_bookings(ticket.room, start, until) if b.status != Booking.Status.CHECKED_IN]


def _lock(ticket):
    ticket = Ticket.objects.select_for_update(of=('self',)).select_related('room', 'out_of_order').get(pk=ticket.pk)
    if ticket.status not in ACTIVE:
        raise ConflictError(f"Ticket {ticket.number} is already resolved.")
    return ticket


def update_status(ticket, new_status, *, request):
    if new_status not in (Ticket.Status.IN_PROGRESS, Ticket.Status.ON_HOLD):
        raise DomainError("Use resolve to close a ticket.", field='status')
    with transaction.atomic():
        ticket = _lock(ticket)
        ticket.status = new_status
        if ticket.assigned_to_id is None:
            ticket.assigned_to = request.user
        ticket.save(update_fields=['status', 'assigned_to', 'updated_at'])
    record(AuditLog.Action.MAINTENANCE_TICKET_UPDATED, request=request, target=ticket, changes={'status': new_status})
    return ticket


def resolve(ticket, *, request, notes):
    """Close the ticket and give the room back to sale (it needs cleaning after the work)."""
    if not notes:
        raise DomainError("Describe what was done.", field='resolution_notes')
    from housekeeping.services import mark_dirty

    with transaction.atomic():
        ticket = _lock(ticket)
        ticket.status = Ticket.Status.RESOLVED
        ticket.resolution_notes = notes
        ticket.resolved_at = timezone.now()
        ticket.resolved_by = request.user
        ticket.save(update_fields=['status', 'resolution_notes', 'resolved_at', 'resolved_by', 'updated_at'])

        block = ticket.out_of_order
        if block is not None:
            today = business_date()
            if block.start_date >= today:
                block.delete()
            elif block.end_date > today:
                block.end_date = today  # stop blocking from today; keep the history
                block.save(update_fields=['end_date'])
            Room.objects.filter(pk=ticket.room_id, status=Room.Status.MAINTENANCE).update(
                status=Room.Status.AVAILABLE, updated_at=timezone.now())
        if ticket.room_id:
            mark_dirty(ticket.room, request=request, reason=f"After maintenance {ticket.number}")
    record(AuditLog.Action.MAINTENANCE_TICKET_UPDATED, request=request, target=ticket, changes={'status': 'RESOLVED'})
    return ticket

