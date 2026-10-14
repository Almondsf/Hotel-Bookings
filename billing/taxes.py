from billing.models import TaxRule
from hotel.money import ZERO, money


def active_rules():
    return list(TaxRule.objects.filter(is_active=True))


def compute_taxes(category, net_amount, rules=None):
    """
    Taxes on `net_amount` for a charge category: (tax_total, tax_lines).
    Each rule applies to the net amount (no tax-on-tax).
    """
    rules = active_rules() if rules is None else rules
    lines = []
    for rule in rules:
        if category in rule.categories:
            amount = money(net_amount * rule.rate)
            lines.append({'code': rule.code, 'name': rule.name, 'rate': str(rule.rate), 'amount': str(amount)})
    total = sum((money(line['amount']) for line in lines), ZERO)
    return total, lines


def quote(category, net_amount):
    """Net, taxes and gross for showing a price before it is charged."""
    tax_total, lines = compute_taxes(category, net_amount)
    return {'net': money(net_amount), 'taxes': tax_total, 'gross': money(net_amount) + tax_total, 'tax_lines': lines}
