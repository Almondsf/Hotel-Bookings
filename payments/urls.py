from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import FlutterwaveWebhookView, PaystackWebhookView, TransactionViewSet, VerifyPaymentView

router = SimpleRouter()
router.register('transactions', TransactionViewSet, basename='payment-transaction')

urlpatterns = [
    path('verify/', VerifyPaymentView.as_view(), name='payment-verify'),
    path('webhooks/paystack/', PaystackWebhookView.as_view(), name='webhook-paystack'),
    path('webhooks/flutterwave/', FlutterwaveWebhookView.as_view(), name='webhook-flutterwave'),
    *router.urls,
]
