from datetime import timedelta

from django.db.models import Q

from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.models import AuditLog
from audit.services import record
from authentication.permissions import HasCapability
from hotel.clock import business_date
from rooms.models import Room
from hotel.schema import ANY, DATE_RANGE, body, extend_schema, query, serializers as s

from . import groups, lifecycle
from .front_desk import room_board, walk_in
from .models import Booking, BookingGroup, Guest, folio_totals_prefetch, valid_ids_prefetch
from .services import create_staff_reservation
from .staff_serializers import (
    BookingGroupSerializer,
    CheckInSerializer,
    CheckOutSerializer,
    GuestDetailSerializer,
    GroupActionResponseSerializer,
    GuestProfileSerializer,
    IdentificationSerializer,
    MoveRoomSerializer,
    PenaltyActionSerializer,
    ReservationCreateSerializer,
    ReservationSerializer,
    ReservationUpdateSerializer,
    WalkInSerializer,
)

Status = Booking.Status


def parse_date_param(params, name):
    value = params.get(name)
    if not value:
        return None
    try:
        return serializers.DateField().to_internal_value(value)
    except serializers.ValidationError:
        raise serializers.ValidationError({name: "Use YYYY-MM-DD."})


class ReservationViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """
    Staff reservations.

    Filters: ?status=CONFIRMED,CHECKED_IN  ?arrival=YYYY-MM-DD  ?departure=YYYY-MM-DD
             ?in_house=true  ?from=&to= (stays overlapping a range)  ?group=GR-...
             ?q= (confirmation number, guest name, email or phone)
    """
    serializer_class = ReservationSerializer
    read_actions = {'list', 'retrieve', 'summary'}

    def get_permissions(self):
        capability = 'bookings.view' if self.action in self.read_actions else 'bookings.manage'
        return [HasCapability(capability)()]

    def get_queryset(self):
        queryset = (
            Booking.objects
            .select_related('guest', 'room__room_type', 'group', 'created_by', 'rate_plan')
            # Folio totals and ID status for every row in a fixed number of queries
            .prefetch_related('payment_transactions', folio_totals_prefetch(), valid_ids_prefetch('guest__identifications'))
            .order_by('check_in_date', 'id')
        )
        if self.action != 'list':
            return queryset

        params = self.request.query_params
        if params.get('status'):
            queryset = queryset.filter(status__in=params['status'].upper().split(','))
        if (arrival := parse_date_param(params, 'arrival')):
            queryset = queryset.filter(check_in_date=arrival)
        if (departure := parse_date_param(params, 'departure')):
            queryset = queryset.filter(check_out_date=departure)
        if params.get('in_house') == 'true':
            queryset = queryset.filter(status=Status.CHECKED_IN)
        date_from, date_to = parse_date_param(params, 'from'), parse_date_param(params, 'to')
        if date_from and date_to:
            queryset = queryset.overlapping(date_from, date_to)
        if params.get('group'):
            queryset = queryset.filter(group__reference=params['group'].upper())
        if (q := params.get('q', '').strip()):
            queryset = queryset.filter(
                Q(confirmation_number__iexact=q) | Q(guest__first_name__icontains=q)
                | Q(guest__last_name__icontains=q) | Q(guest__email__iexact=q)
                | Q(guest__phone_number__icontains=q)
            )
        return queryset

    def respond(self, booking, status_code=status.HTTP_200_OK):
        return Response(ReservationSerializer(self.get_queryset().get(pk=booking.pk)).data, status=status_code)

    def create(self, request):
        serializer = ReservationCreateSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        bookings = create_staff_reservation(
            guest=data.get('existing_guest') or data['guest'],
            rooms=data['rooms'],
            check_in_date=data['check_in_date'],
            check_out_date=data['check_out_date'],
            special_requests=data['special_requests'],
            source=data['source'],
            notes=data['notes'],
            rate_plan=data.get('rate_plan'),
            corporate_account=data.get('corporate_account'),
            rate_override=data.get('rate_override'),
            override_reason=data['override_reason'],
            request=request,
        )
        queryset = self.get_queryset().filter(pk__in=[b.pk for b in bookings])
        return Response(ReservationSerializer(queryset, many=True).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        serializer = ReservationUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        booking = lifecycle.modify(self.get_object(), serializer.validated_data, request=request)
        return self.respond(booking)

    @action(detail=True, methods=['post'], url_path='check-in')
    def check_in(self, request, pk=None):
        serializer = CheckInSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        booking = lifecycle.check_in(
            self.get_object(), identification=serializer.validated_data.get('identification'), request=request,
        )
        return self.respond(booking)

    @action(detail=True, methods=['post'], url_path='post-room-charges')
    def post_room_charges(self, request, pk=None):
        """Bring the folio up to date before check-out so the guest can see and pay the bill."""
        lifecycle.bring_folio_up_to_date(self.get_object(), request=request)
        return self.respond(self.get_object())

    @action(detail=True, methods=['post'], url_path='move-room')
    def move_room(self, request, pk=None):
        serializer = MoveRoomSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        booking = lifecycle.move_room(
            self.get_object(), data['room'], reason=data['reason'], reprice_stay=data['reprice'], request=request,
        )
        return self.respond(booking)

    @action(detail=True, methods=['post'], url_path='check-out')
    def check_out(self, request, pk=None):
        serializer = CheckOutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        booking = lifecycle.check_out(
            self.get_object(), transfer_to_account=serializer.validated_data.get('transfer_to_account'),
            request=request,
        )
        return self.respond(booking)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        serializer = PenaltyActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self.respond(lifecycle.cancel(self.get_object(), request=request, **serializer.validated_data))

    @action(detail=True, methods=['post'], url_path='no-show')
    def no_show(self, request, pk=None):
        serializer = PenaltyActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self.respond(lifecycle.mark_no_show(self.get_object(), request=request, **serializer.validated_data))

    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Front-desk dashboard figures for ?date= (default today)."""
        day = parse_date_param(request.query_params, 'date') or business_date()
        bookings = Booking.objects.all()

        sellable_rooms = Room.objects.exclude(status__in=Room.UNSELLABLE_STATUSES).count()
        occupied_tonight = bookings.blocking().overlapping(day, day + timedelta(days=1)).count()

        return Response({
            'date': day,
            'arrivals_expected': bookings.filter(check_in_date=day, status=Status.CONFIRMED).count(),
            'arrivals_checked_in': bookings.filter(check_in_date=day, status=Status.CHECKED_IN).count(),
            'departures_expected': bookings.filter(check_out_date=day, status=Status.CHECKED_IN).count(),
            'departures_checked_out': bookings.filter(check_out_date=day, status=Status.CHECKED_OUT).count(),
            'in_house': bookings.filter(status=Status.CHECKED_IN).count(),
            'pending_holds': bookings.blocking().filter(status=Status.PENDING).count(),
            'sellable_rooms': sellable_rooms,
            'occupied_tonight': occupied_tonight,
            'occupancy_percent': round(100 * occupied_tonight / sellable_rooms, 1) if sellable_rooms else 0,
        })


class GuestViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                   mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """
    Guest profiles. Listing requires ?q= (name, email, phone or company) so
    the guest database can't be paged through wholesale.
    """
    http_method_names = ['get', 'post', 'patch', 'head', 'options']

    def get_permissions(self):
        if self.action == 'reveal_identification':
            capability = 'guests.view_identity'
        elif self.action in ('list', 'retrieve') or (self.action == 'identifications' and self.request.method == 'GET'):
            capability = 'bookings.view'
        else:
            capability = 'bookings.manage'
        return [HasCapability(capability)()]

    def get_serializer_class(self):
        return GuestDetailSerializer if self.action == 'retrieve' else GuestProfileSerializer

    def get_queryset(self):
        queryset = Guest.objects.order_by('last_name', 'first_name', 'id').prefetch_related(valid_ids_prefetch())
        if self.action != 'list':
            return queryset
        q = self.request.query_params.get('q', '').strip()
        if not q:
            return queryset.none()
        return queryset.filter(
            Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(email__iexact=q)
            | Q(phone_number__icontains=q) | Q(company_name__icontains=q)
        )

    def perform_update(self, serializer):
        before = {field: getattr(serializer.instance, field) for field in serializer.validated_data}
        guest = serializer.save()
        changed = sorted(f for f in before if before[f] != getattr(guest, f))
        if changed:
            # Field names only: the audit log shouldn't become a second copy of guest PII
            record(AuditLog.Action.GUEST_UPDATED, request=self.request, target=guest, changes={'fields': changed})

    @action(detail=True, methods=['get', 'post'])
    def identifications(self, request, pk=None):
        guest = self.get_object()
        if request.method == 'POST':
            serializer = IdentificationSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            identification = lifecycle.record_identification(guest, serializer.validated_data, request=request)
            return Response(IdentificationSerializer(identification).data, status=status.HTTP_201_CREATED)
        return Response(IdentificationSerializer(guest.identifications.select_related('captured_by'), many=True).data)

    @action(detail=True, methods=['post'], url_path=r'identifications/(?P<identification_id>[0-9]+)/reveal')
    def reveal_identification(self, request, pk=None, identification_id=None):
        """Full document number, for managers only. Every reveal is audited."""
        guest = self.get_object()
        identification = guest.identifications.filter(pk=identification_id).first()
        if identification is None:
            return Response({"error": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        record(AuditLog.Action.GUEST_ID_REVEALED, request=request, target=guest,
               changes={'identification_id': identification.pk})
        return Response({'id': identification.pk, 'document_number': identification.document_number})


class WalkInView(APIView):
    """Book and check in an arriving guest in one step."""
    permission_classes = [HasCapability('bookings.manage')]

    @extend_schema(summary='Book and check in an arriving guest', request=WalkInSerializer, responses=ReservationSerializer)
    def post(self, request):
        serializer = WalkInSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        booking = walk_in(
            guest=data.get('existing_guest') or data['guest'],
            room=data['room'],
            check_out_date=data['check_out_date'],
            identification=data.get('identification'),
            request=request,
        )
        booking = Booking.objects.select_related('guest', 'room__room_type', 'group', 'created_by').get(pk=booking.pk)
        return Response(ReservationSerializer(booking).data, status=status.HTTP_201_CREATED)


class RoomBoardView(APIView):
    """Every room and what's happening in it on ?date= (default today)."""
    permission_classes = [HasCapability('bookings.view')]

    @extend_schema(summary='Every room and what is happening in it', parameters=[query('date', 'Day to show (YYYY-MM-DD); default today')], responses=ANY)
    def get(self, request):
        return Response(room_board(parse_date_param(request.query_params, 'date')))


class BookingGroupViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """
    A booking group (several rooms booked together) by its reference, e.g.
    GR-ABC123, with whole-group check-in, check-out and cancellation. Each
    room is handled on its own, so the response lists what happened to every room.
    """
    serializer_class = BookingGroupSerializer
    lookup_field = 'reference'
    lookup_value_regex = '[A-Za-z0-9-]+'

    def get_permissions(self):
        return [HasCapability('bookings.view' if self.action == 'retrieve' else 'bookings.manage')()]

    def get_queryset(self):
        return BookingGroup.objects.select_related('booker', 'created_by').prefetch_related(
            valid_ids_prefetch('booker__identifications'))

    def get_object(self):
        self.kwargs['reference'] = self.kwargs['reference'].upper()
        return super().get_object()

    def respond(self, group, results):
        group = self.get_queryset().get(pk=group.pk)  # fresh: statuses and balances have changed
        return Response({'group': BookingGroupSerializer(group).data, 'results': results})

    @extend_schema(summary='Check in every room of the group arriving today', request=CheckInSerializer,
                   responses=GroupActionResponseSerializer)
    @action(detail=True, methods=['post'], url_path='check-in')
    def check_in(self, request, reference=None):
        serializer = CheckInSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        group = self.get_object()
        results = groups.check_in_group(group, identification=serializer.validated_data.get('identification'),
                                        request=request)
        return self.respond(group, results)

    @extend_schema(summary='Check out every in-house room of the group', request=None,
                   responses=GroupActionResponseSerializer)
    @action(detail=True, methods=['post'], url_path='check-out')
    def check_out(self, request, reference=None):
        group = self.get_object()
        return self.respond(group, groups.check_out_group(group, request=request))

    @extend_schema(summary='Cancel every room of the group still to come', request=PenaltyActionSerializer,
                   responses=GroupActionResponseSerializer)
    @action(detail=True, methods=['post'])
    def cancel(self, request, reference=None):
        serializer = PenaltyActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        group = self.get_object()
        return self.respond(group, groups.cancel_group(group, request=request, **serializer.validated_data))
