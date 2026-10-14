from rest_framework.throttling import ScopedRateThrottle, SimpleRateThrottle

from .models import normalize_email


class LoginIPThrottle(ScopedRateThrottle):
    """Attempts per client IP, using the view's `login_ip_throttle_scope`."""
    scope_attr = 'login_ip_throttle_scope'


class EmailThrottle(SimpleRateThrottle):
    """
    Attempts per target email regardless of IP, so a distributed attack on a
    single account is still slowed down. Uses the view's `email_throttle_scope`.
    """

    def __init__(self):
        # The rate depends on the view, so it's resolved in allow_request.
        pass

    def allow_request(self, request, view):
        self.scope = getattr(view, 'email_throttle_scope', None)
        if not self.scope:
            return True
        self.rate = self.get_rate()
        self.num_requests, self.duration = self.parse_rate(self.rate)
        return super().allow_request(request, view)

    def get_cache_key(self, request, view):
        email = request.data.get('email') if hasattr(request.data, 'get') else None
        email = normalize_email(email if isinstance(email, str) else '')
        if not email:
            return None
        return self.cache_format % {'scope': self.scope, 'ident': email}
