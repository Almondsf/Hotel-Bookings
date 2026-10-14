from django.urls import path

from .views import BookingKeysView, RevokeKeysView

urlpatterns = [
    path('bookings/<int:booking_id>/keys/', BookingKeysView.as_view(), name='booking-keys'),
    path('bookings/<int:booking_id>/keys/revoke/', RevokeKeysView.as_view(), name='booking-keys-revoke'),
]
