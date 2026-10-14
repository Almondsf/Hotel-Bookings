"""Request IDs and JSON logs, so one request can be traced through every log line."""
import contextvars
import json
import logging
import re
import uuid

_request_id = contextvars.ContextVar('request_id', default='-')
_SAFE_ID = re.compile(r'^[A-Za-z0-9\-_.]{8,64}$')


class RequestIdMiddleware:
    """
    Use the proxy's X-Request-ID (if well-formed) or make one; echo it back so
    a guest or staff member can quote it when reporting a problem.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = request.headers.get('X-Request-ID', '')
        request_id = incoming if _SAFE_ID.match(incoming) else uuid.uuid4().hex
        token = _request_id.set(request_id)
        request.request_id = request_id
        try:
            response = self.get_response(request)
        finally:
            _request_id.reset(token)
        response['X-Request-ID'] = request_id
        return response


class RequestIdFilter(logging.Filter):
    def filter(self, record):
        record.request_id = _request_id.get()
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line, for log shippers (Loki, CloudWatch, ELK)."""

    def format(self, record):
        entry = {
            'time': self.formatTime(record, '%Y-%m-%dT%H:%M:%S%z'),
            'level': record.levelname,
            'logger': record.name,
            'request_id': getattr(record, 'request_id', '-'),
            'message': record.getMessage(),
        }
        if record.exc_info:
            entry['exception'] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)
