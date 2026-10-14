from django.contrib import admin

from .models import ChannelBooking, ChannelConnection, RatePlanMapping, RoomTypeMapping


class RoomTypeMappingInline(admin.TabularInline):
    model = RoomTypeMapping
    extra = 0


class RatePlanMappingInline(admin.TabularInline):
    model = RatePlanMapping
    extra = 0


@admin.register(ChannelConnection)
class ChannelConnectionAdmin(admin.ModelAdmin):
    list_display = ['provider', 'is_active', 'property_id', 'last_full_sync_at', 'last_error']
    inlines = [RoomTypeMappingInline, RatePlanMappingInline]
    readonly_fields = ['last_full_sync_at', 'last_error']


@admin.register(ChannelBooking)
class ChannelBookingAdmin(admin.ModelAdmin):
    list_display = ['ota_name', 'ota_reference', 'external_id', 'status', 'updated_at']
    list_filter = ['status', 'ota_name']
    readonly_fields = ['payload']
