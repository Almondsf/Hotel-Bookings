"""Booking events other apps react to, without the booking app depending on them."""
from django.dispatch import Signal

# Sent once with the bookings created or updated in bulk (bulk_create and bulk_update send no
# post_save), so listeners such as the channel manager still hear about them. Argument: bookings.
bookings_saved = Signal()
