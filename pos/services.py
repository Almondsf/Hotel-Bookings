"""
Selling at outlets. Every settled order is billed through a folio (the
guest's, or a one-off folio when paid on the spot), so taxes, revenue
reports and the cashier report all come from one place.
"""
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, F, Sum
from django.utils import timezone

from audit.models import AuditLog
from audit.services import record
from billing import services as billing
from billing.taxes import active_rules, compute_taxes
from booking.models import Booking
from hotel.errors import ConflictError, DomainError, ForbiddenError
from hotel.money import ZERO, money

from .models import Order, OrderItem, Product


def _ensure_access(outlet, user):
    if not outlet.is_active:
        raise DomainError(f"{outlet.name} is closed.")
    if not outlet.is_open_to(user):
        raise ForbiddenError(f"You can't sell at {outlet.name}.")


def _lock_open(order):
    order = Order.objects.select_for_update(of=('self',)).select_related('outlet').get(pk=order.pk)
    if order.status != Order.Status.OPEN:
        raise ConflictError(f"Order {order.number} is {order.get_status_display().lower()}.")
    return order


def totals(order, rules=None):
    """Net, tax and total of an order as it would be billed. `rules`: tax rules already loaded."""
    rules = active_rules() if rules is None else rules
    net = tax = ZERO
    for item in order.items.all():
        line_net = money(item.unit_price * item.quantity)
        line_tax, _ = compute_taxes(item.charge_category, line_net, rules)
        net += line_net
        tax += line_tax
    return {'net': net, 'tax': tax, 'total': net + tax}


def open_order(outlet, *, user, table_label='', covers=1, notes=''):
    _ensure_access(outlet, user)
    return Order.objects.create(outlet=outlet, table_label=table_label, covers=covers, notes=notes, opened_by=user)


def add_item(order, product, *, quantity, user, notes=''):
    with transaction.atomic():
        order = _lock_open(order)
        _ensure_access(order.outlet, user)
        if product.outlet_id != order.outlet_id:
            raise DomainError(f"{product.name} isn't sold at {order.outlet.name}.", field='product')
        if not product.is_available:
            raise DomainError(f"{product.name} is not available.", field='product')
        return OrderItem.objects.create(
            order=order, product=product, name=product.name, unit_price=product.price,
            charge_category=product.charge_category, quantity=quantity, notes=notes,
        )


def remove_item(order, item, *, user):
    with transaction.atomic():
        order = _lock_open(order)
        _ensure_access(order.outlet, user)
        item.delete()  # nothing has been billed yet, so removing is safe


def _consume_stock(order):
    """Take the order's items out of stock: products locked and updated together."""
    items = list(order.items.all())
    products = {p.pk: p for p in Product.objects.select_for_update()
                .filter(pk__in=sorted({i.product_id for i in items})).order_by('pk')}
    for item in items:
        product = products[item.product_id]
        if product.track_stock:
            if product.stock_quantity < item.quantity:
                raise ConflictError(f"Only {product.stock_quantity} × {product.name} left in stock.")
            product.stock_quantity -= item.quantity
    Product.objects.bulk_update([p for p in products.values() if p.track_stock], ['stock_quantity'])


def _post_items(order, folio, request):
    billing.post_charges([{
        'folio': folio, 'category': item.charge_category,
        'description': f"{order.outlet.name}: {item.name}" + (f" ({item.notes})" if item.notes else ''),
        'unit_price': item.unit_price, 'quantity': item.quantity, 'source': f'pos.order:{order.pk}',
    } for item in order.items.all()], request=request)


def _finish(order, folio, request, booking=None):
    order.status = Order.Status.SETTLED
    order.folio = folio
    order.booking = booking
    order.settled_by = request.user
    order.settled_at = timezone.now()
    order.save(update_fields=['status', 'folio', 'booking', 'settled_by', 'settled_at'])


def find_in_house(room_number):
    return (Booking.objects.select_related('guest', 'room')
            .filter(status=Booking.Status.CHECKED_IN, room__room_number=room_number).first())


def charge_to_room(order, *, room_number, guest_last_name, request):
    """
    Bill the order to an in-house guest's folio. The guest's surname must
    match the room, so nobody can charge to a random room number.
    """
    with transaction.atomic():
        order = _lock_open(order)
        _ensure_access(order.outlet, request.user)
        if not order.items.exists():
            raise DomainError("The order is empty.")
        booking = find_in_house(room_number)
        if booking is None or booking.guest.last_name.strip().lower() != guest_last_name.strip().lower():
            raise DomainError("No in-house guest with that name in that room.", field='guest_last_name')
        folio = billing.folio_for(booking)
        _consume_stock(order)
        _post_items(order, folio, request)
        _finish(order, folio, request, booking=booking)
    record(AuditLog.Action.POS_ORDER_SETTLED, request=request, target=order,
           changes={'to_room': room_number, 'folio': folio.number, 'total': str(totals(order)['total'])})
    return order


def pay_now(order, *, method, tendered_amount=None, reference='', request):
    """
    Settle on the spot: bill a one-off folio, take the payment and close it
    with a receipt (invoice). Returns (order, change_due).
    """
    with transaction.atomic():
        order = _lock_open(order)
        _ensure_access(order.outlet, request.user)
        if not order.items.exists():
            raise DomainError("The order is empty.")
        total = totals(order)['total']
        change = ZERO
        if method == 'CASH':
            tendered = money(tendered_amount if tendered_amount is not None else total)
            if tendered < total:
                raise DomainError(f"Cash tendered is less than the total of {total}.", field='tendered_amount')
            change = tendered - total
        elif not reference:
            raise DomainError("Card and transfer payments need a reference.", field='reference')

        folio = billing.open_non_guest_folio(name=f"{order.outlet.name} {order.number}", request=request)
        _consume_stock(order)
        _post_items(order, folio, request)
        billing.record_payment(folio, method=method, amount=total, reference=reference, request=request)
        billing.settle(folio, request=request)
        _finish(order, folio, request)
    record(AuditLog.Action.POS_ORDER_SETTLED, request=request, target=order,
           changes={'method': method, 'total': str(total), 'folio': folio.number})
    return order, change


def void_order(order, *, reason, request):
    if not reason:
        raise DomainError("A reason is required to void an order.", field='reason')
    with transaction.atomic():
        order = _lock_open(order)
        order.status = Order.Status.VOID
        order.void_reason = reason
        order.save(update_fields=['status', 'void_reason'])
    record(AuditLog.Action.POS_ORDER_VOIDED, request=request, target=order,
           changes={'reason': reason, 'items': order.items.count()})
    return order


def sales_report(start, end):
    """Settled sales by outlet and best sellers, for [start, end]."""
    items = OrderItem.objects.filter(order__status=Order.Status.SETTLED,
                                     order__settled_at__date__range=(start, end))
    by_outlet = (items.values('order__outlet__name')
                 .annotate(orders=Count('order', distinct=True), net=Sum(F('unit_price') * F('quantity')))
                 .order_by('order__outlet__name'))
    best = (items.values('name', 'order__outlet__name')
            .annotate(units=Sum('quantity'), net=Sum(F('unit_price') * F('quantity')))
            .order_by('-units')[:10])
    return {
        'from': start, 'to': end,
        'by_outlet': [{'outlet': r['order__outlet__name'], 'orders': r['orders'], 'net': money(r['net'] or Decimal(0))}
                      for r in by_outlet],
        'best_sellers': [{'product': r['name'], 'outlet': r['order__outlet__name'], 'quantity': r['units'],
                          'net': money(r['net'] or Decimal(0))} for r in best],
    }
