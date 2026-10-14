"""
Online payments. The rule throughout: never trust the browser or the webhook
body for the outcome. Always re-verify with the gateway, check amount and
currency, and settle idempotently under a row lock.
"""
import logging
import secrets

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from audit.models import AuditLog
from audit.services import record
from billing import services as billing
from billing.models import PaymentMethod
from hotel.errors import DomainError
from hotel.money import money

from .gateways import GatewayError, get_gateway
from .models import PaymentTransaction

logger = logging.getLogger(__name__)

Status = PaymentTransaction.Status
METHOD_FOR_GATEWAY = {
    PaymentTransaction.Gateway.PAYSTACK: PaymentMethod.PAYSTACK,
    PaymentTransaction.Gateway.FLUTTERWAVE: PaymentMethod.FLUTTERWAVE,
}


class PaymentError(DomainError):
    pass


def new_reference():
    return 'PAY-' + secrets.token_hex(10).upper()


def start_payment(*, gateway, folio, amount, email, purpose, booking=None, customer_name='', description=''):
    """Create a transaction and get the gateway's checkout URL for it."""
    amount = money(amount)
    if amount <= 0:
        raise PaymentError("Nothing to pay.", field='amount')
    provider = get_gateway(gateway)
    txn = PaymentTransaction.objects.create(
        reference=new_reference(), gateway=gateway, purpose=purpose, booking=booking, folio=folio,
        amount=amount, currency=folio.currency, email=email,
    )
    initialized = provider.initialize(
        reference=txn.reference, amount=amount, currency=txn.currency, email=email,
        callback_url=settings.PAYMENT_CALLBACK_URL, customer_name=customer_name, description=description,
    )
    txn.authorization_url = initialized.authorization_url
    txn.save(update_fields=['authorization_url', 'updated_at'])
    return txn


def _flag(txn, reason):
    txn.status = Status.NEEDS_REVIEW
    txn.review_reason = reason
    txn.save(update_fields=['status', 'review_reason', 'updated_at'])
    record(AuditLog.Action.PAYMENT_NEEDS_REVIEW, target=txn, changes={'reason': reason})
    logger.warning("Payment %s needs review: %s", txn.reference, reason)


def confirm_payment(reference):
    """
    Settle a transaction after the guest pays. Safe to call any number of
    times, from the redirect and the webhook concurrently.
    """
    with transaction.atomic():
        # The lock is held across the gateway call on purpose: it makes the
        # redirect and the webhook take turns, so a payment settles once.
        txn = PaymentTransaction.objects.select_for_update().get(reference=reference)
        if txn.status != Status.INITIALIZED:
            return txn  # already handled

        verification = get_gateway(txn.gateway).verify(txn.reference)
        txn.gateway_transaction_id = verification.gateway_transaction_id
        txn.gateway_response = verification.raw
        if not verification.succeeded:
            if verification.status in ('failed', 'abandoned', 'cancelled'):
                txn.status = Status.FAILED
            txn.save(update_fields=['status', 'gateway_transaction_id', 'gateway_response', 'updated_at'])
            return txn
        if verification.currency != txn.currency or money(verification.amount) != txn.amount:
            txn.save(update_fields=['gateway_transaction_id', 'gateway_response', 'updated_at'])
            _flag(txn, f"Paid {verification.amount} {verification.currency}, expected {txn.amount} {txn.currency}")
            return txn

        txn.folio_payment = billing.record_payment(
            txn.folio, method=METHOD_FOR_GATEWAY[txn.gateway], amount=txn.amount, reference=txn.reference,
            notes=f"{txn.get_gateway_display()} {txn.gateway_transaction_id}",
        )
        txn.status = Status.SUCCEEDED
        txn.settled_at = timezone.now()
        txn.save(update_fields=['status', 'folio_payment', 'gateway_transaction_id', 'gateway_response',
                                'settled_at', 'updated_at'])
    record(AuditLog.Action.ONLINE_PAYMENT_SUCCEEDED, target=txn,
           changes={'gateway': txn.gateway, 'amount': str(txn.amount), 'folio': txn.folio.number})

    if txn.purpose == PaymentTransaction.Purpose.BOOKING_PREPAYMENT:
        _confirm_booking_or_refund(txn)
    return txn


def _confirm_booking_or_refund(txn):
    from booking import lifecycle
    from booking.exceptions import BookingError

    try:
        lifecycle.confirm_paid_booking(txn.booking)
    except BookingError as e:
        # Paid after the hold lapsed and the room was sold: give the money back
        logger.warning("Refunding %s: booking could not be confirmed (%s)", txn.reference, e.message)
        try:
            refund_transaction(txn, amount=txn.amount, reason=f"Booking could not be confirmed: {e.message}")
        except DomainError as refund_error:
            _flag(txn, f"Automatic refund failed: {refund_error.message}")
        return
    from booking.services import send_booking_confirmation
    send_booking_confirmation(txn.booking)


def refund_transaction(txn, *, amount, reason, request=None):
    """Refund (part of) a gateway payment to the payer's card/account."""
    amount = money(amount)
    with transaction.atomic():
        txn = PaymentTransaction.objects.select_for_update().get(pk=txn.pk)
        if txn.status not in (Status.SUCCEEDED, Status.NEEDS_REVIEW) or not txn.folio_payment_id:
            raise PaymentError("Only settled payments can be refunded.")
        if amount <= 0 or txn.refunded_amount + amount > txn.amount:
            raise PaymentError(f"Refund must be between 0 and {txn.amount - txn.refunded_amount}.", field='amount')

        # Record on the folio first (checks the folio's credit), then ask the
        # gateway; a gateway failure rolls the folio entry back.
        billing.refund(txn.folio, amount=amount, method=METHOD_FOR_GATEWAY[txn.gateway], reference=txn.reference,
                       reason=reason, request=request)
        response = get_gateway(txn.gateway).refund(
            gateway_transaction_id=txn.gateway_transaction_id, reference=txn.reference,
            amount=amount, currency=txn.currency,
        )
        txn.refunded_amount += amount
        if txn.refunded_amount == txn.amount:
            txn.status = Status.REFUNDED
        txn.gateway_response = {**txn.gateway_response, 'refund': response}
        txn.save(update_fields=['refunded_amount', 'status', 'gateway_response', 'updated_at'])
    return txn


__all__ = ['GatewayError', 'PaymentError', 'confirm_payment', 'refund_transaction', 'start_payment']
