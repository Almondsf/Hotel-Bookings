from django.contrib import admin

from .models import KeyCard


@admin.register(KeyCard)
class KeyCardAdmin(admin.ModelAdmin):
    list_display = ['booking', 'room', 'status', 'valid_until', 'issued_by', 'issued_at']
    list_filter = ['status']

    def has_change_permission(self, request, obj=None):
        return False
