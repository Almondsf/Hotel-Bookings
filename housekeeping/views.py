from django.db.models import Prefetch
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from authentication.models import User
from authentication.permissions import HasCapability
from booking.models import Booking
from booking.staff_views import parse_date_param
from hotel.clock import business_date
from rooms.models import Room
from hotel.schema import ANY, DATE_RANGE, body, extend_schema, query, serializers as s

from . import services
from .models import HousekeepingTask


class TaskSerializer(serializers.ModelSerializer):
    room_number = serializers.CharField(source='room.room_number', read_only=True)
    floor_number = serializers.IntegerField(source='room.floor_number', read_only=True)
    room_status = serializers.CharField(source='room.housekeeping_status', read_only=True)
    assigned_to_name = serializers.SerializerMethodField()

    class Meta:
        model = HousekeepingTask
        fields = ['id', 'room', 'room_number', 'floor_number', 'room_status', 'date', 'task_type', 'status',
                  'is_rush', 'assigned_to', 'assigned_to_name', 'notes', 'started_at', 'completed_at']
        read_only_fields = ['id', 'room', 'date', 'task_type', 'status', 'is_rush', 'started_at', 'completed_at']

    def get_assigned_to_name(self, obj) -> str | None:
        return obj.assigned_to.full_name if obj.assigned_to_id else None

    def validate_assigned_to(self, user):
        if user is not None and (not user.is_active or not user.has_capability('housekeeping.work')):
            raise serializers.ValidationError("Tasks can only be assigned to active housekeeping staff.")
        return user


class NotesSerializer(serializers.Serializer):
    notes = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255)


class TaskViewSet(mixins.ListModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """
    Cleaning tasks. ?date= (default today) ?status= ?mine=true
    PATCH assigned_to to assign (supervisors); start / complete / skip for attendants.
    """
    serializer_class = TaskSerializer
    pagination_class = None
    http_method_names = ['get', 'post', 'patch', 'head', 'options']

    def get_permissions(self):
        capability = {
            'list': 'housekeeping.view', 'generate': 'housekeeping.manage', 'partial_update': 'housekeeping.manage',
        }.get(self.action, 'housekeeping.work')
        return [HasCapability(capability)()]

    def get_queryset(self):
        params = self.request.query_params
        queryset = HousekeepingTask.objects.select_related('room', 'assigned_to')
        if self.action != 'list':
            return queryset
        queryset = queryset.filter(date=parse_date_param(params, 'date') or business_date())
        if params.get('status'):
            queryset = queryset.filter(status=params['status'].upper())
        if params.get('mine') == 'true':
            queryset = queryset.filter(assigned_to=self.request.user)
        return queryset

    @action(detail=False, methods=['post'])
    def generate(self, request):
        day = parse_date_param(request.data, 'date') or business_date()
        created = services.generate_daily_tasks(day)
        return Response({'date': day, 'created': created})

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        return Response(TaskSerializer(services.start_task(self.get_object(), request=request)).data)

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        data = NotesSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        task = services.complete_task(self.get_object(), request=request, notes=data.validated_data['notes'])
        return Response(TaskSerializer(task).data)

    @action(detail=True, methods=['post'])
    def skip(self, request, pk=None):
        data = ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        task = services.skip_task(self.get_object(), request=request, reason=data.validated_data['reason'])
        return Response(TaskSerializer(task).data)


class RoomStatusSerializer(serializers.Serializer):
    housekeeping_status = serializers.ChoiceField(choices=Room.Housekeeping.choices)
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')


class RoomStatusView(APIView):
    """GET: every room's cleaning and occupancy status. POST {room, housekeeping_status}: supervisors set it."""

    def get_permissions(self):
        return [HasCapability('housekeeping.view' if self.request.method == 'GET' else 'housekeeping.manage')()]

    @extend_schema(summary="Rooms' cleaning and occupancy status", responses=ANY)
    def get(self, request):
        in_house = set(Booking.objects.filter(status=Booking.Status.CHECKED_IN).values_list('room_id', flat=True))
        today_tasks = HousekeepingTask.objects.filter(date=business_date())
        rooms = (Room.objects.select_related('room_type')
                 .prefetch_related(Prefetch('housekeeping_tasks', queryset=today_tasks, to_attr='today_tasks'))
                 .order_by('floor_number', 'room_number'))
        return Response([{
            'room_id': room.pk, 'room_number': room.room_number, 'floor_number': room.floor_number,
            'room_type': room.room_type.name, 'status': room.status, 'housekeeping_status': room.housekeeping_status,
            'occupied': room.pk in in_house,
            'tasks': [{'id': t.pk, 'task_type': t.task_type, 'status': t.status} for t in room.today_tasks],
        } for room in rooms])

    @extend_schema(summary="Set a room's cleaning status", request=RoomStatusSerializer, responses=ANY)
    def post(self, request, room_id):
        room = Room.objects.filter(pk=room_id).first()
        if room is None:
            return Response({'error': 'Room not found.'}, status=status.HTTP_404_NOT_FOUND)
        data = RoomStatusSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.set_room_status(room, data.validated_data['housekeeping_status'], request=request,
                                 reason=data.validated_data['reason'])
        return Response({'room_id': room.pk, 'housekeeping_status': room.housekeeping_status})


class HousekeepingStaffView(APIView):
    """Attendants tasks can be assigned to."""
    permission_classes = [HasCapability('housekeeping.manage')]

    @extend_schema(summary='Staff who can be assigned cleaning tasks', responses=ANY)
    def get(self, request):
        staff = User.objects.filter(is_active=True, role__in=[User.Role.HOUSEKEEPING, User.Role.MANAGER])
        return Response([{'id': u.pk, 'name': u.full_name, 'role': u.role} for u in staff.order_by('first_name')])
