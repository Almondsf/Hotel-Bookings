"""
Database and cache settings built from URLs in the environment. Kept as
plain functions so the production choices (connection pooling, a shared
Redis cache) are unit-tested rather than living untested in settings.py.
"""
import environ

POSTGRES = 'django.db.backends.postgresql'


def database_config(url, *, pool=True, pool_min=2, pool_max=10, pool_timeout=10, conn_max_age=60):
    """
    DATABASES['default'] for DATABASE_URL. PostgreSQL connections are reused
    instead of opened per request: with `pool`, through Django's connection
    pool (psycopg_pool; one per server process, so size it to the threads per
    process); without it, by keeping each connection for `conn_max_age`
    seconds. Other databases (SQLite in development) are left as they are.
    """
    config = environ.Env.db_url_config(url)
    if config['ENGINE'] != POSTGRES:
        return config
    if pool:
        # The pool hands out healthy connections itself; CONN_MAX_AGE must stay 0 with it
        config['OPTIONS'] = {**config.get('OPTIONS', {}),
                             'pool': {'min_size': pool_min, 'max_size': pool_max, 'timeout': pool_timeout}}
        config['CONN_MAX_AGE'] = 0
    else:
        config['CONN_MAX_AGE'] = conn_max_age
        config['CONN_HEALTH_CHECKS'] = True
    return config


def cache_config(url):
    """
    CACHES['default'] for CACHE_URL. redis:// and rediss:// use Django's own
    Redis backend (no extra Django package). Anything else is passed to
    django-environ, e.g. locmemcache:// for development and tests.
    """
    if url.startswith(('redis://', 'rediss://')):
        return {'BACKEND': 'django.core.cache.backends.redis.RedisCache', 'LOCATION': url, 'KEY_PREFIX': 'hotel'}
    return environ.Env.cache_url_config(url)


def is_shared_cache(config):
    """Whether every server process sees the same cache (needed for rate limits and the sign-in grace window)."""
    return 'locmem' not in config['BACKEND'].lower() and 'dummy' not in config['BACKEND'].lower()
