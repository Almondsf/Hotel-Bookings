"""
Gunicorn settings for the API, tunable from the environment.

Each worker process runs several threads, so a request waiting on a payment
gateway (Paystack/Flutterwave calls take a second or more) doesn't hold up
the others. Concurrent requests per container = workers x threads. Each
process has its own database pool: keep DB_POOL_MAX_SIZE at least
GUNICORN_THREADS, and workers x DB_POOL_MAX_SIZE (x containers) under the
database's max_connections.
"""
import multiprocessing
import os

bind = os.environ.get('GUNICORN_BIND', '0.0.0.0:8000')
# 2 per CPU (+1) is gunicorn's usual guidance; capped so a big machine doesn't open too many DB pools
workers = int(os.environ.get('GUNICORN_WORKERS', min(multiprocessing.cpu_count() * 2 + 1, 9)))
worker_class = 'gthread'
threads = int(os.environ.get('GUNICORN_THREADS', 4))
timeout = int(os.environ.get('GUNICORN_TIMEOUT', 60))   # matches nginx's proxy_read_timeout
graceful_timeout = 30
keepalive = 5   # nginx keeps connections to us open (upstream keepalive)
# Recycle workers now and then so a slow memory leak can never build up
max_requests = int(os.environ.get('GUNICORN_MAX_REQUESTS', 2000))
max_requests_jitter = 200
accesslog = '-'
forwarded_allow_ips = '*'  # only nginx can reach the container
