from django import forms
from .models import Institution, Fridge, Product, FridgeSlot


class InstitutionForm(forms.ModelForm):
    class Meta:
        model = Institution
        fields = '__all__'


class FridgeForm(forms.ModelForm):
    class Meta:
        model = Fridge
        fields = '__all__'


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = '__all__'


class FridgeSlotForm(forms.ModelForm):
    class Meta:
        model = FridgeSlot
        fields = '__all__'