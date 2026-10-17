from django.urls import path

from .views import (
    BookingLookupView, CreateBookingView, CreateGroupBookingView, GroupLookupView, GuestCancelBookingView,
    GuestCancelGroupView,
)

urlpatterns = [
    path('create/', CreateBookingView.as_view(), name='create-booking'),
    path('create-group/', CreateGroupBookingView.as_view(), name='create-group-booking'),
    path('lookup/', BookingLookupView.as_view(), name='booking-lookup'),
    path('cancel/', GuestCancelBookingView.as_view(), name='booking-cancel'),
    path('group/lookup/', GroupLookupView.as_view(), name='group-lookup'),
    path('group/cancel/', GuestCancelGroupView.as_view(), name='group-cancel'),
]
