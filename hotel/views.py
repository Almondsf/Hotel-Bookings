from django.conf import settings
from django.db import connection
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from booking.policies import describe_cancellation_policy


class HealthView(APIView):
    """For load balancers and uptime monitors: 200 if the app can reach its database."""
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = []

    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
        except Exception:
            return Response({'status': 'unavailable'}, status=503)
        return Response({'status': 'ok'})


class HotelInfoView(APIView):
    """Public facts the guest website needs: name, contacts, times, policies, payment options."""
    permission_classes = [AllowAny]

    def get(self, request):
        from payments.gateways import enabled_gateways

        return Response({
            'name': settings.HOTEL_NAME,
            'address': settings.HOTEL_ADDRESS,
            'phone': settings.HOTEL_PHONE,
            'email': settings.HOTEL_EMAIL,
            'currency': settings.HOTEL_CURRENCY,
            'check_in_time': settings.HOTEL_CHECK_IN_TIME,
            'check_out_time': settings.HOTEL_CHECK_OUT_TIME,
            'cancellation_policy': describe_cancellation_policy(),
            'payment_gateways': enabled_gateways(),
            'max_stay_nights': settings.MAX_STAY_NIGHTS,
        })
