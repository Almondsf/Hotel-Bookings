from django.contrib import admin

from .models import Booking, BookingGroup, Guest


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ['confirmation_number', 'guest', 'room', 'check_in_date', 'check_out_date', 'status', 'total_price']
    list_filter = ['status', 'source', 'check_in_date']
    search_fields = ['confirmation_number', 'guest__first_name', 'guest__last_name', 'guest__email']
    list_select_related = ['guest', 'room']
    autocomplete_fields = ['guest', 'room']
    date_hierarchy = 'check_in_date'
    readonly_fields = [
        'confirmation_number', 'confirmed_at', 'checked_in_at', 'checked_out_at', 'cancelled_at',
        'created_by', 'created_at', 'updated_at',
    ]


@admin.register(BookingGroup)
class BookingGroupAdmin(admin.ModelAdmin):
    list_display = ['reference', 'booker', 'created_by', 'created_at']
    search_fields = ['reference', 'booker__last_name', 'booker__email']
    readonly_fields = ['reference', 'created_by', 'created_at']


@admin.register(Guest)
class GuestAdmin(admin.ModelAdmin):
    list_display = ['first_name', 'last_name', 'email', 'phone_number', 'created_at']
    search_fields = ['first_name', 'last_name', 'email', 'phone_number']

