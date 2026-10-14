"""
Pricing and eligibility for rate plans.

quote_plans() answers "what can this guest book, at what price?" for a room
type and stay; plan_nightly_rates() prices a stay under one plan.
"""
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from django.db.models import Q

from hotel.clock import business_date
from hotel.money import money
from rooms.services import nightly_rates as bar_nightly_rates

from .models import RatePlan, RateRestriction

WEBSITE = 'WEBSITE'
STAFF = 'STAFF'


class RatePlanUnavailable(Exception):
    def __init__(self, reasons):
        super().__init__('; '.join(reasons))
        self.reasons = reasons


@dataclass
class PlanQuote:
    plan: RatePlan
    rates: list = field(default_factory=list)  # [(date, rate)]
    reasons: list = field(default_factory=list)  # why it can't be booked (empty = bookable)

    @property
    def bookable(self):
        return not self.reasons

    @property
    def total(self):
        return sum((rate for _, rate in self.rates), Decimal('0.00'))


def bar_plan():
    plan, _ = RatePlan.objects.get_or_create(
        code=RatePlan.BAR_CODE, defaults={'name': 'Best Available Rate', 'is_public': True},
    )
    return plan


def plan_nightly_rates(plan, room_type, check_in_date, check_out_date):
    """[(date, rate)] for the stay under `plan`. Raises RatePlanUnavailable if a night has no price."""
    if plan is None or plan.pricing == RatePlan.Pricing.DERIVED:
        rates = bar_nightly_rates(room_type, check_in_date, check_out_date)
        if plan is None or plan.adjustment_percent == 0:
            return rates
        factor = 1 + plan.adjustment_percent / Decimal(100)
        return [(date, money(rate * factor)) for date, rate in rates]

    prices = list(plan.prices.filter(room_type=room_type, start_date__lt=check_out_date, end_date__gte=check_in_date))
    rates, missing = [], []
    day = check_in_date
    while day < check_out_date:
        price = next((p for p in prices if p.start_date <= day <= p.end_date), None)
        if price is None:
            missing.append(day)
        else:
            rates.append((day, price.price))
        day += timedelta(days=1)
    if missing:
        raise RatePlanUnavailable([f"No {plan.code} price for {room_type.name} on {missing[0]}"])
    return rates


def _restriction_reasons(plan, room_type, check_in_date, check_out_date):
    restrictions = RateRestriction.objects.filter(
        Q(rate_plan__isnull=True) | Q(rate_plan=plan),
        Q(room_type__isnull=True) | Q(room_type=room_type),
        start_date__lte=check_out_date, end_date__gte=check_in_date,
    )
    nights = (check_out_date - check_in_date).days
    reasons = []
    for r in restrictions:
        stay_overlaps = r.start_date < check_out_date and r.end_date >= check_in_date
        if r.stop_sell and stay_overlaps:
            reasons.append(f"Not available for sale on some of these dates{f' ({r.note})' if r.note else ''}")
        if r.closed_to_arrival and r.start_date <= check_in_date <= r.end_date:
            reasons.append(f"Arrivals are closed on {check_in_date}")
        if r.closed_to_departure and r.start_date <= check_out_date <= r.end_date:
            reasons.append(f"Departures are closed on {check_out_date}")
        if r.min_stay and r.start_date <= check_in_date <= r.end_date and nights < r.min_stay:
            reasons.append(f"Minimum stay of {r.min_stay} nights for this arrival date")
    return reasons


def _eligibility_reasons(plan, room_type, check_in_date, check_out_date, *, channel, promo_code, account, today):
    reasons = []
    nights = (check_out_date - check_in_date).days
    advance = (check_in_date - today).days

    if not plan.is_active:
        reasons.append("Rate plan is inactive")
    if plan.pk and plan.room_types.exists() and not plan.room_types.filter(pk=room_type.pk).exists():
        reasons.append(f"Not offered for {room_type.name}")
    if channel == WEBSITE and not plan.is_public:
        reasons.append("Not bookable online")
    if plan.promo_code and (promo_code or '').strip().upper() != plan.promo_code:
        reasons.append("Requires a promo code")
    if plan.corporate_account_id and (account is None or account.pk != plan.corporate_account_id):
        reasons.append("Reserved for a corporate account")
    if (plan.sell_from and today < plan.sell_from) or (plan.sell_until and today > plan.sell_until):
        reasons.append("Not on sale today")
    if nights < plan.min_stay:
        reasons.append(f"Minimum stay is {plan.min_stay} nights")
    if plan.max_stay and nights > plan.max_stay:
        reasons.append(f"Maximum stay is {plan.max_stay} nights")
    if advance < plan.min_advance_days:
        reasons.append(f"Must be booked at least {plan.min_advance_days} days ahead")
    if plan.max_advance_days is not None and advance > plan.max_advance_days:
        reasons.append(f"Can only be booked up to {plan.max_advance_days} days ahead")
    if channel == WEBSITE:
        reasons += _restriction_reasons(plan, room_type, check_in_date, check_out_date)
    return reasons


def quote_plan(plan, room_type, check_in_date, check_out_date, *, channel=WEBSITE, promo_code=None, account=None):
    today = business_date()
    quote = PlanQuote(plan=plan)
    quote.reasons = _eligibility_reasons(plan, room_type, check_in_date, check_out_date, channel=channel,
                                         promo_code=promo_code, account=account, today=today)
    try:
        quote.rates = plan_nightly_rates(plan, room_type, check_in_date, check_out_date)
    except RatePlanUnavailable as e:
        quote.reasons += e.reasons
    return quote


def quote_plans(room_type, check_in_date, check_out_date, *, channel=WEBSITE, promo_code=None, account=None):
    """Bookable plans for this stay, cheapest first."""
    bar_plan()  # make sure the reference plan exists
    plans = RatePlan.objects.filter(is_active=True).prefetch_related('room_types')
    quotes = [quote_plan(plan, room_type, check_in_date, check_out_date, channel=channel,
                         promo_code=promo_code, account=account) for plan in plans]
    return sorted((q for q in quotes if q.bookable), key=lambda q: q.total)


def require_plan(plan, room_type, check_in_date, check_out_date, *, channel, promo_code=None, account=None):
    """Price a stay under `plan`, or raise RatePlanUnavailable with the reasons it can't be booked."""
    quote = quote_plan(plan, room_type, check_in_date, check_out_date, channel=channel,
                       promo_code=promo_code, account=account)
    if not quote.bookable:
        raise RatePlanUnavailable(quote.reasons)
    return quote.rates
