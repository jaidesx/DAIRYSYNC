from django import forms
from .models import Institution, Fridge, Product, FridgeSlot, Transaction


class InstitutionForm(forms.ModelForm):
    class Meta:
        model = Institution
        fields = '__all__'


class FridgeForm(forms.ModelForm):
    class Meta:
        model = Fridge
        fields = ['fridge_code', 'institution']


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = '__all__'


class FridgeSlotForm(forms.ModelForm):
    class Meta:
        model = FridgeSlot
        fields = ['fridge', 'product', 'slot_number', 'motor_pin', 'ir_sensor_pin']


class TransactionForm(forms.ModelForm):
    class Meta:
        model = Transaction
        fields = ['fridge', 'product', 'quantity', 'amount', 'payment_method']