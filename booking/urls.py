from .views import CreateBookingView
from django.urls import path

urlpatterns = [
    path('create/', CreateBookingView.as_view(), name='create-booking'),
]