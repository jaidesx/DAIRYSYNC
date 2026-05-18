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

admin.site.register(Institution)
admin.site.register(Fridge)
admin.site.register(Product)
admin.site.register(FridgeSlot)
admin.site.register(SensorReading)
admin.site.register(StockReading)
admin.site.register(Transaction)
admin.site.register(RestockOrder)
admin.site.register(Alert)