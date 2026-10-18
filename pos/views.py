from django.shortcuts import get_object_or_404
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import SAFE_METHODS
from rest_framework.response import Response
from rest_framework.views import APIView

from authentication.permissions import HasCapability
from billing.models import PaymentMethod
from nightaudit.views import date_range
from hotel.schema import ANY, DATE_RANGE, body, extend_schema, query, serializers as s

from . import services
from .models import Order, OrderItem, Outlet, Product


class OutletSerializer(serializers.ModelSerializer):
    class Meta:
        model = Outlet
        fields = ['id', 'code', 'name', 'kind', 'allowed_roles', 'is_active']


class ProductSerializer(serializers.ModelSerializer):
    is_low_on_stock = serializers.BooleanField(read_only=True)

    class Meta:
        model = Product
        fields = ['id', 'outlet', 'name', 'section', 'price', 'charge_category', 'is_available', 'track_stock',
                  'stock_quantity', 'low_stock_threshold', 'is_low_on_stock']

    def validate_charge_category(self, value):
        if value in ('ROOM', 'PENALTY', 'ALLOWANCE'):
            raise serializers.ValidationError("Outlets can't sell this category.")
        return value


class OrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = ['id', 'product', 'name', 'unit_price', 'quantity', 'notes']
        read_only_fields = ['id', 'name', 'unit_price']


class OrderSerializer(serializers.ModelSerializer):
    number = serializers.CharField(read_only=True)
    items = OrderItemSerializer(many=True, read_only=True)
    totals = serializers.SerializerMethodField()
    outlet_name = serializers.CharField(source='outlet.name', read_only=True)
    room_number = serializers.CharField(source='booking.room.room_number', default=None, read_only=True)

    class Meta:
        model = Order
        fields = ['id', 'number', 'outlet', 'outlet_name', 'table_label', 'covers', 'status', 'notes', 'items',
                  'totals', 'folio', 'room_number', 'opened_at', 'settled_at', 'void_reason']
        read_only_fields = ['id', 'status', 'folio', 'opened_at', 'settled_at', 'void_reason']

    def get_totals(self, obj) -> dict:
        from billing.taxes import rules_for
        return {k: str(v) for k, v in services.totals(obj, rules_for(self)).items()}


class AddItemSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    quantity = serializers.IntegerField(min_value=1, max_value=100, default=1)
    notes = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')


class ChargeToRoomSerializer(serializers.Serializer):
    room_number = serializers.CharField(max_length=10)
    guest_last_name = serializers.CharField(max_length=100)


class PayNowSerializer(serializers.Serializer):
    method = serializers.ChoiceField(choices=[PaymentMethod.CASH, PaymentMethod.CARD_TERMINAL, PaymentMethod.BANK_TRANSFER])
    tendered_amount = serializers.DecimalField(max_digits=14, decimal_places=2, required=False)
    reference = serializers.CharField(max_length=150, required=False, allow_blank=True, default='')


class OutletViewSet(viewsets.ModelViewSet):
    serializer_class = OutletSerializer
    queryset = Outlet.objects.none()  # typing hint for the API docs; get_queryset decides
    http_method_names = ['get', 'post', 'patch', 'head', 'options']
    pagination_class = None

    def get_permissions(self):
        return [HasCapability('pos.use' if self.request.method in SAFE_METHODS else 'pos.manage')()]

    def get_queryset(self):
        outlets = Outlet.objects.all()
        if self.request.method in SAFE_METHODS:
            # Only the outlets this person may sell at
            return [o for o in outlets.filter(is_active=True) if o.is_open_to(self.request.user)]
        return outlets


class ProductViewSet(viewsets.ModelViewSet):
    """Menu items. ?outlet=<id>"""
    serializer_class = ProductSerializer
    http_method_names = ['get', 'post', 'patch', 'head', 'options']
    pagination_class = None

    def get_permissions(self):
        return [HasCapability('pos.use' if self.request.method in SAFE_METHODS else 'pos.manage')()]

    def get_queryset(self):
        products = Product.objects.select_related('outlet')
        outlet = self.request.query_params.get('outlet', '')
        return products.filter(outlet_id=outlet) if outlet.isdigit() else products


class OrderViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                   viewsets.GenericViewSet):
    """Orders. ?outlet=<id> ?status=OPEN"""
    serializer_class = OrderSerializer
    queryset = Order.objects.none()  # typing hint for the API docs; get_queryset decides

    def get_permissions(self):
        return [HasCapability('pos.void' if self.action == 'void' else 'pos.use')()]

    def get_queryset(self):
        orders = Order.objects.select_related('outlet', 'booking__room').prefetch_related('items')
        params = self.request.query_params
        if params.get('outlet', '').isdigit():
            orders = orders.filter(outlet_id=params['outlet'])
        if params.get('status'):
            orders = orders.filter(status=params['status'].upper())
        allowed = [o.pk for o in Outlet.objects.all() if o.is_open_to(self.request.user)]
        return orders.filter(outlet_id__in=allowed)

    def respond(self, order, status_code=status.HTTP_200_OK, **extra):
        order = self.get_queryset().get(pk=order.pk)
        return Response({**OrderSerializer(order).data, **extra}, status=status_code)

    def create(self, request):
        serializer = OrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        order = services.open_order(data['outlet'], user=request.user, table_label=data.get('table_label', ''),
                                    covers=data.get('covers', 1), notes=data.get('notes', ''))
        return self.respond(order, status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def items(self, request, pk=None):
        serializer = AddItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = self.get_object()
        services.add_item(order, user=request.user, **serializer.validated_data)
        return self.respond(order, status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path=r'items/(?P<item_id>[0-9]+)/remove')
    def remove_item(self, request, pk=None, item_id=None):
        order = self.get_object()
        services.remove_item(order, get_object_or_404(order.items, pk=item_id), user=request.user)
        return self.respond(order)

    @action(detail=True, methods=['post'], url_path='charge-to-room')
    def charge_to_room(self, request, pk=None):
        serializer = ChargeToRoomSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = services.charge_to_room(self.get_object(), request=request, **serializer.validated_data)
        return self.respond(order)

    @action(detail=True, methods=['post'])
    def pay(self, request, pk=None):
        serializer = PayNowSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order, change = services.pay_now(self.get_object(), request=request, **serializer.validated_data)
        return self.respond(order, change_due=str(change))

    @action(detail=True, methods=['post'])
    def void(self, request, pk=None):
        order = services.void_order(self.get_object(), reason=str(request.data.get('reason', '')).strip(),
                                    request=request)
        return self.respond(order)


class InHouseLookupView(APIView):
    """?room=101 → the in-house guest's name, so the server can confirm it before charging the room."""
    permission_classes = [HasCapability('pos.use')]

    @extend_schema(summary='The in-house guest in a room (for charge-to-room)', parameters=[query('room', 'Room number', required=True)], responses=ANY)
    def get(self, request):
        booking = services.find_in_house(request.query_params.get('room', '').strip())
        if booking is None:
            return Response({'error': 'No guest is checked in to that room.'}, status=status.HTTP_404_NOT_FOUND)
        # Surname initial only: the server must ask the guest, not read the name off the screen
        return Response({'room_number': booking.room.room_number, 'guest_initials':
                         f"{booking.guest.first_name[:1]}. {booking.guest.last_name[:1]}."})


class SalesReportView(APIView):
    permission_classes = [HasCapability('reports.view')]

    @extend_schema(summary='Outlet sales and best sellers', parameters=DATE_RANGE[:2], responses=ANY)
    def get(self, request):
        start, end = date_range(request)
        return Response(services.sales_report(start, end))
