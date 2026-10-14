from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import HousekeepingStaffView, RoomStatusView, TaskViewSet

router = SimpleRouter()
router.register('tasks', TaskViewSet, basename='housekeeping-task')

urlpatterns = [
    path('rooms/', RoomStatusView.as_view(), name='housekeeping-rooms'),
    path('rooms/<int:room_id>/status/', RoomStatusView.as_view(), name='housekeeping-room-status'),
    path('staff/', HousekeepingStaffView.as_view(), name='housekeeping-staff'),
    *router.urls,
]
