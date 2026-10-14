from django.urls import path
from .views import (
    RoomCreateView,
    RoomTypeUpdateView,
    RoomUpdateView,
    RoomListView,
    RoomTypeCreateView,
    RoomTypeDetailView,
    RoomTypeListView,
    RoomTypeSearchView,
)

urlpatterns = [
    path('create-room-type/', RoomTypeCreateView.as_view(), name='create-room-type'),
    path('create/', RoomCreateView.as_view(), name='create-room'),
    path('types/<int:pk>/', RoomTypeUpdateView.as_view(), name='room-type-update'),
    path('all/<int:pk>/', RoomUpdateView.as_view(), name='room-update'),
    path('search/', RoomTypeSearchView.as_view(), name='room-type-search'),
    path('types/', RoomTypeListView.as_view(), name='room-type-list'),
    path('all/', RoomListView.as_view(), name='room-list'),
    path('<slug:slug>/', RoomTypeDetailView.as_view(), name='room-type-detail'),
]