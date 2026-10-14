from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal('0.01')
ZERO = Decimal('0.00')


def money(value):
    """Round to kobo/cents, half-up (how invoices are expected to round)."""
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)
