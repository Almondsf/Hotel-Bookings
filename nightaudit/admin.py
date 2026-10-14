from django.contrib import admin

from .models import BusinessDay


@admin.register(BusinessDay)
class BusinessDayAdmin(admin.ModelAdmin):
    list_display = ['date', 'status', 'closed_at', 'closed_by']
    readonly_fields = ['date', 'status', 'opened_at', 'closed_at', 'closed_by', 'statistics']

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
