from django.urls import path

from .views import ChannelStatusView, ChannelSyncView, ChannexWebhookView, ResolveChannelBookingView

urlpatterns = [
    path('status/', ChannelStatusView.as_view(), name='channel-status'),
    path('sync/', ChannelSyncView.as_view(), name='channel-sync'),
    path('bookings/<int:pk>/resolve/', ResolveChannelBookingView.as_view(), name='channel-booking-resolve'),
    path('webhooks/channex/', ChannexWebhookView.as_view(), name='webhook-channex'),
]
