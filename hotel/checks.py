"""Deployment checks (`manage.py check --deploy`) for running the app with several server processes."""
from django.conf import settings
from django.core.checks import Tags, Warning, register

from hotel.infra import is_shared_cache


@register(Tags.caches, deploy=True)
def shared_cache_check(app_configs, **kwargs):
    """Production runs several processes; an in-memory cache would give each its own rate-limit counters."""
    if is_shared_cache(settings.CACHES['default']):
        return []
    return [Warning(
        "The cache is local to each server process, so rate limits (logins, booking lookups, password resets) "
        "are counted separately per process and the sign-in grace window only works within one process.",
        hint="Set CACHE_URL to a shared cache, e.g. CACHE_URL=redis://redis:6379/0 (docker-compose runs Redis).",
        id='hotel.W001',
    )]
