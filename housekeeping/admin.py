from django.contrib import admin

from .models import HousekeepingTask


@admin.register(HousekeepingTask)
class HousekeepingTaskAdmin(admin.ModelAdmin):
    list_display = ['date', 'room', 'task_type', 'status', 'is_rush', 'assigned_to']
    list_filter = ['date', 'status', 'task_type']
