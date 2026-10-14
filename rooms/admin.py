from django.contrib import admin

from .models import Amenity, Room, RoomAvailabilityOverride, RoomImage, RoomPricing, RoomType


class RoomImageInline(admin.TabularInline):
    model = RoomImage
    extra = 0


class RoomPricingInline(admin.TabularInline):
    model = RoomPricing
    extra = 0


@admin.register(RoomType)
class RoomTypeAdmin(admin.ModelAdmin):
    list_display = ['name', 'base_price', 'max_adults', 'max_children', 'bed_type']
    search_fields = ['name']
    filter_horizontal = ['amenities']
    inlines = [RoomPricingInline, RoomImageInline]


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ['room_number', 'room_type', 'floor_number', 'status']
    list_filter = ['status', 'room_type', 'floor_number']
    search_fields = ['room_number']
    list_select_related = ['room_type']


@admin.register(RoomAvailabilityOverride)
class RoomAvailabilityOverrideAdmin(admin.ModelAdmin):
    list_display = ['room', 'start_date', 'end_date', 'reason']
    list_filter = ['reason']
    autocomplete_fields = ['room']


admin.site.register(Amenity)
admin.site.register(RoomPricing)
admin.site.register(RoomImage)
