from hotel.errors import ConflictError, DomainError


class BookingError(DomainError):
    """Base class for expected booking failures that should be shown to the client."""


class RoomUnavailableError(ConflictError, BookingError):
    pass


class InvalidTransitionError(ConflictError, BookingError):
    """The booking's current status doesn't allow the requested action."""

