from django.apps import AppConfig


class DistributionConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'distribution'
    verbose_name = 'Channel manager'

    def ready(self):
        from django.db.models.signals import post_save

        from booking.models import Booking

        def booking_changed(sender, instance, **kwargs):
            from .services import schedule_push
            schedule_push(instance)

        def bookings_saved(sender, bookings, **kwargs):
            from .services import schedule_push
            schedule_push(*bookings)

        # Any booking change can move availability; republish just those dates
        post_save.connect(booking_changed, sender=Booking, dispatch_uid='distribution.booking_changed')
        from booking.signals import bookings_saved as bulk_saved
        bulk_saved.connect(bookings_saved, dispatch_uid='distribution.bookings_saved')
