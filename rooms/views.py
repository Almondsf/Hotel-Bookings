from rest_framework import generics, serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.models import AuditLog
from audit.services import record
from authentication.permissions import HasCapability

from .models import Room, RoomType
from .serializers import (
    RoomSearchQuerySerializer,
    RoomSerializer,
    RoomTypeAvailabilitySerializer,
    RoomTypeDetailSerializer,
    RoomTypeSerializer,
)
from .services import generate_booking_plans, get_available_rooms_for_type


class RoomTypeCreateView(generics.CreateAPIView):
    serializer_class = RoomTypeSerializer
    permission_classes = [HasCapability('rooms.manage')]

    def perform_create(self, serializer):
        record(AuditLog.Action.ROOM_TYPE_CREATED, request=self.request, target=serializer.save())


class RoomCreateView(generics.CreateAPIView):
    serializer_class = RoomSerializer
    permission_classes = [HasCapability('rooms.manage')]

    def perform_create(self, serializer):
        record(AuditLog.Action.ROOM_CREATED, request=self.request, target=serializer.save())


class RoomTypeUpdateView(generics.UpdateAPIView):
    """PATCH a room type's description, base price, capacity or beds. Past bookings keep their agreed rates."""
    serializer_class = RoomTypeSerializer
    permission_classes = [HasCapability('rooms.manage')]
    queryset = RoomType.objects.all()
    http_method_names = ['patch', 'options']

    def perform_update(self, serializer):
        record(AuditLog.Action.ROOM_TYPE_UPDATED, request=self.request, target=serializer.save(),
               changes={k: str(v) for k, v in serializer.validated_data.items()})


class RoomUpdateSerializer(RoomSerializer):
    # Occupancy follows check-in/out and MAINTENANCE follows maintenance tickets; staff here
    # can only take a room out of service (e.g. renovation) or return it to sale.
    status = serializers.ChoiceField(choices=[Room.Status.AVAILABLE, Room.Status.OUT_OF_SERVICE], required=False)

    class Meta(RoomSerializer.Meta):
        read_only_fields = RoomSerializer.Meta.read_only_fields + ['room_number', 'housekeeping_status']

    def validate_status(self, value):
        room = self.instance
        if room.status in (Room.Status.OCCUPIED, Room.Status.MAINTENANCE) and value != room.status:
            raise serializers.ValidationError(
                f"Room {room.room_number} is {room.get_status_display().lower()}; that status is managed by "
                "check-in/out and maintenance tickets.")
        return value


class RoomUpdateView(generics.UpdateAPIView):
    serializer_class = RoomUpdateSerializer
    permission_classes = [HasCapability('rooms.manage')]
    queryset = Room.objects.select_related('room_type')
    http_method_names = ['patch', 'options']

    def perform_update(self, serializer):
        record(AuditLog.Action.ROOM_UPDATED, request=self.request, target=serializer.save(),
               changes={k: str(v) for k, v in serializer.validated_data.items()})


class RoomTypeListView(generics.ListAPIView):
    """All room types, for the booking site and staff forms."""
    serializer_class = RoomTypeDetailSerializer
    permission_classes = [AllowAny]
    pagination_class = None
    queryset = RoomType.objects.prefetch_related('amenities', 'images', 'rooms')


class RoomListView(generics.ListAPIView):
    """Physical rooms, for staff (room moves, assigning a specific room)."""
    serializer_class = RoomSerializer
    permission_classes = [HasCapability('bookings.view')]
    pagination_class = None
    queryset = Room.objects.select_related('room_type').prefetch_related('room_type__amenities')


class RoomTypeSearchView(APIView):
    """
    GET ?check_in=YYYY-MM-DD&check_out=YYYY-MM-DD&adults=N&children=N

    Returns room types that fit the whole party in one room. When none do,
    also returns multi-room booking plans.
    """
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        query = RoomSearchQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        check_in = query.validated_data['check_in']
        check_out = query.validated_data['check_out']
        adults = query.validated_data['adults']
        children = query.validated_data['children']

        candidates = RoomType.objects.filter(
            max_adults__gte=adults,
            max_children__gte=children
        ).prefetch_related('images')
        room_types = [
            room_type for room_type in candidates
            if get_available_rooms_for_type(room_type, check_in, check_out).exists()
        ]

        serializer = RoomTypeAvailabilitySerializer(
            room_types, many=True,
            context={'request': request, 'check_in_date': check_in, 'check_out_date': check_out,
                     'promo_code': request.query_params.get('promo_code', '')[:40]},
        )

        booking_plans = None
        if not room_types:
            plans = generate_booking_plans(check_in, check_out, adults, children)
            booking_plans = {
                'budget_friendly': self._format_plans(plans['budget_friendly']),
                'convenience': self._format_plans(plans['convenience'])
            }

        return Response({
            'room_types': serializer.data,
            'booking_plans': booking_plans,
        })

    def _format_plans(self, plans):
        """Format plans for JSON response"""
        formatted = []
        for plan in plans:
            rooms_list = []
            for room_type, count in plan['rooms'].items():
                rooms_list.append({
                    'room_type_id': room_type.id,
                    'room_type_name': room_type.name,
                    'room_type_slug': room_type.slug,
                    'count': count,
                    'capacity': f"{room_type.max_adults} adults, {room_type.max_children} children"
                })

            formatted.append({
                'rooms': rooms_list,
                'total_rooms': plan['total_rooms'],
                'total_price': str(plan['total_price']),
                'price_per_night': str(plan['price_per_night'])
            })

        return formatted


class RoomTypeDetailView(generics.RetrieveAPIView):
    queryset = RoomType.objects.prefetch_related('amenities', 'images', 'rooms')
    serializer_class = RoomTypeDetailSerializer
    permission_classes = [AllowAny]
    lookup_field = 'slug'
