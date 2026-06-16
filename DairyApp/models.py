from django.db import models
from django.conf import settings
from django.contrib.auth.models import User
from django.utils import timezone


class Institution(models.Model):
    name = models.CharField(max_length=150)
    location = models.CharField(max_length=200)
    contact_person = models.CharField(max_length=100)
    phone = models.CharField(max_length=20)

    def __str__(self):
        return self.name


class Fridge(models.Model):
    STATUS_CHOICES = [
        ('online', 'Online'),
        ('offline', 'Offline'),
        ('faulty', 'Faulty'),
    ]

    fridge_code     = models.CharField(max_length=50, unique=True)
    institution     = models.ForeignKey(Institution, on_delete=models.CASCADE)
    temperature     = models.FloatField(default=0)
    humidity        = models.FloatField(default=0)
    door_open       = models.BooleanField(default=False)
    voltage         = models.FloatField(default=0)
    status          = models.CharField(max_length=20, choices=STATUS_CHOICES, default='offline', db_index=True)
    last_seen       = models.DateTimeField(blank=True, null=True, db_index=True)
    last_updated    = models.DateTimeField(auto_now=True)
    qr_code         = models.ImageField(upload_to='qr_codes/', blank=True, null=True)
    temp_threshold  = models.FloatField(
        default=6.0,
        help_text='Temperature (°C) above which a high-temp alert is triggered',
    )

    def __str__(self):
        return self.fridge_code

    @property
    def is_stale(self):
        """True if the last heartbeat is older than the configured offline timeout."""
        if not self.last_seen:
            return True
        timeout = getattr(settings, 'FRIDGE_OFFLINE_TIMEOUT_SECONDS', 300)
        return (timezone.now() - self.last_seen).total_seconds() > timeout

    @property
    def is_online(self):
        return self.status == 'online' and not self.is_stale


class Product(models.Model):
    name             = models.CharField(max_length=100)
    price            = models.DecimalField(max_digits=10, decimal_places=2)
    minimum_stock    = models.PositiveIntegerField(default=5)
    restock_quantity = models.PositiveIntegerField(
        default=20,
        help_text='Quantity to order when an automatic restock order is created',
    )

    def __str__(self):
        return self.name


class FridgeSlot(models.Model):
    fridge        = models.ForeignKey(Fridge, on_delete=models.CASCADE)
    product       = models.ForeignKey(Product, on_delete=models.CASCADE)
    slot_number   = models.PositiveIntegerField()
    current_stock = models.PositiveIntegerField(default=0)
    motor_pin     = models.PositiveIntegerField()
    ir_sensor_pin = models.PositiveIntegerField()

    def __str__(self):
        return f"{self.fridge.fridge_code} - Slot {self.slot_number}"


class SensorReading(models.Model):
    fridge      = models.ForeignKey(Fridge, on_delete=models.CASCADE)
    temperature = models.FloatField()
    humidity    = models.FloatField()
    voltage     = models.FloatField()
    door_open   = models.BooleanField(default=False)
    recorded_at = models.DateTimeField(auto_now_add=True, db_index=True)

    def __str__(self):
        return f"{self.fridge.fridge_code} Reading"


class StockReading(models.Model):
    fridge_slot = models.ForeignKey(FridgeSlot, on_delete=models.CASCADE)
    stock_level = models.PositiveIntegerField()
    recorded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.fridge_slot} - {self.stock_level}"


class Transaction(models.Model):
    PAYMENT_CHOICES = [
        ('cashless', 'Cashless'),
        ('manual', 'Manual'),
    ]

    product        = models.ForeignKey(Product, on_delete=models.CASCADE)
    fridge         = models.ForeignKey(Fridge, on_delete=models.CASCADE)
    quantity       = models.PositiveIntegerField(default=1)
    amount         = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=30, choices=PAYMENT_CHOICES)
    created_at     = models.DateTimeField(auto_now_add=True)
    voided         = models.BooleanField(default=False, db_index=True)
    voided_at      = models.DateTimeField(null=True, blank=True)
    voided_by      = models.ForeignKey(
        User, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='voided_transactions',
    )

    def __str__(self):
        return f"{self.product.name} - {self.amount}"


class RestockOrder(models.Model):
    STATUS_CHOICES = [
        ('pending',   'Pending'),
        ('approved',  'Approved'),
        ('delivered', 'Delivered'),
    ]

    fridge          = models.ForeignKey(Fridge, on_delete=models.CASCADE)
    product         = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity_needed = models.PositiveIntegerField()
    status          = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    created_by      = models.ForeignKey(
        User, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='restock_orders',
    )

    def __str__(self):
        return f"Restock {self.product.name} for {self.fridge.fridge_code}"


class Alert(models.Model):
    ALERT_TYPES = [
        ('low_stock',        'Low Stock'),
        ('high_temperature', 'High Temperature'),
        ('door_open',        'Door Open'),
        ('power_fault',      'Power Fault'),
        ('motor_fault',      'Motor Fault'),
    ]

    fridge     = models.ForeignKey(Fridge, on_delete=models.CASCADE)
    alert_type = models.CharField(max_length=50, choices=ALERT_TYPES)
    message    = models.TextField()
    resolved   = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.alert_type


class NotificationPreference(models.Model):
    user                    = models.OneToOneField(User, on_delete=models.CASCADE, related_name='notification_preference')
    email_enabled           = models.BooleanField(default=True)
    sms_enabled             = models.BooleanField(default=False)
    notify_high_temperature = models.BooleanField(default=True)
    notify_low_stock        = models.BooleanField(default=True)
    notify_door_open        = models.BooleanField(default=True)
    notify_power_fault      = models.BooleanField(default=True)
    notify_motor_fault      = models.BooleanField(default=True)
    custom_email            = models.EmailField(blank=True, help_text='Leave blank to use your account email')
    custom_phone            = models.CharField(max_length=20, blank=True, help_text='e.g. +254712345678')

    def __str__(self):
        return f'{self.user.username} notification preferences'

    def get_email(self):
        return self.custom_email or self.user.email

    def get_phone(self):
        return self.custom_phone


class Feedback(models.Model):
    CATEGORY_CHOICES = [
        ('bug',        'Bug Report'),
        ('suggestion', 'Suggestion'),
        ('general',    'General Feedback'),
    ]
    STATUS_CHOICES = [
        ('open',     'Open'),
        ('reviewed', 'Reviewed'),
        ('resolved', 'Resolved'),
    ]

    user       = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='feedbacks')
    category   = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='general')
    subject    = models.CharField(max_length=200)
    message    = models.TextField()
    status     = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'[{self.get_category_display()}] {self.subject}'
