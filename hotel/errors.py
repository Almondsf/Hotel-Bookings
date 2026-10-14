from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


class DomainError(Exception):
    """
    An expected business-rule failure, safe to show to the client.

    Raised from services; turned into an HTTP response by `exception_handler`,
    so views don't need try/except around every service call.
    """
    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, message, field=None):
        super().__init__(message)
        self.message = message
        self.field = field

    def as_response_data(self):
        return {self.field: [self.message]} if self.field else {"error": self.message}


class ConflictError(DomainError):
    """The request is valid but conflicts with current state (e.g. room just taken)."""
    status_code = status.HTTP_409_CONFLICT


class ForbiddenError(DomainError):
    """The user is signed in but not allowed to do this particular thing."""
    status_code = status.HTTP_403_FORBIDDEN


def exception_handler(exc, context):
    if isinstance(exc, DomainError):
        return Response(exc.as_response_data(), status=exc.status_code)
    return drf_exception_handler(exc, context)
