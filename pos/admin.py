from django.contrib import admin

from .models import Order, Outlet, Product


@admin.register(Outlet)
class OutletAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'kind', 'is_active']


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['name', 'outlet', 'section', 'price', 'is_available', 'stock_quantity']
    list_filter = ['outlet', 'is_available']
    search_fields = ['name']


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['id', 'outlet', 'table_label', 'status', 'opened_at', 'settled_at']
    list_filter = ['outlet', 'status']

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
