from datetime import timedelta

from django.db import migrations


def backfill(apps, schema_editor):
    """Existing bookings only stored an average rate; use it for each of their nights."""
    Booking = apps.get_model('booking', 'Booking')
    BookingNight = apps.get_model('booking', 'BookingNight')
    nights = []
    for booking in Booking.objects.filter(nightly_rates__isnull=True):
        day = booking.check_in_date
        while day < booking.check_out_date:
            nights.append(BookingNight(booking=booking, date=day, rate=booking.price_per_night))
            day += timedelta(days=1)
    BookingNight.objects.bulk_create(nights)


class Migration(migrations.Migration):

    dependencies = [
        ('booking', '0004_guest_company_name_guest_date_of_birth_guest_is_vip_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
