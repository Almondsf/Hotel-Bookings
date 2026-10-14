from hotel.errors import ConflictError, DomainError


class BillingError(DomainError):
    pass


class FolioClosedError(ConflictError, BillingError):
    pass
