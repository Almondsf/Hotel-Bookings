from django.db import migrations

STATUS = {'COMPLETED': 'SUCCEEDED', 'FAILED': 'FAILED', 'REFUNDED': 'REFUNDED', 'PENDING': 'NEEDS_REVIEW'}


def copy_legacy(apps, schema_editor):
    """Keep the history of payments taken before the gateway integration."""
    Payment = apps.get_model('booking', 'Payment')
    Folio = apps.get_model('billing', 'Folio')
    PaymentTransaction = apps.get_model('payments', 'PaymentTransaction')
    for payment in Payment.objects.select_related('booking__guest').filter(amount__gt=0):
        booking = payment.booking
        folio, _ = Folio.objects.get_or_create(booking=booking, defaults={'guest_id': booking.guest_id})
        PaymentTransaction.objects.get_or_create(
            reference=f'LEGACY-{payment.pk}',
            defaults={
                'gateway': 'LEGACY', 'purpose': 'BOOKING_PREPAYMENT', 'booking': booking, 'folio': folio,
                'amount': payment.amount, 'currency': folio.currency, 'email': booking.guest.email,
                'status': STATUS.get(payment.status, 'NEEDS_REVIEW'),
                'gateway_transaction_id': payment.transaction_id or '',
                'review_reason': 'Imported from the pre-gateway payment table',
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(copy_legacy, migrations.RunPython.noop),
    ]
