from django.urls import path
from rest_framework.routers import SimpleRouter

from .staff_views import GuestViewSet, ReservationViewSet, RoomBoardView, WalkInView

router = SimpleRouter()
router.register('reservations', ReservationViewSet, basename='reservation')
router.register('guests', GuestViewSet, basename='guest')

urlpatterns = [
    path('front-desk/walk-in/', WalkInView.as_view(), name='walk-in'),
    path('front-desk/room-board/', RoomBoardView.as_view(), name='room-board'),
    *router.urls,
]
