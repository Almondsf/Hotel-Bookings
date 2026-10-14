from rest_framework import serializers, viewsets
from rest_framework.permissions import SAFE_METHODS

from audit.models import AuditLog
from audit.services import record
from authentication.permissions import HasCapability

from .models import RatePlan, RatePlanPrice, RateRestriction


class RatePlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = RatePlan
        fields = [
            'id', 'code', 'name', 'description', 'meal_plan', 'pricing', 'adjustment_percent', 'room_types',
            'is_active', 'is_public', 'promo_code', 'corporate_account', 'min_stay', 'max_stay',
            'min_advance_days', 'max_advance_days', 'sell_from', 'sell_until', 'is_refundable',
            'free_cancellation_hours', 'updated_at',
        ]
        read_only_fields = ['id', 'updated_at']

    def validate(self, data):
        code = data.get('code', getattr(self.instance, 'code', None))
        if code == RatePlan.BAR_CODE and (data.get('pricing', 'DERIVED') != 'DERIVED' or data.get('adjustment_percent', 0)):
            raise serializers.ValidationError("BAR is the reference rate; set room type prices instead.")
        if data.get('promo_code'):
            data['promo_code'] = data['promo_code'].strip().upper()
        return data


class RatePlanPriceSerializer(serializers.ModelSerializer):
    class Meta:
        model = RatePlanPrice
        fields = ['id', 'rate_plan', 'room_type', 'start_date', 'end_date', 'price']

    def validate(self, data):
        if data['end_date'] < data['start_date']:
            raise serializers.ValidationError({'end_date': "End date can't be before start date."})
        return data


class RateRestrictionSerializer(serializers.ModelSerializer):
    class Meta:
        model = RateRestriction
        fields = ['id', 'rate_plan', 'room_type', 'start_date', 'end_date', 'stop_sell', 'closed_to_arrival',
                  'closed_to_departure', 'min_stay', 'note']

    def validate(self, data):
        if data.get('end_date') and data.get('start_date') and data['end_date'] < data['start_date']:
            raise serializers.ValidationError({'end_date': "End date can't be before start date."})
        return data


class AuditedRatesViewSet(viewsets.ModelViewSet):
    """Read: anyone who takes bookings. Write: revenue / general managers, audited."""

    def get_permissions(self):
        capability = 'bookings.view' if self.request.method in SAFE_METHODS else 'rates.manage'
        return [HasCapability(capability)()]

    def _audit(self, instance, verb):
        record(AuditLog.Action.RATES_CHANGED, request=self.request, target=instance,
               changes={'change': verb, **{k: str(v) for k, v in self.request.data.items()}})

    def perform_create(self, serializer):
        self._audit(serializer.save(), 'created')

    def perform_update(self, serializer):
        self._audit(serializer.save(), 'updated')

    def perform_destroy(self, instance):
        self._audit(instance, 'deleted')
        instance.delete()


class RatePlanViewSet(AuditedRatesViewSet):
    serializer_class = RatePlanSerializer
    queryset = RatePlan.objects.prefetch_related('room_types')
    http_method_names = ['get', 'post', 'patch', 'head', 'options']  # deactivate instead of deleting


class RatePlanPriceViewSet(AuditedRatesViewSet):
    serializer_class = RatePlanPriceSerializer
    queryset = RatePlanPrice.objects.select_related('rate_plan', 'room_type')


class RateRestrictionViewSet(AuditedRatesViewSet):
    serializer_class = RateRestrictionSerializer
    queryset = RateRestriction.objects.all()
