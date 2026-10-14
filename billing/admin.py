from django.contrib import admin

from .models import CorporateAccount, ExchangeRate, Folio, Invoice, TaxRule


class ReadOnlyAdmin(admin.ModelAdmin):
    """Money records change only through the billing services (with audit), never by hand."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Folio)
class FolioAdmin(ReadOnlyAdmin):
    list_display = ['id', 'booking', 'guest', 'name', 'account', 'status', 'opened_at']
    list_filter = ['status']
    search_fields = ['name', 'guest__last_name', 'booking__confirmation_number']


@admin.register(Invoice)
class InvoiceAdmin(ReadOnlyAdmin):
    list_display = ['number', 'folio', 'total', 'issued_at']
    search_fields = ['number']


@admin.register(TaxRule)
class TaxRuleAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'rate', 'is_active']

    def has_delete_permission(self, request, obj=None):
        return False  # deactivate instead; charges reference rule codes


@admin.register(CorporateAccount)
class CorporateAccountAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'credit_limit', 'is_active']
    search_fields = ['name', 'code']


@admin.register(ExchangeRate)
class ExchangeRateAdmin(ReadOnlyAdmin):
    list_display = ['currency', 'rate', 'effective_from', 'set_by']
