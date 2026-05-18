from django.db import models


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

    fridge_code = models.CharField(max_length=50, unique=True)
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE)
    temperature = models.FloatField(default=0)
    humidity = models.FloatField(default=0)
    door_open = models.BooleanField(default=False)
    voltage = models.FloatField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='offline')
    last_updated = models.DateTimeField(auto_now=True)
    qr_code = models.ImageField(upload_to='qr_codes/', blank=True, null=True)

    def __str__(self):
        return self.fridge_code


class Product(models.Model):
    name = models.CharField(max_length=100)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    minimum_stock = models.PositiveIntegerField(default=5)

    def __str__(self):
        return self.name


class FridgeSlot(models.Model):
    fridge = models.ForeignKey(Fridge, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    slot_number = models.PositiveIntegerField()
    current_stock = models.PositiveIntegerField(default=0)
    motor_pin = models.PositiveIntegerField()
    ir_sensor_pin = models.PositiveIntegerField()

    def __str__(self):
        return f"{self.fridge.fridge_code} - Slot {self.slot_number}"


class SensorReading(models.Model):
    fridge = models.ForeignKey(Fridge, on_delete=models.CASCADE)
    temperature = models.FloatField()
    humidity = models.FloatField()
    voltage = models.FloatField()
    door_open = models.BooleanField(default=False)
    recorded_at = models.DateTimeField(auto_now_add=True)

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

    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    fridge = models.ForeignKey(Fridge, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=30, choices=PAYMENT_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.product.name} - {self.amount}"


class RestockOrder(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('delivered', 'Delivered'),
    ]

    fridge = models.ForeignKey(Fridge, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity_needed = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Restock {self.product.name} for {self.fridge.fridge_code}"


class Alert(models.Model):
    ALERT_TYPES = [
        ('low_stock', 'Low Stock'),
        ('high_temperature', 'High Temperature'),
        ('door_open', 'Door Open'),
        ('power_fault', 'Power Fault'),
        ('motor_fault', 'Motor Fault'),
    ]

    fridge = models.ForeignKey(Fridge, on_delete=models.CASCADE)
    alert_type = models.CharField(max_length=50, choices=ALERT_TYPES)
    message = models.TextField()
    resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.alert_type