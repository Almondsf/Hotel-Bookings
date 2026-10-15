from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from authentication.permissions import HasCapability
from booking.models import Guest
from hotel.schema import ANY, DATE_RANGE, body, extend_schema, query, serializers as s

from . import services


class GuestExportView(APIView):
    """GET: a guest's data (NDPA right of access), to hand over or send to them."""
    permission_classes = [HasCapability('privacy.manage')]

    @extend_schema(summary='Download everything held about a guest (NDPA access)', responses={(200, 'application/json'): ANY})
    def get(self, request, guest_id):
        data = services.export_guest(get_object_or_404(Guest, pk=guest_id), request=request)
        response = Response(data)
        response['Content-Disposition'] = f'attachment; filename="guest-{guest_id}-data.json"'
        return response


class GuestAnonymiseView(APIView):
    """POST {reason}: erase a guest's personal data (NDPA right to erasure)."""
    permission_classes = [HasCapability('privacy.manage')]

    @extend_schema(summary="Erase a guest's personal data (NDPA erasure)", request=body('Anonymise', reason=s.CharField(required=False)), responses=ANY)
    def post(self, request, guest_id):
        guest = services.anonymise_guest(get_object_or_404(Guest, pk=guest_id), request=request,
                                         reason=str(request.data.get('reason') or 'Guest request')[:200])
        return Response({'id': guest.pk, 'anonymised': True})
