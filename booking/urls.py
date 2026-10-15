from django.urls import path

from .views import BookingLookupView, CreateBookingView, CreateGroupBookingView, GuestCancelBookingView

urlpatterns = [
    path('create/', CreateBookingView.as_view(), name='create-booking'),
    path('create-group/', CreateGroupBookingView.as_view(), name='create-group-booking'),
    path('lookup/', BookingLookupView.as_view(), name='booking-lookup'),
    path('cancel/', GuestCancelBookingView.as_view(), name='booking-cancel'),
]
