from django.db import transaction
from django.utils import timezone

from audit.models import AuditLog
from audit.services import record, record_many
from booking.models import Booking
from hotel.clock import business_date
from hotel.errors import ConflictError, DomainError
from rooms.models import Room

from .models import HousekeepingTask

Task = HousekeepingTask


def set_room_status(room, status, *, request=None, actor=None, reason=''):
    """Change a room's housekeeping status (cleaned, inspected, needs cleaning)."""
    set_rooms_status([room], status, request=request, actor=actor, reasons={room.pk: reason})
    return room


def set_rooms_status(rooms, status, *, request=None, actor=None, reasons=None):
    """
    set_room_status for several rooms in a fixed number of queries (one
    update, one audit insert). `reasons` is {room id: reason}.
    """
    reasons = reasons or {}
    changed = [room for room in rooms if room.housekeeping_status != status]
    if not changed:
        return
    previous = {room.pk: room.housekeeping_status for room in changed}
    Room.objects.filter(pk__in=previous).update(housekeeping_status=status, updated_at=timezone.now())
    for room in changed:
        room.housekeeping_status = status
    record_many(AuditLog.Action.ROOM_HOUSEKEEPING_CHANGED, changed, request=request, actor=actor,
                changes=lambda r: {'from': previous[r.pk], 'to': status, 'reason': reasons.get(r.pk) or None})


def mark_dirty(room, *, request=None, reason=''):
    return set_room_status(room, Room.Housekeeping.DIRTY, request=request, reason=reason)


def generate_daily_tasks(day=None):
    """
    Create today's cleaning list: a departure clean for rooms guests leave
    (or that are dirty), a stay-over service for occupied rooms. Rooms with an
    arrival are flagged rush. Safe to run repeatedly.
    """
    day = day or business_date()
    in_house = {b.room_id: b for b in Booking.objects.filter(status=Booking.Status.CHECKED_IN)}
    arriving = set(Booking.objects.blocking().filter(check_in_date=day).exclude(
        status=Booking.Status.CHECKED_IN).values_list('room_id', flat=True))

    existing = set(Task.objects.filter(date=day).values_list('room_id', 'task_type'))
    new = []
    for room in Room.objects.exclude(status=Room.Status.OUT_OF_SERVICE):
        booking = in_house.get(room.pk)
        if booking and booking.check_out_date > day:
            task_type = Task.TaskType.STAYOVER
        elif (booking and booking.check_out_date <= day) or room.housekeeping_status == Room.Housekeeping.DIRTY:
            task_type = Task.TaskType.DEPARTURE_CLEAN
        else:
            continue
        if (room.pk, task_type) not in existing:
            new.append(Task(room=room, date=day, task_type=task_type, is_rush=room.pk in arriving))
    # ignore_conflicts: another worker may have generated the same tasks meanwhile (unique per room/day/type)
    Task.objects.bulk_create(new, ignore_conflicts=True)
    return len(new)


def _lock(task):
    return Task.objects.select_for_update(of=('self',)).select_related('room').get(pk=task.pk)


def start_task(task, *, request):
    with transaction.atomic():
        task = _lock(task)
        if task.status != Task.Status.PENDING:
            raise ConflictError(f"This task is {task.get_status_display().lower()}.")
        task.status = Task.Status.IN_PROGRESS
        task.started_at = timezone.now()
        if task.assigned_to_id is None:
            task.assigned_to = request.user  # whoever picks it up owns it
        task.save(update_fields=['status', 'started_at', 'assigned_to'])
    return task


def complete_task(task, *, request, notes=''):
    with transaction.atomic():
        task = _lock(task)
        if task.status not in (Task.Status.PENDING, Task.Status.IN_PROGRESS):
            raise ConflictError(f"This task is {task.get_status_display().lower()}.")
        task.status = Task.Status.DONE
        task.completed_at = timezone.now()
        task.completed_by = request.user
        task.notes = notes or task.notes
        task.save(update_fields=['status', 'completed_at', 'completed_by', 'notes'])
        set_room_status(task.room, Room.Housekeeping.CLEAN, request=request, reason=task.get_task_type_display())
    record(AuditLog.Action.HOUSEKEEPING_TASK_UPDATED, request=request, target=task, changes={'status': 'DONE'})
    return task


def skip_task(task, *, request, reason):
    if not reason:
        raise DomainError("Say why the task was skipped (e.g. Do Not Disturb).", field='reason')
    with transaction.atomic():
        task = _lock(task)
        if task.status == Task.Status.DONE:
            raise ConflictError("This task is already done.")
        task.status = Task.Status.SKIPPED
        task.notes = reason
        task.completed_at = timezone.now()
        task.completed_by = request.user
        task.save(update_fields=['status', 'notes', 'completed_at', 'completed_by'])
    record(AuditLog.Action.HOUSEKEEPING_TASK_UPDATED, request=request, target=task,
           changes={'status': 'SKIPPED', 'reason': reason})
    return task
