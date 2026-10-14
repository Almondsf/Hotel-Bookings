from django.conf import settings
from django.contrib import admin
from django.urls import path, include

from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.permissions import IsAdminUser

from .views import HealthView, HotelInfoView

urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
    path('api/health/', HealthView.as_view(), name='health'),
    path('api/hotel/', HotelInfoView.as_view(), name='hotel-info'),
    # API reference for integrators: Django-admin staff only, so the attack surface isn't advertised
    path('api/schema/', SpectacularAPIView.as_view(permission_classes=[IsAdminUser]), name='api-schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='api-schema', permission_classes=[IsAdminUser]),
         name='api-docs'),
    path('api/', include('authentication.urls')),
    path('api/audit/', include('audit.urls')),
    path('api/billing/', include('billing.urls')),
    path('api/payments/', include('payments.urls')),
    path('api/rates/', include('rates.urls')),
    path('api/housekeeping/', include('housekeeping.urls')),
    path('api/maintenance/', include('maintenance.urls')),
    path('api/', include('nightaudit.urls')),
    path('api/pos/', include('pos.urls')),
    path('api/distribution/', include('distribution.urls')),
    path('api/locks/', include('locks.urls')),
    path('api/privacy/', include('privacy.urls')),
    path('api/bookings/', include('booking.urls')),
    path('api/', include('booking.staff_urls')),
    path('api/rooms/', include('rooms.urls')),
    
]
