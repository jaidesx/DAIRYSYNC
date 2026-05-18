from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User

from .models import (
    Institution,
    Fridge,
    Product,
    FridgeSlot,
    SensorReading,
    StockReading,
    Alert,
    RestockOrder,
)


class DairyAppModelTests(TestCase):

    def setUp(self):
        self.institution = Institution.objects.create(
            name='Pioneer Mall',
            location='Kampala',
            contact_person='Manager',
            phone='0755062613'
        )

        self.fridge = Fridge.objects.create(
            fridge_code='FRIDGE001',
            institution=self.institution,
            temperature=4.5,
            humidity=60,
            voltage=12,
            status='online'
        )

        self.product = Product.objects.create(
            name='Lato Milk',
            price=3000,
            minimum_stock=5
        )

        self.slot = FridgeSlot.objects.create(
            fridge=self.fridge,
            product=self.product,
            slot_number=1,
            current_stock=10,
            motor_pin=18,
            ir_sensor_pin=19
        )

    def test_institution_created(self):
        self.assertEqual(self.institution.name, 'Pioneer Mall')

    def test_fridge_created(self):
        self.assertEqual(self.fridge.fridge_code, 'FRIDGE001')

    def test_product_created(self):
        self.assertEqual(self.product.name, 'Lato Milk')

    def test_fridge_slot_created(self):
        self.assertEqual(self.slot.current_stock, 10)


class DairyAppAPITests(TestCase):

    def setUp(self):
        self.client = Client()

        self.user = User.objects.create_user(
            username='admin',
            password='admin12345'
        )

        self.institution = Institution.objects.create(
            name='Pioneer Mall',
            location='Kampala',
            contact_person='Manager',
            phone='0755062613'
        )

        self.fridge = Fridge.objects.create(
            fridge_code='FRIDGE001',
            institution=self.institution,
            status='offline'
        )

        self.product = Product.objects.create(
            name='Lato Yoghurt',
            price=2500,
            minimum_stock=5
        )

        self.slot = FridgeSlot.objects.create(
            fridge=self.fridge,
            product=self.product,
            slot_number=1,
            current_stock=10,
            motor_pin=18,
            ir_sensor_pin=19
        )

    def test_sensor_api_receives_data(self):
        data = {
            "fridge_code": "FRIDGE001",
            "temperature": 4.5,
            "humidity": 60,
            "voltage": 12,
            "door_open": False,
            "stock": [
                {
                    "slot_number": 1,
                    "stock_level": 8
                }
            ]
        }

        response = self.client.post(
            reverse('receive_sensor_data'),
            data,
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 200)

        self.fridge.refresh_from_db()
        self.slot.refresh_from_db()

        self.assertEqual(self.fridge.status, 'online')
        self.assertEqual(self.slot.current_stock, 8)
        self.assertEqual(SensorReading.objects.count(), 1)
        self.assertEqual(StockReading.objects.count(), 1)

    def test_high_temperature_creates_alert(self):
        data = {
            "fridge_code": "FRIDGE001",
            "temperature": 9.0,
            "humidity": 70,
            "voltage": 12,
            "door_open": False,
            "stock": [
                {
                    "slot_number": 1,
                    "stock_level": 10
                }
            ]
        }

        response = self.client.post(
            reverse('receive_sensor_data'),
            data,
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Alert.objects.filter(alert_type='high_temperature').exists())

    def test_low_stock_creates_alert_and_order(self):
        data = {
            "fridge_code": "FRIDGE001",
            "temperature": 4.0,
            "humidity": 60,
            "voltage": 12,
            "door_open": False,
            "stock": [
                {
                    "slot_number": 1,
                    "stock_level": 3
                }
            ]
        }

        response = self.client.post(
            reverse('receive_sensor_data'),
            data,
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Alert.objects.filter(alert_type='low_stock').exists())
        self.assertTrue(RestockOrder.objects.filter(status='pending').exists())

    def test_fridges_api_returns_data(self):
        response = self.client.get(reverse('api_fridges'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)

    def test_products_api_returns_data(self):
        response = self.client.get(reverse('api_products'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)


class DairyAppProtectedViewsTests(TestCase):

    def setUp(self):
        self.client = Client()

        self.user = User.objects.create_user(
            username='admin',
            password='admin12345'
        )

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 302)

    def test_dashboard_opens_after_login(self):
        self.client.login(username='admin', password='admin12345')

        response = self.client.get(reverse('dashboard'))

        self.assertEqual(response.status_code, 200)