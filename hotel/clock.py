from django.utils import timezone


def business_date():
    """
    The hotel's current business date: the day charges are posted to and
    reports are run for. It moves forward at night audit, not at midnight, so
    a guest arriving at 1am still belongs to the previous business day. Before
    the first night audit it is the local calendar date.
    """
    from nightaudit.models import BusinessDay  # imported late: models import this module

    open_day = BusinessDay.objects.filter(status=BusinessDay.Status.OPEN).values_list('date', flat=True).first()
    return open_day or timezone.localdate()
