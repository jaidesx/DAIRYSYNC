from rest_framework import serializers
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


class InstitutionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Institution
        fields = '__all__'


class FridgeSerializer(serializers.ModelSerializer):
    institution_name = serializers.CharField(source='institution.name', read_only=True)

    class Meta:
        model = Fridge
        fields = '__all__'


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = '__all__'


class FridgeSlotSerializer(serializers.ModelSerializer):
    fridge_code = serializers.CharField(source='fridge.fridge_code', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)

    class Meta:
        model = FridgeSlot
        fields = '__all__'


class SensorReadingSerializer(serializers.ModelSerializer):
    fridge_code = serializers.CharField(source='fridge.fridge_code', read_only=True)

    class Meta:
        model = SensorReading
        fields = '__all__'


class StockReadingSerializer(serializers.ModelSerializer):
    fridge_slot_name = serializers.CharField(source='fridge_slot.__str__', read_only=True)

    class Meta:
        model = StockReading
        fields = '__all__'


class TransactionSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    fridge_code = serializers.CharField(source='fridge.fridge_code', read_only=True)

    class Meta:
        model = Transaction
        fields = '__all__'


class RestockOrderSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    fridge_code = serializers.CharField(source='fridge.fridge_code', read_only=True)

    class Meta:
        model = RestockOrder
        fields = '__all__'


class AlertSerializer(serializers.ModelSerializer):
    fridge_code = serializers.CharField(source='fridge.fridge_code', read_only=True)

    class Meta:
        model = Alert
        fields = '__all__'