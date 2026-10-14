"""
Posting to folios. All money movement goes through here so balances,
taxes, locking and the audit trail stay consistent. Nothing is ever deleted:
mistakes are voided with a reason.
"""
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from audit.models import AuditLog
from audit.services import record
from billing.exceptions import BillingError, FolioClosedError
from billing.models import (
    AccountPayment,
    Charge,
    ChargeCategory,
    CorporateAccount,
    ExchangeRate,
    Folio,
    FolioPayment,
    Invoice,
    InvoiceSequence,
)
from billing.taxes import compute_taxes
from hotel.clock import business_date
from hotel.money import ZERO, money


def _actor(request):
    return request.user if request is not None and request.user.is_authenticated else None


def _lock(folio):
    return Folio.objects.select_for_update().get(pk=folio.pk)


def _ensure_open(folio):
    if folio.status != Folio.Status.OPEN:
        raise FolioClosedError(f"Folio {folio.number} is {folio.get_status_display().lower()}.")


def folio_for(booking):
    """The booking's folio, created on first use."""
    folio, _ = Folio.objects.get_or_create(
        booking=booking, defaults={'guest_id': booking.guest_id, 'currency': settings.HOTEL_CURRENCY},
    )
    return folio


def open_non_guest_folio(*, name, guest=None, request=None):
    """A bill for someone not staying (restaurant walk-in, event client)."""
    folio = Folio.objects.create(name=name, guest=guest, currency=settings.HOTEL_CURRENCY)
    record(AuditLog.Action.FOLIO_OPENED, request=request, target=folio)
    return folio


# --- Charges -----------------------------------------------------------------

def post_charge(folio, *, category, description, unit_price, quantity=1, service_date=None,
                source='', booking_night=None, request=None, actor=None):
    unit_price, quantity = money(unit_price), Decimal(quantity)
    if quantity <= 0:
        raise BillingError("Quantity must be positive.", field='quantity')
    if category == ChargeCategory.ALLOWANCE:
        if unit_price >= 0:
            raise BillingError("Allowances must be negative amounts.", field='unit_price')
    elif unit_price < 0:
        raise BillingError("Only allowances can be negative.", field='unit_price')

    net = money(unit_price * quantity)
    # Allowances are negative, so rules covering them reduce the tax too
    tax_total, tax_lines = compute_taxes(category, net)

    with transaction.atomic():
        folio = _lock(folio)
        _ensure_open(folio)
        charge = Charge.objects.create(
            folio=folio, category=category, description=description, quantity=quantity, unit_price=unit_price,
            net_amount=net, tax_amount=tax_total, total_amount=net + tax_total, tax_lines=tax_lines,
            service_date=service_date or business_date(), source=source, booking_night=booking_night,
            posted_by=actor or _actor(request),
        )
    record(AuditLog.Action.CHARGE_POSTED, request=request, actor=actor, target=charge,
           changes={'folio': folio.number, 'category': category, 'total': str(charge.total_amount)})
    return charge


def void_charge(charge, *, reason, request=None):
    if not reason:
        raise BillingError("A reason is required to void a charge.", field='reason')
    with transaction.atomic():
        folio = _lock(charge.folio)
        _ensure_open(folio)
        charge = Charge.objects.select_for_update().get(pk=charge.pk)
        if charge.is_void:
            raise BillingError("This charge is already void.")
        charge.is_void = True
        charge.void_reason = reason
        charge.voided_by = _actor(request)
        charge.voided_at = timezone.now()
        charge.save(update_fields=['is_void', 'void_reason', 'voided_by', 'voided_at'])
    record(AuditLog.Action.CHARGE_VOIDED, request=request, target=charge,
           changes={'folio': folio.number, 'total': str(charge.total_amount), 'reason': reason})
    return charge


def transfer_charge(charge, to_folio, *, reason='', request=None):
    """Move a charge to another open folio (split billing)."""
    if to_folio.pk == charge.folio_id:
        raise BillingError("The charge is already on this folio.")
    with transaction.atomic():
        # Lock both folios in id order to avoid deadlocks
        first, second = sorted([charge.folio_id, to_folio.pk])
        locked = {f.pk: f for f in Folio.objects.select_for_update().filter(pk__in=[first, second]).order_by('pk')}
        for folio in locked.values():
            _ensure_open(folio)
        charge = Charge.objects.select_for_update().get(pk=charge.pk)
        if charge.is_void:
            raise BillingError("Void charges can't be transferred.")
        from_folio = locked[charge.folio_id]
        charge.transferred_from = from_folio
        charge.folio = locked[to_folio.pk]
        charge.save(update_fields=['folio', 'transferred_from'])
    record(AuditLog.Action.CHARGE_TRANSFERRED, request=request, target=charge,
           changes={'from': from_folio.number, 'to': to_folio.number, 'reason': reason})
    return charge


def post_room_charges(booking, *, through_date, request=None, actor=None):
    """
    Post the room rate for every night of `booking` up to and including
    `through_date` that isn't posted yet. Safe to call repeatedly.
    """
    folio = folio_for(booking)
    posted = []
    nights = booking.nightly_rates.filter(date__lte=through_date).exclude(charges__is_void=False)
    for night in nights.order_by('date'):
        posted.append(post_charge(
            folio, category=ChargeCategory.ROOM,
            description=f"Room {booking.room.room_number} - {night.date:%a %d %b %Y}",
            unit_price=night.rate, service_date=night.date, booking_night=night,
            source=f'booking.night:{night.pk}', request=request, actor=actor,
        ))
    return posted


# --- Payments ----------------------------------------------------------------

def latest_rate(currency):
    rate = ExchangeRate.objects.filter(currency=currency.upper()).first()
    if rate is None:
        raise BillingError(f"No exchange rate is set for {currency.upper()}.", field='currency')
    return rate.rate


def record_payment(folio, *, method, amount=None, currency=None, tendered_amount=None, reference='',
                   notes='', request=None, actor=None):
    """
    Take a payment. In the hotel currency pass `amount`; in a foreign
    currency pass `currency` and `tendered_amount` and it is converted at the
    current exchange rate.
    """
    tendered_currency, rate = '', None
    if currency and currency.upper() != folio.currency:
        if tendered_amount is None or Decimal(tendered_amount) <= 0:
            raise BillingError("Enter the amount tendered in the foreign currency.", field='tendered_amount')
        tendered_currency = currency.upper()
        rate = latest_rate(tendered_currency)
        amount = money(Decimal(tendered_amount) * rate)
    if amount is None or money(amount) <= 0:
        raise BillingError("Payment amount must be positive.", field='amount')

    with transaction.atomic():
        folio = _lock(folio)
        _ensure_open(folio)
        payment = FolioPayment.objects.create(
            folio=folio, kind=FolioPayment.Kind.PAYMENT, method=method, amount=money(amount),
            tendered_currency=tendered_currency, tendered_amount=tendered_amount if tendered_currency else None,
            exchange_rate=rate, reference=reference, notes=notes, received_by=actor or _actor(request),
            service_date=business_date(),
        )
    record(AuditLog.Action.PAYMENT_RECEIVED, request=request, actor=actor, target=payment,
           changes={'folio': folio.number, 'method': method, 'amount': str(payment.amount),
                    'tendered': f'{tendered_amount} {tendered_currency}' if tendered_currency else None})
    return payment


def refund(folio, *, amount, method, reference='', reason='', request=None, actor=None):
    """Return money to the guest. Limited to the folio's credit balance."""
    amount = money(amount)
    if amount <= 0:
        raise BillingError("Refund amount must be positive.", field='amount')
    if not reason:
        raise BillingError("A reason is required for refunds.", field='reason')
    with transaction.atomic():
        folio = _lock(folio)
        credit = -folio.balance
        if amount > credit:
            raise BillingError(f"Refund exceeds the folio's credit balance of {money(max(credit, ZERO))}.",
                               field='amount')
        payment = FolioPayment.objects.create(
            folio=folio, kind=FolioPayment.Kind.REFUND, method=method, amount=amount, reference=reference,
            notes=reason, received_by=actor or _actor(request), service_date=business_date(),
        )
    record(AuditLog.Action.REFUND_ISSUED, request=request, actor=actor, target=payment,
           changes={'folio': folio.number, 'method': method, 'amount': str(amount), 'reason': reason})
    return payment


def void_payment(payment, *, reason, request=None):
    if not reason:
        raise BillingError("A reason is required to void a payment.", field='reason')
    with transaction.atomic():
        folio = _lock(payment.folio)
        _ensure_open(folio)
        payment = FolioPayment.objects.select_for_update().get(pk=payment.pk)
        if payment.is_void:
            raise BillingError("This payment is already void.")
        payment.is_void = True
        payment.void_reason = reason
        payment.voided_by = _actor(request)
        payment.voided_at = timezone.now()
        payment.save(update_fields=['is_void', 'void_reason', 'voided_by', 'voided_at'])
    record(AuditLog.Action.PAYMENT_VOIDED, request=request, target=payment,
           changes={'folio': folio.number, 'amount': str(payment.amount), 'reason': reason})
    return payment


# --- Closing -----------------------------------------------------------------

def _next_invoice_number():
    year = timezone.localdate().year
    sequence, _ = InvoiceSequence.objects.select_for_update().get_or_create(year=year)
    sequence.last_number += 1
    sequence.save(update_fields=['last_number'])
    return f"{settings.INVOICE_PREFIX}-{year}-{sequence.last_number:06d}"


def _snapshot(folio):
    charges = folio.charges.filter(is_void=False).order_by('service_date', 'id')
    payments = folio.payments.filter(is_void=False).order_by('received_at', 'id')
    booking = folio.booking
    tax_summary = {}
    for charge in charges:
        for line in charge.tax_lines:
            entry = tax_summary.setdefault(line['code'], {'name': line['name'], 'rate': line['rate'], 'amount': ZERO})
            entry['amount'] += money(line['amount'])
    return {
        'hotel': {
            'name': settings.HOTEL_NAME, 'address': settings.HOTEL_ADDRESS, 'phone': settings.HOTEL_PHONE,
            'email': settings.HOTEL_EMAIL, 'tax_id': settings.HOTEL_TAX_ID,
        },
        'folio': folio.number,
        'currency': folio.currency,
        'bill_to': {
            'name': folio.account.name if folio.account_id else folio.display_name,
            'company_tax_id': folio.account.tax_id if folio.account_id else '',
            'email': folio.guest.email if folio.guest_id else '',
        },
        'stay': {
            'confirmation_number': booking.confirmation_number,
            'room': booking.room.room_number,
            'check_in_date': str(booking.check_in_date),
            'check_out_date': str(booking.check_out_date),
        } if booking else None,
        'charges': [{
            'date': str(c.service_date), 'description': c.description, 'category': c.category,
            'quantity': str(c.quantity), 'unit_price': str(c.unit_price), 'net': str(c.net_amount),
            'tax': str(c.tax_amount), 'total': str(c.total_amount),
        } for c in charges],
        'payments': [{
            'date': str(p.service_date), 'kind': p.kind, 'method': p.get_method_display(),
            'reference': p.reference, 'amount': str(p.amount),
        } for p in payments],
        'taxes': [{'code': code, 'name': t['name'], 'rate': t['rate'], 'amount': str(t['amount'])}
                  for code, t in tax_summary.items()],
        'totals': {
            'net': str(sum((c.net_amount for c in charges), ZERO)),
            'tax': str(sum((c.tax_amount for c in charges), ZERO)),
            'total': str(folio.charges_total),
            'paid': str(folio.payments_total),
            'balance': str(folio.balance),
        },
    }


def issue_invoice(folio, *, request=None):
    with transaction.atomic():
        folio = _lock(folio)
        invoice = Invoice.objects.create(
            number=_next_invoice_number(), folio=folio, issued_by=_actor(request),
            snapshot=_snapshot(folio), total=folio.charges_total,
        )
    record(AuditLog.Action.INVOICE_ISSUED, request=request, target=invoice,
           changes={'folio': folio.number, 'total': str(invoice.total)})
    return invoice


def settle(folio, *, request=None):
    """Close a fully paid folio and issue its invoice."""
    with transaction.atomic():
        folio = _lock(folio)
        _ensure_open(folio)
        balance = folio.balance
        if balance != 0:
            owed = 'still owes' if balance > 0 else 'is owed'
            raise BillingError(f"Folio {folio.number} {owed} {abs(balance)} {folio.currency}; it can't be settled yet.")
        folio.status = Folio.Status.SETTLED
        folio.closed_at = timezone.now()
        folio.save(update_fields=['status', 'closed_at'])
        invoice = issue_invoice(folio, request=request)
    record(AuditLog.Action.FOLIO_SETTLED, request=request, target=folio)
    return invoice


def transfer_to_account(folio, account, *, request=None):
    """Bill the folio's outstanding balance to a company's city-ledger account."""
    with transaction.atomic():
        account = CorporateAccount.objects.select_for_update().get(pk=account.pk)
        folio = _lock(folio)
        _ensure_open(folio)
        if not account.is_active:
            raise BillingError(f"{account.name}'s account is inactive.", field='account')
        balance = folio.balance
        if balance <= 0:
            raise BillingError("Nothing is owed on this folio; settle it instead.")
        if account.balance + balance > account.credit_limit:
            raise BillingError(
                f"This would exceed {account.name}'s credit limit of {account.credit_limit} "
                f"(current balance {account.balance}).", field='account',
            )
        folio.account = account
        folio.status = Folio.Status.TRANSFERRED
        folio.transferred_at = folio.closed_at = timezone.now()
        folio.save(update_fields=['account', 'status', 'transferred_at', 'closed_at'])
        invoice = issue_invoice(folio, request=request)
    record(AuditLog.Action.FOLIO_TRANSFERRED, request=request, target=folio,
           changes={'account': account.code, 'amount': str(balance)})
    return invoice


def record_account_payment(account, *, amount, method, reference='', request=None):
    amount = money(amount)
    if amount <= 0:
        raise BillingError("Payment amount must be positive.", field='amount')
    payment = AccountPayment.objects.create(account=account, amount=amount, method=method,
                                            reference=reference, received_by=_actor(request))
    record(AuditLog.Action.ACCOUNT_PAYMENT_RECEIVED, request=request, target=account,
           changes={'amount': str(amount), 'method': method, 'reference': reference})
    return payment
