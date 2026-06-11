from django import forms
from .models import Institution, Fridge, Product, FridgeSlot, Transaction, NotificationPreference, Feedback


class InstitutionForm(forms.ModelForm):
    class Meta:
        model = Institution
        fields = '__all__'


class FridgeForm(forms.ModelForm):
    class Meta:
        model  = Fridge
        fields = ['fridge_code', 'institution', 'temp_threshold']
        labels = {
            'temp_threshold': 'Temperature alert threshold (°C)',
        }
        help_texts = {
            'temp_threshold': 'An alert fires when the fridge exceeds this temperature.',
        }


class ProductForm(forms.ModelForm):
    class Meta:
        model  = Product
        fields = '__all__'
        labels = {
            'restock_quantity': 'Auto-restock quantity',
        }
        help_texts = {
            'restock_quantity': 'Units to order when an automatic restock order is created.',
        }


class FridgeSlotForm(forms.ModelForm):
    class Meta:
        model  = FridgeSlot
        fields = ['fridge', 'product', 'slot_number', 'motor_pin', 'ir_sensor_pin']


class TransactionForm(forms.ModelForm):
    class Meta:
        model  = Transaction
        fields = ['fridge', 'product', 'quantity', 'amount', 'payment_method']


class NotificationPreferenceForm(forms.ModelForm):
    class Meta:
        model  = NotificationPreference
        fields = [
            'email_enabled', 'sms_enabled',
            'custom_email', 'custom_phone',
            'notify_high_temperature', 'notify_low_stock',
            'notify_door_open', 'notify_power_fault', 'notify_motor_fault',
        ]
        labels = {
            'email_enabled':           'Email notifications',
            'sms_enabled':             'SMS notifications',
            'custom_email':            'Email address',
            'custom_phone':            'Phone number',
            'notify_high_temperature': 'High temperature alerts',
            'notify_low_stock':        'Low stock alerts',
            'notify_door_open':        'Door open alerts',
            'notify_power_fault':      'Power fault alerts',
            'notify_motor_fault':      'Motor fault alerts',
        }


class FeedbackForm(forms.ModelForm):
    class Meta:
        model   = Feedback
        fields  = ['category', 'subject', 'message']
        widgets = {
            'message': forms.Textarea(attrs={'rows': 5}),
        }
