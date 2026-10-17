from django.conf import settings

from audit.models import AuditLog


def client_ip(request):
    """
    The client's IP. X-Forwarded-For is only trusted for the number of
    proxies we actually run behind (NUM_PROXIES), otherwise any client could
    spoof it.
    """
    num_proxies = settings.REST_FRAMEWORK.get('NUM_PROXIES') or 0
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if num_proxies and forwarded:
        addresses = [a.strip() for a in forwarded.split(',')]
        return addresses[-min(num_proxies, len(addresses))]
    return request.META.get('REMOTE_ADDR')


def record(action, *, request=None, actor=None, actor_email='', target=None, changes=None):
    """Write an audit entry. `actor` defaults to the authenticated request user."""
    entry = _entry(action, request=request, actor=actor, actor_email=actor_email, target=target, changes=changes)
    entry.save()
    return entry


def record_many(action, targets, *, request=None, actor=None, actor_email='', changes=None):
    """
    One audit entry per target, written in a single query. `changes` is a
    dict shared by every entry, or a function of the target.
    """
    entries = [_entry(action, request=request, actor=actor, actor_email=actor_email, target=target,
                      changes=changes(target) if callable(changes) else changes) for target in targets]
    return AuditLog.objects.bulk_create(entries)


def _entry(action, *, request, actor, actor_email, target, changes):
    if actor is None and request is not None and request.user.is_authenticated:
        actor = request.user

    return AuditLog(
        actor=actor,
        actor_email=(actor.email if actor else actor_email)[:255],
        action=action,
        target_type=target._meta.label if target is not None else '',
        target_id=str(target.pk) if target is not None else '',
        target_repr=str(target)[:255] if target is not None else '',
        changes=changes or {},
        ip_address=client_ip(request) if request is not None else None,
        user_agent=request.META.get('HTTP_USER_AGENT', '')[:255] if request is not None else '',
    )
