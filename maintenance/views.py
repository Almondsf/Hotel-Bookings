from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from authentication.permissions import HasCapability
from rooms.models import Room

from . import services
from .models import MaintenanceTicket


class TicketSerializer(serializers.ModelSerializer):
    number = serializers.CharField(read_only=True)
    room_number = serializers.CharField(source='room.room_number', default=None, read_only=True)
    reported_by = serializers.CharField(source='reported_by.full_name', default=None, read_only=True)
    assigned_to_name = serializers.CharField(source='assigned_to.full_name', default=None, read_only=True)
    out_of_order_until = serializers.DateField(source='out_of_order.end_date', default=None, read_only=True)

    class Meta:
        model = MaintenanceTicket
        fields = ['id', 'number', 'room', 'room_number', 'location', 'title', 'description', 'category', 'priority',
                  'status', 'reported_by', 'assigned_to', 'assigned_to_name', 'out_of_order_until',
                  'resolution_notes', 'created_at', 'resolved_at']
        read_only_fields = ['id', 'status', 'resolution_notes', 'created_at', 'resolved_at']


class ReportSerializer(serializers.Serializer):
    room = serializers.PrimaryKeyRelatedField(queryset=Room.objects.all(), required=False, allow_null=True)
    location = serializers.CharField(max_length=150, required=False, allow_blank=True, default='')
    title = serializers.CharField(max_length=150)
    description = serializers.CharField(required=False, allow_blank=True, default='')
    category = serializers.ChoiceField(choices=MaintenanceTicket.Category.choices, default='OTHER')
    priority = serializers.ChoiceField(choices=MaintenanceTicket.Priority.choices, default='MEDIUM')
    out_of_order_until = serializers.DateField(required=False, allow_null=True,
                                               help_text="Take the room off sale until this date")


class TicketViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin,
                    viewsets.GenericViewSet):
    """Tickets. ?status=OPEN ?priority= ?room=<id> ?active=true"""
    serializer_class = TicketSerializer
    http_method_names = ['get', 'post', 'patch', 'head', 'options']

    def get_permissions(self):
        capability = {'list': 'maintenance.view', 'retrieve': 'maintenance.view',
                      'create': 'maintenance.report'}.get(self.action, 'maintenance.manage')
        return [HasCapability(capability)()]

    def get_queryset(self):
        queryset = MaintenanceTicket.objects.select_related('room', 'reported_by', 'assigned_to', 'out_of_order')
        params = self.request.query_params
        if params.get('status'):
            queryset = queryset.filter(status=params['status'].upper())
        if params.get('active') == 'true':
            queryset = queryset.filter(status__in=services.ACTIVE)
        if params.get('priority'):
            queryset = queryset.filter(priority=params['priority'].upper())
        if params.get('room', '').isdigit():
            queryset = queryset.filter(room_id=params['room'])
        return queryset

    def create(self, request):
        data = ReportSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        ticket, conflicts = services.report(request=request, **data.validated_data)
        return Response({
            **TicketSerializer(ticket).data,
            # Reservations in the out-of-order window that the front desk must move
            'bookings_to_move': [{'id': b.pk, 'confirmation_number': b.confirmation_number,
                                  'guest_name': str(b.guest), 'check_in_date': b.check_in_date}
                                 for b in conflicts],
        }, status=status.HTTP_201_CREATED)

    def perform_update(self, serializer):
        # Only assignment / details change through PATCH; status changes use the actions
        serializer.save()

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        ticket = services.update_status(self.get_object(), MaintenanceTicket.Status.IN_PROGRESS, request=request)
        return Response(TicketSerializer(ticket).data)

    @action(detail=True, methods=['post'])
    def hold(self, request, pk=None):
        ticket = services.update_status(self.get_object(), MaintenanceTicket.Status.ON_HOLD, request=request)
        return Response(TicketSerializer(ticket).data)

    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        ticket = services.resolve(self.get_object(), request=request,
                                  notes=str(request.data.get('resolution_notes', '')).strip())
        return Response(TicketSerializer(ticket).data)
