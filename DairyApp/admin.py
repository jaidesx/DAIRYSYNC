from django.contrib import admin
from .models import (
    Institution,
    Fridge,
    Product,
    FridgeSlot,
    SensorReading,
    StockReading,
    Transaction,
    RestockOrder,
    Alert,
)


@admin.register(Institution)
class InstitutionAdmin(admin.ModelAdmin):
    list_display = ['name', 'location', 'contact_person', 'phone']
    search_fields = ['name', 'location', 'contact_person']
    ordering = ['name']


@admin.register(Fridge)
class FridgeAdmin(admin.ModelAdmin):
    list_display = ['fridge_code', 'institution', 'status', 'temperature', 'humidity', 'voltage', 'door_open', 'last_updated']
    list_filter = ['status', 'institution', 'door_open']
    search_fields = ['fridge_code', 'institution__name']
    readonly_fields = ['temperature', 'humidity', 'voltage', 'door_open', 'status', 'last_updated', 'qr_code']
    ordering = ['fridge_code']


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['name', 'price', 'minimum_stock']
    search_fields = ['name']
    ordering = ['name']


@admin.register(FridgeSlot)
class FridgeSlotAdmin(admin.ModelAdmin):
    list_display = ['fridge', 'slot_number', 'product', 'current_stock', 'motor_pin', 'ir_sensor_pin']
    list_filter = ['fridge', 'product']
    search_fields = ['fridge__fridge_code', 'product__name']
    readonly_fields = ['current_stock']
    ordering = ['fridge', 'slot_number']


@admin.register(SensorReading)
class SensorReadingAdmin(admin.ModelAdmin):
    list_display = ['fridge', 'temperature', 'humidity', 'voltage', 'door_open', 'recorded_at']
    list_filter = ['fridge', 'door_open']
    search_fields = ['fridge__fridge_code']
    readonly_fields = ['fridge', 'temperature', 'humidity', 'voltage', 'door_open', 'recorded_at']
    ordering = ['-recorded_at']


@admin.register(StockReading)
class StockReadingAdmin(admin.ModelAdmin):
    list_display = ['fridge_slot', 'stock_level', 'recorded_at']
    list_filter = ['fridge_slot__fridge', 'fridge_slot__product']
    search_fields = ['fridge_slot__fridge__fridge_code', 'fridge_slot__product__name']
    readonly_fields = ['fridge_slot', 'stock_level', 'recorded_at']
    ordering = ['-recorded_at']


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ['product', 'fridge', 'quantity', 'amount', 'payment_method', 'created_at']
    list_filter = ['payment_method', 'fridge', 'product']
    search_fields = ['product__name', 'fridge__fridge_code']
    readonly_fields = ['created_at']
    ordering = ['-created_at']


@admin.register(RestockOrder)
class RestockOrderAdmin(admin.ModelAdmin):
    list_display = ['fridge', 'product', 'quantity_needed', 'status', 'created_at']
    list_filter = ['status', 'fridge', 'product']
    search_fields = ['fridge__fridge_code', 'product__name']
    readonly_fields = ['created_at']
    ordering = ['-created_at']
    actions = ['mark_approved', 'mark_delivered']

    @admin.action(description='Mark selected orders as Approved')
    def mark_approved(self, request, queryset):
        queryset.update(status='approved')

    @admin.action(description='Mark selected orders as Delivered')
    def mark_delivered(self, request, queryset):
        queryset.update(status='delivered')


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ['fridge', 'alert_type', 'message', 'resolved', 'created_at']
    list_filter = ['alert_type', 'resolved', 'fridge']
    search_fields = ['fridge__fridge_code', 'message']
    readonly_fields = ['fridge', 'alert_type', 'message', 'created_at']
    ordering = ['-created_at']
    actions = ['mark_resolved']

    @admin.action(description='Mark selected alerts as Resolved')
    def mark_resolved(self, request, queryset):
        queryset.update(resolved=True)
