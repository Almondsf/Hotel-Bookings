from django.contrib import admin

from .models import RatePlan, RatePlanPrice, RateRestriction


class RatePlanPriceInline(admin.TabularInline):
    model = RatePlanPrice
    extra = 0


@admin.register(RatePlan)
class RatePlanAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'meal_plan', 'pricing', 'adjustment_percent', 'is_public', 'is_active']
    list_filter = ['is_active', 'is_public', 'meal_plan']
    filter_horizontal = ['room_types']
    inlines = [RatePlanPriceInline]


@admin.register(RateRestriction)
class RateRestrictionAdmin(admin.ModelAdmin):
    list_display = ['start_date', 'end_date', 'rate_plan', 'room_type', 'stop_sell', 'closed_to_arrival',
                    'closed_to_departure', 'min_stay']
