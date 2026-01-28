from .views import CreateBookingView, BookingLookupView
from django.urls import path

urlpatterns = [
    path('create/', CreateBookingView.as_view(), name='create-booking'),
    path('lookup/', BookingLookupView.as_view(), name='booking-lookup'),
]