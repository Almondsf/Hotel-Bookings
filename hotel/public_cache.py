"""
Short-lived server-side cache for public, read-mostly API responses (the
room types every page of the guest site loads). Entries are keyed by a
version number that any change to the underlying data bumps, so an edit by
staff shows at once everywhere (the cache is shared between processes);
PUBLIC_CACHE_SECONDS only bounds how long an entry lives when nothing changes.
Nothing is cached in the browser, so staff screens never show stale data.
"""
import json

from django.conf import settings
from django.core.cache import cache
from django.core.serializers.json import DjangoJSONEncoder

VERSION_KEY = 'public-cache:version'


def _version():
    return cache.get_or_set(VERSION_KEY, 1, timeout=None)


def invalidate(*args, **kwargs):
    """Forget every cached public response (usable directly as a signal receiver)."""
    try:
        cache.incr(VERSION_KEY)
    except ValueError:  # not set yet, or evicted
        cache.set(VERSION_KEY, 2, timeout=None)


def cached(name, request, build):
    """
    The response data for this request from the cache, or build() it and
    cache it. `name` identifies the endpoint; the full path (with query
    string) the variant. The data is stored as plain JSON.
    """
    if not settings.PUBLIC_CACHE_SECONDS:
        return build()
    key = f'public-cache:{_version()}:{name}:{request.get_full_path()}'
    data = cache.get(key)
    if data is None:
        data = json.loads(json.dumps(build(), cls=DjangoJSONEncoder))
        cache.set(key, data, timeout=settings.PUBLIC_CACHE_SECONDS)
    return data
