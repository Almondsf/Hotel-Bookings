from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import InHouseLookupView, OrderViewSet, OutletViewSet, ProductViewSet, SalesReportView

router = SimpleRouter()
router.register('outlets', OutletViewSet, basename='pos-outlet')
router.register('products', ProductViewSet, basename='pos-product')
router.register('orders', OrderViewSet, basename='pos-order')

urlpatterns = [
    path('in-house/', InHouseLookupView.as_view(), name='pos-in-house'),
    path('reports/sales/', SalesReportView.as_view(), name='pos-sales-report'),
    *router.urls,
]
