from django.urls import path
from .views import RoomTypeCreateView, RoomCreateView, RoomTypeSearchView, RoomTypeDetailView, BookingPlanView

urlpatterns = [
    path('create-room-type/', RoomTypeCreateView.as_view(), name='create-room-type'),
    path('create/', RoomCreateView.as_view(), name='create-room'),
    path('search/', RoomTypeSearchView.as_view(), name='room-type-search'),
    path('<slug:slug>/', RoomTypeDetailView.as_view(), name='room-type-detail'),
    path('booking-plans/', BookingPlanView.as_view(), name='booking-plans'),
]