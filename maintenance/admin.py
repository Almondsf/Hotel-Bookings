from django.contrib import admin

from .models import MaintenanceTicket


@admin.register(MaintenanceTicket)
class MaintenanceTicketAdmin(admin.ModelAdmin):
    list_display = ['id', 'title', 'room', 'location', 'priority', 'status', 'assigned_to', 'created_at']
    list_filter = ['status', 'priority', 'category']
    search_fields = ['title', 'location', 'room__room_number']
