from django.contrib import admin

from .models import PaymentTransaction


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = ['reference', 'gateway', 'purpose', 'amount', 'currency', 'status', 'created_at']
    list_filter = ['gateway', 'status', 'purpose']
    search_fields = ['reference', 'gateway_transaction_id', 'email', 'booking__confirmation_number']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
