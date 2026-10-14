from rest_framework import generics

from authentication.permissions import HasCapability

from .models import AuditLog
from .serializers import AuditLogSerializer


class AuditLogListView(generics.ListAPIView):
    """GET /api/audit/?action=&actor=&target_type=&target_id="""
    serializer_class = AuditLogSerializer
    permission_classes = [HasCapability('audit.view')]

    def get_queryset(self):
        queryset = AuditLog.objects.all()
        params = self.request.query_params
        for param in ['action', 'target_type', 'target_id']:
            if params.get(param):
                queryset = queryset.filter(**{param: params[param]})
        actor = params.get('actor')
        if actor:
            queryset = queryset.filter(actor_id=actor) if actor.isdigit() else queryset.none()
        return queryset
