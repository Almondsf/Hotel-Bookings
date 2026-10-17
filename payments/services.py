"""
Online payments. The rule throughout: never trust the browser or the webhook
body for the outcome. Always re-verify with the gateway, check amount and
currency, and settle idempotently under a row lock.
"""
import logging
import secrets

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from audit.models import AuditLog
from audit.services import record
from billing import services as billing
from billing.models import Folio, PaymentMethod
from billing.taxes import active_rules
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

        txn.folio_payment = _record_on_folios(txn)
        txn.status = Status.SUCCEEDED
        txn.settled_at = timezone.now()
        txn.save(update_fields=['status', 'folio_payment', 'gateway_transaction_id', 'gateway_response',
                                'settled_at', 'updated_at'])
    record(AuditLog.Action.ONLINE_PAYMENT_SUCCEEDED, target=txn,
           changes={'gateway': txn.gateway, 'amount': str(txn.amount), 'folio': txn.folio.number})

    if txn.purpose == PaymentTransaction.Purpose.BOOKING_PREPAYMENT:
        _confirm_booking_or_refund(txn)
    return txn


def _group_bookings(txn):
    """The bookings a payment covers: the whole group for an online group plan, else just its booking."""
    from booking.models import Booking

    if txn.booking_id is None:
        return []
    if txn.booking.group_id and txn.purpose == PaymentTransaction.Purpose.BOOKING_PREPAYMENT:
        return list(Booking.objects.filter(group_id=txn.booking.group_id).order_by('pk'))
    return [txn.booking]


def _record_on_folios(txn):
    """
    Record a verified payment. A group plan's single payment is split so each
    room's folio receives its own prepaid amount; the lead folio's share is
    the one linked to the transaction. Returns that payment.
    """
    from booking.services import amount_due_online

    method, notes = METHOD_FOR_GATEWAY[txn.gateway], f"{txn.get_gateway_display()} {txn.gateway_transaction_id}"
    bookings = _group_bookings(txn)
    if len(bookings) < 2:
        return billing.record_payment(txn.folio, method=method, amount=txn.amount, reference=txn.reference, notes=notes)

    others = [b for b in bookings if b.pk != txn.booking_id]
    folios, rules = billing.folios_for(others), active_rules()
    shares = [(folios[b.pk], amount_due_online(b, rules)) for b in others]
    lead_share = txn.amount - sum(amount for _, amount in shares)  # absorbs any rounding difference
    if lead_share <= 0:
        raise PaymentError("Group payment doesn't cover the rooms it was taken for.")
    payments = billing.record_payments(shares + [(txn.folio, lead_share)], method=method, reference=txn.reference,
                                       notes=notes)
    return payments[-1]


def _confirm_booking_or_refund(txn):
    from booking import lifecycle
    from booking.exceptions import BookingError

    bookings = _group_bookings(txn)
    try:
        # A group is confirmed whole or not at all: half a group plan is no use to the guests
        with transaction.atomic():
            lifecycle.confirm_paid_bookings(bookings)
    except BookingError as e:
        # Paid after the hold lapsed and the room was sold: give the money back
        logger.warning("Refunding %s: booking could not be confirmed (%s)", txn.reference, e.message)
        try:
            refund_transaction(txn, amount=txn.amount, reason=f"Booking could not be confirmed: {e.message}")
        except DomainError as refund_error:
            _flag(txn, f"Automatic refund failed: {refund_error.message}")
        return
    from booking.services import send_confirmations
    send_confirmations(bookings)


def refund_transaction(txn, *, amount, reason, request=None, folios=None):
    """
    Refund (part of) a gateway payment to the payer's card/account. `folios`
    limits which bills the refund comes off (e.g. only a cancelled room's);
    by default the payment's own folio(s).
    """
    amount = money(amount)
    with transaction.atomic():
        txn = PaymentTransaction.objects.select_for_update().get(pk=txn.pk)
        if txn.status not in (Status.SUCCEEDED, Status.NEEDS_REVIEW) or not txn.folio_payment_id:
            raise PaymentError("Only settled payments can be refunded.")
        if amount <= 0 or txn.refunded_amount + amount > txn.amount:
            raise PaymentError(f"Refund must be between 0 and {txn.amount - txn.refunded_amount}.", field='amount')

        # Record on the folios first (each checks its own credit), then ask the
        # gateway; a gateway failure rolls the folio entries back.
        _refund_on_folios(txn, amount, reason, request, folios)
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


def _refund_on_folios(txn, amount, reason, request, folios=None):
    """
    Take a gateway refund off the folios the payment went to (lead folio
    first), within each one's credit: credits read in one query, refunds
    written together.
    """
    if folios is None:
        others = [b for b in _group_bookings(txn) if b.pk != txn.booking_id]
        folios = [txn.folio, *billing.folios_for(others).values()]
    if len(folios) == 1:
        entries = [(folios[0], amount)]  # billing.refund_many checks it against the folio's credit
    else:
        credits, entries, remaining = billing.folio_credits(folios), [], amount
        for folio in folios:
            take = min(credits[folio.pk], remaining)
            if take > 0:
                entries.append((folio, take))
                remaining -= take
            if remaining <= 0:
                break
        if remaining > 0:
            raise PaymentError(f"Only {amount - remaining} of the refund is owed back to the guest.", field='amount')
    billing.refund_many(entries, method=METHOD_FOR_GATEWAY[txn.gateway], reference=txn.reference, reason=reason,
                        request=request)


def refund_prepaid_remainder(booking, *, request=None):
    """Single-booking form of refund_prepaid_remainders. Returns the amount refunded (0 if none)."""
    return refund_prepaid_remainders([booking], request=request)


def refund_prepaid_remainders(bookings, *, request=None):
    """
    After bookings are cancelled, send back to the guest's card whatever they
    prepaid online beyond the cancellation fees. Only these bookings' bills
    are touched, so cancelling one room of a group plan never refunds the
    others. The credits and payments are read in a fixed number of queries
    and each online payment is refunded once, for all of its rooms together
    (one gateway call per payment, not per room). Returns the total refunded.
    If the gateway refuses, the credit stays on the folios for staff to
    refund, and the reason is audited.
    """
    bookings = list(bookings)
    if not bookings:
        return money(0)
    folios = {folio.booking_id: folio for folio in Folio.objects.filter(booking__in=bookings).with_totals()}
    owed = {b.pk: -folios[b.pk].balance for b in bookings if b.pk in folios and folios[b.pk].balance < 0}
    if not owed:
        return money(0)
    owed_bookings = [b for b in bookings if b.pk in owed]
    groups = {b.group_id for b in owed_bookings if b.group_id}
    candidates = PaymentTransaction.objects.filter(
        Q(booking__in=[b for b in owed_bookings if not b.group_id]) | Q(booking__group_id__in=groups),
        purpose=PaymentTransaction.Purpose.BOOKING_PREPAYMENT, status=Status.SUCCEEDED,
    ).select_related('booking').order_by('-settled_at')
    # The latest online prepayment covering each booking: its own, or its group's
    payment_for = {}
    for txn in candidates:
        key = ('group', txn.booking.group_id) if txn.booking.group_id else ('booking', txn.booking_id)
        payment_for.setdefault(key, txn)
    by_payment = {}
    for booking in owed_bookings:
        txn = payment_for.get(('group', booking.group_id) if booking.group_id else ('booking', booking.pk))
        if txn is not None:  # paid at the desk otherwise: staff refund it the way it was paid
            by_payment.setdefault(txn.pk, (txn, []))[1].append(booking)

    refunded = money(0)
    for txn, covered in by_payment.values():  # one gateway refund per online payment
        amount = min(sum((owed[b.pk] for b in covered), money(0)), txn.amount - txn.refunded_amount)
        if amount <= 0:
            continue
        numbers = ', '.join(b.confirmation_number for b in covered)
        try:
            refund_transaction(txn, amount=amount, request=request, folios=[folios[b.pk] for b in covered],
                               reason=f"Cancellation of {numbers}: prepaid amount beyond the fee")
        except DomainError as e:
            logger.warning("Automatic refund for %s failed: %s", numbers, e.message)
            record(AuditLog.Action.PAYMENT_NEEDS_REVIEW, request=request, target=txn,
                   changes={'booking': numbers, 'refund_due': str(amount), 'reason': e.message})
            continue
        record(AuditLog.Action.ONLINE_PAYMENT_REFUNDED, request=request, target=txn,
               changes={'booking': numbers, 'amount': str(amount), 'automatic': True})
        refunded += amount
    return refunded


__all__ = ['GatewayError', 'PaymentError', 'confirm_payment', 'refund_prepaid_remainder', 'refund_prepaid_remainders',
           'refund_transaction', 'start_payment']
