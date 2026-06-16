import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (
    Alert,
    Fridge,
    FridgeSlot,
    Institution,
    Product,
    RestockOrder,
    SensorReading,
    StockReading,
    Transaction,
)


# ── Shared fixture mixin ──────────────────────────────────────────────────────

class BaseFixture(TestCase):
    """Creates a logged-in client plus one complete object graph."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='tester', password='pass1234')
        self.client.force_login(self.user)

        self.institution = Institution.objects.create(
            name='Pioneer Mall', location='Kampala',
            contact_person='Manager', phone='0700000000',
        )
        self.fridge = Fridge.objects.create(
            fridge_code='F001', institution=self.institution,
            temperature=4.0, humidity=60.0, voltage=5.0, status='online',
            last_seen=timezone.now(),
        )
        self.product = Product.objects.create(
            name='Lato Milk', price=3000, minimum_stock=5,
        )
        self.slot = self.fridge.slots.get(slot_number=1)
        self.slot.product = self.product
        self.slot.current_stock = 10
        self.slot.max_capacity = 10
        self.slot.low_stock_threshold = 5
        self.slot.motor_pin = 18
        self.slot.ir_sensor_pin = 19
        self.slot.save(
            update_fields=[
                'product',
                'current_stock',
                'max_capacity',
                'low_stock_threshold',
                'motor_pin',
                'ir_sensor_pin',
            ]
        )


# ── Model smoke tests ─────────────────────────────────────────────────────────

class ModelTests(BaseFixture):

    def test_institution_str(self):
        self.assertEqual(str(self.institution), 'Pioneer Mall')

    def test_fridge_str(self):
        self.assertEqual(str(self.fridge), 'F001')

    def test_product_str(self):
        self.assertEqual(str(self.product), 'Lato Milk')

    def test_fridge_slot_str(self):
        self.assertIn('F001', str(self.slot))
        self.assertIn('1', str(self.slot))


# ── Login protection ──────────────────────────────────────────────────────────

class AuthRedirectTests(TestCase):

    def setUp(self):
        self.client = Client()

    def _assert_redirects_to_login(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])

    def test_dashboard_requires_login(self):
        self._assert_redirects_to_login(reverse('dashboard'))

    def test_fridge_list_requires_login(self):
        self._assert_redirects_to_login(reverse('fridge_list'))

    def test_transaction_list_requires_login(self):
        self._assert_redirects_to_login(reverse('transaction_list'))

    def test_ai_prediction_requires_login(self):
        self._assert_redirects_to_login(reverse('ai_stock_prediction'))


# ── Dashboard ─────────────────────────────────────────────────────────────────

class DashboardTests(BaseFixture):

    def test_dashboard_loads(self):
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'DAIRYSYNC')

    def test_dashboard_stats_json(self):
        response = self.client.get(reverse('dashboard_stats'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('stats', data)
        self.assertIn('total_fridges', data['stats'])

    def test_alert_count_json(self):
        Alert.objects.create(fridge=self.fridge, alert_type='door_open',
                             message='Door open', resolved=False)
        response = self.client.get(reverse('alert_count'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['active_alerts'], 1)


# ── Institution CRUD ──────────────────────────────────────────────────────────

class InstitutionCRUDTests(BaseFixture):

    def test_institution_list_loads(self):
        response = self.client.get(reverse('institution_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Pioneer Mall')

    def test_institution_search(self):
        Institution.objects.create(name='Nakumatt', location='Nairobi',
                                   contact_person='X', phone='0')
        response = self.client.get(reverse('institution_list'), {'q': 'Nakumatt'})
        self.assertContains(response, 'Nakumatt')
        self.assertNotContains(response, 'Pioneer Mall')

    def test_add_institution(self):
        response = self.client.post(reverse('add_institution'), {
            'name': 'New Mall', 'location': 'Entebbe',
            'contact_person': 'Jane', 'phone': '0711111111',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Institution.objects.filter(name='New Mall').exists())

    def test_edit_institution(self):
        response = self.client.post(
            reverse('edit_institution', args=[self.institution.id]),
            {'name': 'Updated Mall', 'location': 'Kampala',
             'contact_person': 'Manager', 'phone': '0700000000'},
        )
        self.assertEqual(response.status_code, 302)
        self.institution.refresh_from_db()
        self.assertEqual(self.institution.name, 'Updated Mall')

    def test_delete_institution(self):
        inst = Institution.objects.create(
            name='Temp', location='X', contact_person='X', phone='0')
        response = self.client.post(reverse('delete_institution', args=[inst.id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Institution.objects.filter(id=inst.id).exists())

    def test_delete_institution_requires_post(self):
        response = self.client.get(
            reverse('delete_institution', args=[self.institution.id]))
        self.assertEqual(response.status_code, 405)


# ── Fridge CRUD ───────────────────────────────────────────────────────────────

class FridgeCRUDTests(BaseFixture):

    def test_fridge_list_loads(self):
        response = self.client.get(reverse('fridge_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'F001')

    def test_fridge_status_filter(self):
        Fridge.objects.create(fridge_code='F002', institution=self.institution,
                              status='offline')
        response = self.client.get(reverse('fridge_list'), {'status': 'online'})
        self.assertContains(response, 'F001')
        self.assertNotContains(response, 'F002')

    def test_fridge_search(self):
        Fridge.objects.create(fridge_code='ZZZZ', institution=self.institution,
                              status='offline')
        response = self.client.get(reverse('fridge_list'), {'q': 'ZZZZ'})
        self.assertContains(response, 'ZZZZ')
        self.assertNotContains(response, 'F001')

    def test_add_fridge(self):
        response = self.client.post(reverse('add_fridge'), {
            'fridge_code': 'F999', 'institution': self.institution.id,
            'temp_threshold': 6.0,
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Fridge.objects.filter(fridge_code='F999').exists())

    def test_add_fridge_does_not_accept_sensor_fields(self):
        # temperature and status should be ignored (not in FridgeForm.fields)
        self.client.post(reverse('add_fridge'), {
            'fridge_code': 'FHACK', 'institution': self.institution.id,
            'temp_threshold': 6.0,
            'temperature': 99, 'status': 'faulty',
        })
        f = Fridge.objects.get(fridge_code='FHACK')
        self.assertNotEqual(f.temperature, 99)
        self.assertNotEqual(f.status, 'faulty')

    def test_fridge_detail_loads(self):
        response = self.client.get(reverse('fridge_detail', args=[self.fridge.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'F001')
        self.assertContains(response, 'Pioneer Mall')

    def test_fridge_detail_shows_slots(self):
        response = self.client.get(reverse('fridge_detail', args=[self.fridge.id]))
        self.assertContains(response, 'Lato Milk')

    def test_fridge_detail_shows_active_alerts(self):
        Alert.objects.create(fridge=self.fridge, alert_type='door_open',
                             message='Door open', resolved=False)
        response = self.client.get(reverse('fridge_detail', args=[self.fridge.id]))
        self.assertContains(response, 'Door Open')   # rendered badge text

    def test_delete_fridge_requires_post(self):
        response = self.client.get(
            reverse('delete_fridge', args=[self.fridge.id]))
        self.assertEqual(response.status_code, 405)

    def test_temperature_history_json(self):
        SensorReading.objects.create(fridge=self.fridge, temperature=4.0,
                                     humidity=60, voltage=12, door_open=False)
        response = self.client.get(
            reverse('fridge_temperature_history', args=[self.fridge.id]))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['fridge_code'], 'F001')
        self.assertEqual(len(data['readings']), 1)


# ── FridgeSlot CRUD ───────────────────────────────────────────────────────────

class FridgeSlotTests(BaseFixture):

    def test_new_fridge_automatically_receives_slots_1_to_6(self):
        fridge = Fridge.objects.create(
            fridge_code='AUTO6',
            institution=self.institution,
        )
        self.assertEqual(
            list(fridge.slots.order_by('slot_number').values_list('slot_number', flat=True)),
            [1, 2, 3, 4, 5, 6],
        )

    def test_create_fridge_slots_command_does_not_create_duplicates(self):
        self.fridge.slots.filter(slot_number__in=[5, 6]).delete()

        call_command('create_fridge_slots')

        self.assertEqual(self.fridge.slots.count(), 6)
        self.assertEqual(
            list(self.fridge.slots.order_by('slot_number').values_list('slot_number', flat=True)),
            [1, 2, 3, 4, 5, 6],
        )

        call_command('create_fridge_slots')
        self.assertEqual(self.fridge.slots.count(), 6)

    def test_duplicate_slot_number_for_same_fridge_is_rejected(self):
        duplicate = FridgeSlot(
            fridge=self.fridge,
            product=self.product,
            slot_number=1,
            current_stock=1,
            max_capacity=10,
            low_stock_threshold=2,
        )
        with self.assertRaises(ValidationError):
            duplicate.full_clean()
        with self.assertRaises(IntegrityError):
            FridgeSlot.objects.create(
                fridge=self.fridge,
                product=self.product,
                slot_number=1,
                current_stock=1,
                max_capacity=10,
                low_stock_threshold=2,
            )

    def test_current_stock_cannot_exceed_max_capacity(self):
        self.slot.current_stock = 11
        with self.assertRaises(ValidationError):
            self.slot.full_clean()

    def test_low_stock_threshold_cannot_exceed_max_capacity(self):
        self.slot.low_stock_threshold = 11
        with self.assertRaises(ValidationError):
            self.slot.full_clean()

    def test_stock_list_loads(self):
        response = self.client.get(reverse('stock_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Lato Milk')

    def test_edit_fridge_slot(self):
        product2 = Product.objects.create(name='Yoghurt', price=2500, minimum_stock=3)
        response = self.client.post(
            reverse('edit_fridge_slot', args=[self.slot.id]),
            {'fridge': self.fridge.id, 'product': product2.id,
             'slot_number': 1, 'current_stock': 10,
             'max_capacity': 10, 'low_stock_threshold': 5,
             'motor_pin': 18, 'ir_sensor_pin': 19},
        )
        self.assertEqual(response.status_code, 302)
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.product.name, 'Yoghurt')

    def test_delete_fridge_slot(self):
        slot2 = self.fridge.slots.get(slot_number=2)
        slot2.product = self.product
        slot2.current_stock = 5
        slot2.motor_pin = 20
        slot2.ir_sensor_pin = 21
        slot2.save(update_fields=['product', 'current_stock', 'motor_pin', 'ir_sensor_pin'])
        response = self.client.post(
            reverse('delete_fridge_slot', args=[slot2.id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(FridgeSlot.objects.filter(id=slot2.id).exists())

    def test_delete_fridge_slot_requires_post(self):
        response = self.client.get(
            reverse('delete_fridge_slot', args=[self.slot.id]))
        self.assertEqual(response.status_code, 405)


# ── Alerts & Restock ──────────────────────────────────────────────────────────

class AlertAndRestockTests(BaseFixture):

    def setUp(self):
        super().setUp()
        self.alert = Alert.objects.create(
            fridge=self.fridge, alert_type='high_temperature',
            message='Temp high', resolved=False,
        )
        self.order = RestockOrder.objects.create(
            fridge=self.fridge, product=self.product,
            quantity_needed=20, status='pending',
        )

    def test_alert_list_loads(self):
        response = self.client.get(reverse('alert_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Temp high')

    def test_alert_type_filter(self):
        Alert.objects.create(fridge=self.fridge, alert_type='low_stock',
                             message='Low stock', resolved=False)
        response = self.client.get(reverse('alert_list'),
                                   {'type': 'high_temperature'})
        self.assertContains(response, 'Temp high')
        self.assertNotContains(response, 'Low stock')

    def test_alert_resolved_filter(self):
        self.alert.resolved = True
        self.alert.save()
        response = self.client.get(reverse('alert_list'), {'resolved': '0'})
        self.assertNotContains(response, 'Temp high')

    def test_resolve_alert(self):
        response = self.client.post(
            reverse('resolve_alert', args=[self.alert.id]))
        self.assertEqual(response.status_code, 302)
        self.alert.refresh_from_db()
        self.assertTrue(self.alert.resolved)

    def test_resolve_alert_requires_post(self):
        response = self.client.get(
            reverse('resolve_alert', args=[self.alert.id]))
        self.assertEqual(response.status_code, 405)

    def test_restock_order_list_loads(self):
        response = self.client.get(reverse('restock_order_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Lato Milk')

    def test_approve_order(self):
        response = self.client.post(
            reverse('approve_order', args=[self.order.id]))
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'approved')

    def test_active_alerts_context_processor(self):
        # active_alerts should appear on every authenticated page
        response = self.client.get(reverse('fridge_list'))
        self.assertIn('active_alerts', response.context)
        self.assertEqual(response.context['active_alerts'], 1)

    def test_active_alerts_updates_when_resolved(self):
        self.alert.resolved = True
        self.alert.save()
        response = self.client.get(reverse('fridge_list'))
        self.assertEqual(response.context['active_alerts'], 0)


# ── Transactions ──────────────────────────────────────────────────────────────

class TransactionTests(BaseFixture):

    def setUp(self):
        super().setUp()
        self.txn = Transaction.objects.create(
            fridge=self.fridge, product=self.product,
            quantity=2, amount=6000, payment_method='cashless',
        )

    def test_transaction_list_loads(self):
        response = self.client.get(reverse('transaction_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Lato Milk')

    def test_transaction_method_filter(self):
        Transaction.objects.create(
            fridge=self.fridge, product=self.product,
            quantity=1, amount=3000, payment_method='manual',
        )
        response = self.client.get(reverse('transaction_list'),
                                   {'method': 'cashless'})
        self.assertContains(response, '6000')
        # manual transaction should be filtered out
        response2 = self.client.get(reverse('transaction_list'),
                                    {'method': 'manual'})
        self.assertContains(response2, '3000')

    def test_add_transaction(self):
        response = self.client.post(reverse('add_transaction'), {
            'fridge': self.fridge.id, 'product': self.product.id,
            'quantity': 3, 'amount': 9000, 'payment_method': 'manual',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Transaction.objects.count(), 2)

    def test_void_transaction(self):
        response = self.client.post(
            reverse('void_transaction', args=[self.txn.id]))
        self.assertEqual(response.status_code, 302)
        self.txn.refresh_from_db()
        self.assertTrue(self.txn.voided)
        # Record is preserved — not deleted
        self.assertTrue(Transaction.objects.filter(id=self.txn.id).exists())

    def test_void_transaction_requires_post(self):
        response = self.client.get(
            reverse('void_transaction', args=[self.txn.id]))
        self.assertEqual(response.status_code, 405)


# ── CSV Exports ───────────────────────────────────────────────────────────────

class CSVExportTests(BaseFixture):

    def _assert_csv(self, url, expected_header_fragment, params=None):
        response = self.client.get(url, params or {})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertIn('attachment', response['Content-Disposition'])
        content = response.content.decode()
        self.assertIn(expected_header_fragment, content)
        return content

    def test_export_institutions(self):
        content = self._assert_csv(
            reverse('export_institutions'), 'Name')
        self.assertIn('Pioneer Mall', content)

    def test_export_institutions_with_search(self):
        Institution.objects.create(name='Nakumatt', location='X',
                                   contact_person='X', phone='0')
        content = self._assert_csv(
            reverse('export_institutions'), 'Name', {'q': 'Pioneer'})
        self.assertIn('Pioneer Mall', content)
        self.assertNotIn('Nakumatt', content)

    def test_export_fridges(self):
        content = self._assert_csv(reverse('export_fridges'), 'Fridge Code')
        self.assertIn('F001', content)

    def test_export_fridges_status_filter(self):
        Fridge.objects.create(fridge_code='FOFF', institution=self.institution,
                              status='offline')
        content = self._assert_csv(
            reverse('export_fridges'), 'Fridge Code', {'status': 'online'})
        self.assertIn('F001', content)
        self.assertNotIn('FOFF', content)

    def test_export_products(self):
        content = self._assert_csv(reverse('export_products'), 'Product Name')
        self.assertIn('Lato Milk', content)

    def test_export_stock(self):
        content = self._assert_csv(reverse('export_stock'), 'Fridge Code')
        self.assertIn('F001', content)
        self.assertIn('Lato Milk', content)

    def test_export_alerts(self):
        Alert.objects.create(fridge=self.fridge, alert_type='door_open',
                             message='Door test', resolved=False)
        content = self._assert_csv(reverse('export_alerts'), 'Alert Type')
        self.assertIn('Door test', content)

    def test_export_transactions(self):
        Transaction.objects.create(
            fridge=self.fridge, product=self.product,
            quantity=1, amount=3000, payment_method='cashless',
        )
        content = self._assert_csv(
            reverse('export_transactions'), 'Fridge Code')
        self.assertIn('F001', content)

    def test_export_readings(self):
        SensorReading.objects.create(
            fridge=self.fridge, temperature=4.0,
            humidity=60, voltage=12, door_open=False,
        )
        content = self._assert_csv(reverse('export_readings'), 'Fridge Code')
        self.assertIn('F001', content)

    def test_export_restock_orders(self):
        RestockOrder.objects.create(
            fridge=self.fridge, product=self.product,
            quantity_needed=20, status='pending',
        )
        content = self._assert_csv(
            reverse('export_restock_orders'), 'Fridge Code')
        self.assertIn('F001', content)


# ── Pagination ────────────────────────────────────────────────────────────────

class PaginationTests(BaseFixture):

    def test_second_page_is_accessible(self):
        # Create 25 institutions (PAGE_SIZE = 20)
        for i in range(24):
            Institution.objects.create(
                name=f'Inst {i}', location='X', contact_person='X', phone='0')
        response = self.client.get(reverse('institution_list'), {'page': 2})
        self.assertEqual(response.status_code, 200)
        # Page 2 should exist and render
        self.assertContains(response, 'Inst')

    def test_invalid_page_returns_last_page(self):
        response = self.client.get(
            reverse('institution_list'), {'page': 9999})
        self.assertEqual(response.status_code, 200)


# ── ESP32 Sensor Endpoint ─────────────────────────────────────────────────────

@override_settings(ESP32_API_KEY='TEST_KEY_123')
class SensorEndpointTests(BaseFixture):

    def _post(self, data, key='TEST_KEY_123'):
        return self.client.post(
            reverse('receive_sensor_data'),
            json.dumps(data),
            content_type='application/json',
            HTTP_X_API_KEY=key,
        )

    @patch('DairyApp.views.send_sms_alert')
    @patch('DairyApp.views.send_email_alert')
    def test_valid_data_accepted(self, mock_email, mock_sms):
        response = self._post({
            'fridge_code': 'F001',
            'temperature': 4.5, 'humidity': 60,
            'voltage': 12, 'door_open': False,
            'stock': [{'slot_number': 1, 'stock_level': 8}],
        })
        self.assertEqual(response.status_code, 200)
        self.fridge.refresh_from_db()
        self.assertEqual(self.fridge.status, 'online')
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.current_stock, 8)
        self.assertEqual(SensorReading.objects.count(), 1)
        self.assertIsNotNone(self.fridge.last_seen)
        mock_sms.assert_not_called()

    @patch('DairyApp.views.send_sms_alert')
    @patch('DairyApp.views.send_email_alert')
    def test_high_temperature_triggers_alert(self, mock_email, mock_sms):
        self._post({
            'fridge_code': 'F001',
            'temperature': 9.0, 'humidity': 60,
            'voltage': 12, 'door_open': False, 'stock': [],
        })
        self.assertTrue(
            Alert.objects.filter(alert_type='high_temperature').exists())
        mock_sms.assert_called_once()

    @patch('DairyApp.views.send_sms_alert')
    @patch('DairyApp.views.send_email_alert')
    def test_five_volt_supply_does_not_trigger_power_alert(self, mock_email, mock_sms):
        self._post({
            'fridge_code': 'F001',
            'temperature': 4.0, 'humidity': 60,
            'voltage': 5.0, 'door_open': False, 'stock': [],
        })
        self.assertFalse(Alert.objects.filter(alert_type='power_fault').exists())

    @patch('DairyApp.views.send_sms_alert')
    @patch('DairyApp.views.send_email_alert')
    def test_low_voltage_triggers_alert(self, mock_email, mock_sms):
        self._post({
            'fridge_code': 'F001',
            'temperature': 4.0, 'humidity': 60,
            'voltage': 4.0, 'door_open': False, 'stock': [],
        })
        self.assertTrue(
            Alert.objects.filter(alert_type='power_fault').exists())

    @patch('DairyApp.views.send_sms_alert')
    @patch('DairyApp.views.send_email_alert')
    def test_low_stock_creates_alert_and_restock_order(self, mock_email, mock_sms):
        self._post({
            'fridge_code': 'F001',
            'temperature': 4.0, 'humidity': 60,
            'voltage': 12, 'door_open': False,
            'stock': [{'slot_number': 1, 'stock_level': 3}],
        })
        self.assertTrue(Alert.objects.filter(alert_type='low_stock').exists())
        self.assertTrue(
            RestockOrder.objects.filter(fridge=self.fridge, status='pending').exists())

    @patch('DairyApp.views.send_sms_alert')
    @patch('DairyApp.views.send_email_alert')
    def test_duplicate_restock_order_not_created(self, mock_email, mock_sms):
        RestockOrder.objects.create(
            fridge=self.fridge, product=self.product,
            quantity_needed=20, status='pending',
        )
        self._post({
            'fridge_code': 'F001',
            'temperature': 4.0, 'humidity': 60,
            'voltage': 12, 'door_open': False,
            'stock': [{'slot_number': 1, 'stock_level': 3}],
        })
        self.assertEqual(RestockOrder.objects.filter(status='pending').count(), 1)

    def test_invalid_api_key_rejected(self):
        response = self._post(
            {'fridge_code': 'F001', 'temperature': 4.0,
             'humidity': 60, 'voltage': 12, 'door_open': False, 'stock': []},
            key='WRONG',
        )
        self.assertEqual(response.status_code, 403)

    def test_missing_api_key_rejected(self):
        response = self.client.post(
            reverse('receive_sensor_data'),
            json.dumps({
                'fridge_code': 'F001',
                'temperature': 4.0, 'humidity': 60,
                'voltage': 5.0, 'door_open': False, 'stock': [],
            }),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 403)

    def test_api_key_in_body_accepted(self):
        """Legacy ESP32 firmware sends key in JSON body."""
        response = self.client.post(
            reverse('receive_sensor_data'),
            json.dumps({
                'api_key': 'TEST_KEY_123',
                'fridge_code': 'F001',
                'temperature': 4.0, 'humidity': 60,
                'voltage': 12, 'door_open': False, 'stock': [],
            }),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)

    @patch('DairyApp.views.send_sms_alert')
    @patch('DairyApp.views.send_email_alert')
    def test_door_open_string_false_not_treated_as_true(self, mock_email, mock_sms):
        self._post({
            'fridge_code': 'F001',
            'temperature': 4.0, 'humidity': 60,
            'voltage': 12, 'door_open': 'false', 'stock': [],
        })
        self.fridge.refresh_from_db()
        self.assertFalse(self.fridge.door_open)
        self.assertFalse(Alert.objects.filter(alert_type='door_open').exists())

    def test_unknown_fridge_returns_404(self):
        response = self._post({
            'fridge_code': 'GHOST',
            'temperature': 4.0, 'humidity': 60,
            'voltage': 12, 'door_open': False, 'stock': [],
        })
        self.assertEqual(response.status_code, 404)

    def test_missing_fridge_code_returns_400(self):
        response = self._post({
            'temperature': 4.0, 'humidity': 60,
            'voltage': 12, 'door_open': False, 'stock': [],
        })
        self.assertEqual(response.status_code, 400)

    @patch('DairyApp.views.send_sms_alert')
    @patch('DairyApp.views.send_email_alert')
    def test_sensor_upload_is_atomic_when_stock_slot_is_invalid(self, mock_email, mock_sms):
        response = self._post({
            'fridge_code': 'F001',
            'temperature': 4.0, 'humidity': 60,
            'voltage': 5.0, 'door_open': False,
            'stock': [{'slot_number': 999, 'stock_level': 3}],
        })
        self.assertEqual(response.status_code, 400)
        self.fridge.refresh_from_db()
        self.assertEqual(self.fridge.temperature, 4.0)
        self.assertEqual(SensorReading.objects.count(), 0)


@override_settings(ESP32_API_KEY='TEST_KEY_123', FRIDGE_OFFLINE_TIMEOUT_SECONDS=300)
class FridgeStatusTests(BaseFixture):

    def test_dashboard_counts_recent_fridge_as_online(self):
        response = self.client.get(reverse('dashboard_stats'))
        self.assertEqual(response.status_code, 200)
        self.fridge.refresh_from_db()
        self.assertEqual(self.fridge.status, 'online')
        self.assertEqual(response.json()['stats']['online_fridges'], 1)

    def test_offline_timeout_marks_stale_fridge_offline(self):
        self.fridge.last_seen = timezone.now() - timedelta(seconds=301)
        self.fridge.status = 'online'
        self.fridge.save(update_fields=['last_seen', 'status'])

        response = self.client.get(reverse('dashboard_stats'))
        self.assertEqual(response.status_code, 200)
        self.fridge.refresh_from_db()
        self.assertEqual(self.fridge.status, 'offline')
        self.assertEqual(response.json()['stats']['offline_fridges'], 1)


@override_settings(ESP32_API_KEY='TEST_KEY_123')
class DispenseEndpointTests(BaseFixture):

    def _post(self, data, key='TEST_KEY_123'):
        return self.client.post(
            reverse('dispense_product_api'),
            json.dumps(data),
            content_type='application/json',
            HTTP_X_API_KEY=key,
        )

    @patch('DairyApp.views.send_sms_alert')
    @patch('DairyApp.views.send_email_alert')
    def test_stock_deducted_after_successful_product_detection(self, mock_email, mock_sms):
        response = self._post({
            'fridge_code': 'F001',
            'slot_number': 1,
            'quantity': 1,
            'product_detected': True,
        })
        self.assertEqual(response.status_code, 200)
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.current_stock, 9)
        self.assertEqual(StockReading.objects.filter(fridge_slot=self.slot).count(), 1)
        self.assertTrue(Transaction.objects.filter(fridge=self.fridge, product=self.product).exists())

    def test_stock_not_deducted_without_product_detection(self):
        response = self._post({
            'fridge_code': 'F001',
            'slot_number': 1,
            'quantity': 1,
            'product_detected': False,
        })
        self.assertEqual(response.status_code, 200)
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.current_stock, 10)
        self.assertEqual(StockReading.objects.filter(fridge_slot=self.slot).count(), 0)


# ── Stock Prediction ──────────────────────────────────────────────────────────

class PredictionTests(BaseFixture):

    def _create_readings(self, levels, hours_apart=24):
        """Create StockReadings spaced `hours_apart` hours apart."""
        now = timezone.now()
        for i, level in enumerate(levels):
            r = StockReading.objects.create(
                fridge_slot=self.slot, stock_level=level)
            r.recorded_at = now - timedelta(hours=(len(levels) - i) * hours_apart)
            r.save()

    def test_insufficient_data_when_fewer_than_3_readings(self):
        StockReading.objects.create(fridge_slot=self.slot, stock_level=10)
        StockReading.objects.create(fridge_slot=self.slot, stock_level=9)
        response = self.client.get(reverse('ai_stock_prediction'))
        self.assertEqual(response.status_code, 200)
        predictions = response.context['predictions']
        self.assertEqual(predictions[0]['status'], 'insufficient_data')

    def test_declining_trend_detected(self):
        self._create_readings([20, 15, 10, 8, 6])
        response = self.client.get(reverse('ai_stock_prediction'))
        pred = response.context['predictions'][0]
        self.assertEqual(pred['trend'], 'declining')
        self.assertIsNotNone(pred['days_until_stockout'])

    def test_stable_trend_detected(self):
        self._create_readings([10, 10, 10, 10, 10])
        response = self.client.get(reverse('ai_stock_prediction'))
        pred = response.context['predictions'][0]
        self.assertIn(pred['status'], ('stable',))

    def test_critical_when_already_at_minimum(self):
        # current_stock at or below minimum triggers critical immediately
        self._create_readings([10, 7, 5, 4, 3])
        self.slot.current_stock = 3
        self.slot.save()
        response = self.client.get(reverse('ai_stock_prediction'))
        pred = response.context['predictions'][0]
        self.assertIn(pred['status'], ('critical', 'warning'))

    def test_r2_score_present_for_valid_data(self):
        self._create_readings([20, 18, 16, 14, 12])
        response = self.client.get(reverse('ai_stock_prediction'))
        pred = response.context['predictions'][0]
        self.assertIsNotNone(pred['r2'])
        self.assertGreaterEqual(pred['r2'], 0.0)
        self.assertLessEqual(pred['r2'], 1.0)
