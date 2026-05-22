import csv
import json
from datetime import timedelta

import numpy as np
from django.utils import timezone
from sklearn.linear_model import LinearRegression

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Avg, Q
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import get_template
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from functools import wraps
from rest_framework.decorators import api_view
from rest_framework.response import Response

from xhtml2pdf import pisa

from .utils import send_sms_alert, send_email_alert, generate_fridge_qr

from .models import (
    Institution,
    Fridge,
    Product,
    FridgeSlot,
    SensorReading,
    StockReading,
    Alert,
    RestockOrder,
    Transaction,
)

from .forms import (
    InstitutionForm,
    FridgeForm,
    ProductForm,
    FridgeSlotForm,
    TransactionForm,
)

from .serializers import (
    FridgeSerializer,
    ProductSerializer,
    FridgeSlotSerializer,
    SensorReadingSerializer,
    RestockOrderSerializer,
    AlertSerializer,
)


_PAGE_SIZE = 20

def _paginate(request, qs):
    return Paginator(qs, _PAGE_SIZE).get_page(request.GET.get('page', 1))


# ============================================================
#  SECURITY HELPER — ESP32 API Key decorator
#  Checks X-Api-Key header OR api_key in JSON body
# ============================================================

def require_api_key(view_func):
    """
    Protects ESP32 sensor endpoints.
    Accepts the key from the X-Api-Key header (preferred)
    or from api_key in the JSON body (legacy ESP32 support).
    """
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        header_key = request.headers.get('X-Api-Key', '')
        expected   = getattr(settings, 'ESP32_API_KEY', '')

        # Also allow key in JSON body for backward-compat with existing ESP32 firmware
        body_key = ''
        try:
            body_key = json.loads(request.body).get('api_key', '')
        except (json.JSONDecodeError, Exception):
            pass

        if not expected or (header_key != expected and body_key != expected):
            return JsonResponse(
                {'status': 'error', 'message': 'Invalid or missing API key.'},
                status=403
            )
        return view_func(request, *args, **kwargs)
    return wrapped


# ============================================================
#  REST API ENDPOINTS
# ============================================================

@api_view(['GET'])
def api_fridges(request):
    fridges = Fridge.objects.select_related('institution').all()
    serializer = FridgeSerializer(fridges, many=True)
    return Response(serializer.data)


@api_view(['GET'])
def api_products(request):
    products = Product.objects.all()
    serializer = ProductSerializer(products, many=True)
    return Response(serializer.data)


@api_view(['GET'])
def api_stock(request):
    slots = FridgeSlot.objects.select_related('fridge', 'product').all()
    serializer = FridgeSlotSerializer(slots, many=True)
    return Response(serializer.data)


@api_view(['GET'])
def api_readings(request):
    readings = SensorReading.objects.select_related('fridge').order_by('-recorded_at')[:50]
    serializer = SensorReadingSerializer(readings, many=True)
    return Response(serializer.data)


@api_view(['GET'])
def api_alerts(request):
    alerts = Alert.objects.select_related('fridge').order_by('-created_at')
    serializer = AlertSerializer(alerts, many=True)
    return Response(serializer.data)


@api_view(['GET'])
def api_restock_orders(request):
    orders = RestockOrder.objects.select_related('fridge', 'product').order_by('-created_at')
    serializer = RestockOrderSerializer(orders, many=True)
    return Response(serializer.data)


# ============================================================
#  DASHBOARD
# ============================================================

@login_required
def dashboard(request):
    total_fridges        = Fridge.objects.count()
    online_fridges       = Fridge.objects.filter(status='online').count()
    offline_fridges      = Fridge.objects.filter(status='offline').count()
    faulty_fridges       = Fridge.objects.filter(status='faulty').count()
    total_products       = Product.objects.count()
    total_institutions   = Institution.objects.count()
    active_alerts        = Alert.objects.filter(resolved=False).count()
    pending_orders       = RestockOrder.objects.filter(status='pending').count()
    fridge_health_pct    = round(online_fridges / total_fridges * 100) if total_fridges else 0

    agg = Fridge.objects.filter(status='online').aggregate(
        avg_temp=Avg('temperature'),
        avg_humidity=Avg('humidity'),
    )
    avg_temp     = round(agg['avg_temp'], 1)     if agg['avg_temp']     else None
    avg_humidity = round(agg['avg_humidity'], 1) if agg['avg_humidity'] else None

    fridges             = Fridge.objects.select_related('institution').all()
    recent_alerts       = Alert.objects.select_related('fridge').filter(resolved=False).order_by('-created_at')[:5]
    recent_transactions = Transaction.objects.select_related('fridge', 'product').order_by('-created_at')[:5]

    context = {
        'total_fridges':       total_fridges,
        'online_fridges':      online_fridges,
        'offline_fridges':     offline_fridges,
        'faulty_fridges':      faulty_fridges,
        'total_products':      total_products,
        'total_institutions':  total_institutions,
        'active_alerts':       active_alerts,
        'pending_orders':      pending_orders,
        'fridge_health_pct':   fridge_health_pct,
        'avg_temp':            avg_temp,
        'avg_humidity':        avg_humidity,
        'fridges':             fridges,
        'recent_alerts':       recent_alerts,
        'recent_transactions': recent_transactions,
    }

    return render(request, 'dairysync/dashboard.html', context)


# ============================================================
#  LIST VIEWS
# ============================================================

@login_required
def institution_list(request):
    q = request.GET.get('q', '').strip()
    qs = Institution.objects.all()
    if q:
        qs = qs.filter(
            Q(name__icontains=q) | Q(location__icontains=q) | Q(contact_person__icontains=q)
        )
    return render(request, 'dairysync/institutions.html', {
        'page_obj': _paginate(request, qs),
        'q': q,
    })


@login_required
def fridge_list(request):
    q = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '')
    qs = Fridge.objects.select_related('institution').all()
    if q:
        qs = qs.filter(Q(fridge_code__icontains=q) | Q(institution__name__icontains=q))
    if status_filter:
        qs = qs.filter(status=status_filter)
    return render(request, 'dairysync/fridges.html', {
        'page_obj': _paginate(request, qs),
        'q': q,
        'status_filter': status_filter,
    })


@login_required
def product_list(request):
    q = request.GET.get('q', '').strip()
    qs = Product.objects.all()
    if q:
        qs = qs.filter(Q(name__icontains=q))
    return render(request, 'dairysync/products.html', {
        'page_obj': _paginate(request, qs),
        'q': q,
    })


@login_required
def stock_list(request):
    q = request.GET.get('q', '').strip()
    qs = FridgeSlot.objects.select_related('fridge', 'product', 'fridge__institution').all()
    if q:
        qs = qs.filter(
            Q(fridge__fridge_code__icontains=q) | Q(product__name__icontains=q)
        )
    return render(request, 'dairysync/stock.html', {
        'page_obj': _paginate(request, qs),
        'q': q,
    })


@login_required
def restock_order_list(request):
    q = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '')
    qs = RestockOrder.objects.select_related(
        'fridge', 'product', 'fridge__institution'
    ).order_by('-created_at')
    if q:
        qs = qs.filter(
            Q(fridge__fridge_code__icontains=q) | Q(product__name__icontains=q)
        )
    if status_filter:
        qs = qs.filter(status=status_filter)
    return render(request, 'dairysync/restock_orders.html', {
        'page_obj': _paginate(request, qs),
        'q': q,
        'status_filter': status_filter,
    })


@login_required
def readings_list(request):
    q = request.GET.get('q', '').strip()
    qs = SensorReading.objects.select_related('fridge').order_by('-recorded_at')
    if q:
        qs = qs.filter(Q(fridge__fridge_code__icontains=q))
    return render(request, 'dairysync/readings.html', {
        'page_obj': _paginate(request, qs),
        'q': q,
    })


@login_required
def alert_list(request):
    q = request.GET.get('q', '').strip()
    type_filter = request.GET.get('type', '')
    resolved_filter = request.GET.get('resolved', '')
    qs = Alert.objects.select_related('fridge').order_by('-created_at')
    if q:
        qs = qs.filter(Q(fridge__fridge_code__icontains=q) | Q(message__icontains=q))
    if type_filter:
        qs = qs.filter(alert_type=type_filter)
    if resolved_filter in ('0', '1'):
        qs = qs.filter(resolved=(resolved_filter == '1'))
    return render(request, 'dairysync/alerts.html', {
        'page_obj': _paginate(request, qs),
        'q': q,
        'type_filter': type_filter,
        'resolved_filter': resolved_filter,
    })


# ============================================================
#  INSTITUTION CRUD
# ============================================================

@login_required
def add_institution(request):
    form = InstitutionForm(request.POST or None)
    if form.is_valid():
        form.save()
        messages.success(request, 'Institution added successfully.')
        return redirect('institution_list')
    return render(request, 'dairysync/form.html', {'form': form, 'title': 'Add Institution'})


@login_required
def edit_institution(request, id):
    institution = get_object_or_404(Institution, id=id)
    form = InstitutionForm(request.POST or None, instance=institution)
    if form.is_valid():
        form.save()
        messages.success(request, 'Institution updated successfully.')
        return redirect('institution_list')
    return render(request, 'dairysync/form.html', {'form': form, 'title': 'Edit Institution'})


@login_required
@require_POST  # SECURITY: prevents deletion via GET/link
def delete_institution(request, id):
    institution = get_object_or_404(Institution, id=id)
    name = institution.name
    institution.delete()
    messages.success(request, f'Institution "{name}" deleted.')
    return redirect('institution_list')


# ============================================================
#  FRIDGE CRUD
# ============================================================

@login_required
def add_fridge(request):
    form = FridgeForm(request.POST or None)
    if form.is_valid():
        form.save()
        messages.success(request, 'Fridge registered successfully.')
        return redirect('fridge_list')
    return render(request, 'dairysync/form.html', {'form': form, 'title': 'Add Fridge'})


@login_required
def edit_fridge(request, id):
    fridge = get_object_or_404(Fridge, id=id)
    form = FridgeForm(request.POST or None, instance=fridge)
    if form.is_valid():
        form.save()
        messages.success(request, 'Fridge updated successfully.')
        return redirect('fridge_list')
    return render(request, 'dairysync/form.html', {'form': form, 'title': 'Edit Fridge'})


@login_required
@require_POST  # SECURITY: prevents deletion via GET/link
def delete_fridge(request, id):
    fridge = get_object_or_404(Fridge, id=id)
    code = fridge.fridge_code
    fridge.delete()
    messages.success(request, f'Fridge {code} deleted successfully.')
    return redirect('fridge_list')


# ============================================================
#  PRODUCT CRUD
# ============================================================

@login_required
def add_product(request):
    form = ProductForm(request.POST or None)
    if form.is_valid():
        form.save()
        messages.success(request, 'Product added successfully.')
        return redirect('product_list')
    return render(request, 'dairysync/form.html', {'form': form, 'title': 'Add Product'})


@login_required
def edit_product(request, id):
    product = get_object_or_404(Product, id=id)
    form = ProductForm(request.POST or None, instance=product)
    if form.is_valid():
        form.save()
        messages.success(request, 'Product updated successfully.')
        return redirect('product_list')
    return render(request, 'dairysync/form.html', {'form': form, 'title': 'Edit Product'})


@login_required
@require_POST  # SECURITY: prevents deletion via GET/link
def delete_product(request, id):
    product = get_object_or_404(Product, id=id)
    name = product.name
    product.delete()
    messages.success(request, f'Product "{name}" deleted.')
    return redirect('product_list')


# ============================================================
#  FRIDGE SLOT
# ============================================================

@login_required
def add_fridge_slot(request):
    form = FridgeSlotForm(request.POST or None)
    if form.is_valid():
        form.save()
        messages.success(request, 'Fridge slot added successfully.')
        return redirect('stock_list')
    return render(request, 'dairysync/form.html', {'form': form, 'title': 'Add Fridge Slot'})


@login_required
def edit_fridge_slot(request, id):
    slot = get_object_or_404(FridgeSlot, id=id)
    form = FridgeSlotForm(request.POST or None, instance=slot)
    if form.is_valid():
        form.save()
        messages.success(request, 'Fridge slot updated successfully.')
        return redirect('stock_list')
    return render(request, 'dairysync/form.html', {'form': form, 'title': 'Edit Fridge Slot'})


@login_required
@require_POST
def delete_fridge_slot(request, id):
    slot = get_object_or_404(FridgeSlot, id=id)
    label = f"Slot {slot.slot_number} ({slot.fridge.fridge_code})"
    slot.delete()
    messages.success(request, f'{label} deleted.')
    return redirect('stock_list')


# ============================================================
#  TRANSACTIONS
# ============================================================

@login_required
def transaction_list(request):
    q = request.GET.get('q', '').strip()
    method_filter = request.GET.get('method', '')
    qs = Transaction.objects.select_related('fridge', 'product').order_by('-created_at')
    if q:
        qs = qs.filter(
            Q(fridge__fridge_code__icontains=q) | Q(product__name__icontains=q)
        )
    if method_filter:
        qs = qs.filter(payment_method=method_filter)
    return render(request, 'dairysync/transactions.html', {
        'page_obj':      _paginate(request, qs),
        'q':             q,
        'method_filter': method_filter,
    })


@login_required
def add_transaction(request):
    form = TransactionForm(request.POST or None)
    if form.is_valid():
        form.save()
        messages.success(request, 'Transaction recorded.')
        return redirect('transaction_list')
    return render(request, 'dairysync/form.html', {'form': form, 'title': 'Record Transaction'})


@login_required
@require_POST
def delete_transaction(request, id):
    txn = get_object_or_404(Transaction, id=id)
    txn.delete()
    messages.success(request, 'Transaction deleted.')
    return redirect('transaction_list')


# ============================================================
#  FRIDGE DETAIL
# ============================================================

@login_required
def fridge_detail(request, id):
    fridge = get_object_or_404(Fridge.objects.select_related('institution'), id=id)
    slots = FridgeSlot.objects.filter(fridge=fridge).select_related('product')
    recent_readings = (
        SensorReading.objects
        .filter(fridge=fridge)
        .order_by('-recorded_at')[:20]
    )
    active_fridge_alerts = (
        Alert.objects
        .filter(fridge=fridge, resolved=False)
        .order_by('-created_at')
    )
    return render(request, 'dairysync/fridge_detail.html', {
        'fridge':         fridge,
        'slots':          slots,
        'recent_readings': list(reversed(list(recent_readings))),
        'alerts':         active_fridge_alerts,
    })


# ============================================================
#  ALERTS & RESTOCK
# ============================================================

@login_required
@require_POST  # SECURITY: state-changing action must be POST
def resolve_alert(request, id):
    alert = get_object_or_404(Alert, id=id)
    alert.resolved = True
    alert.save()
    messages.success(request, 'Alert marked as resolved.')
    return redirect('alert_list')


@login_required
@require_POST  # SECURITY: state-changing action must be POST
def approve_order(request, id):
    order = get_object_or_404(RestockOrder, id=id)
    order.status = 'approved'
    order.save()
    messages.success(request, f'Restock order for {order.product.name} approved.')
    return redirect('restock_order_list')


# ============================================================
#  QR CODE
# ============================================================

@login_required
@require_POST
def generate_qr_code(request, id):
    fridge = get_object_or_404(Fridge, id=id)
    generate_fridge_qr(fridge)
    messages.success(request, f'QR code generated for {fridge.fridge_code}.')
    return redirect('fridge_list')


# ============================================================
#  PDF REPORT
# ============================================================

@login_required
def download_system_report(request):
    fridges  = Fridge.objects.select_related('institution').all()
    alerts   = Alert.objects.select_related('fridge').order_by('-created_at')[:20]
    orders   = RestockOrder.objects.select_related('fridge', 'product').order_by('-created_at')[:20]
    readings = SensorReading.objects.select_related('fridge').order_by('-recorded_at')[:20]

    template = get_template('dairysync/pdf_report.html')
    html = template.render({
        'fridges':  fridges,
        'alerts':   alerts,
        'orders':   orders,
        'readings': readings,
    })

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="DAIRYSYNC_Report.pdf"'

    pisa_status = pisa.CreatePDF(html, dest=response)

    if pisa_status.err:
        return HttpResponse('Error generating PDF report', status=500)

    return response


# ============================================================
#  AI STOCK PREDICTION
# ============================================================

@login_required
def ai_stock_prediction(request):
    predictions = []
    slots = FridgeSlot.objects.select_related('fridge', 'product').all()

    for slot in slots:
        readings = list(
            StockReading.objects
            .filter(fridge_slot=slot)
            .order_by('recorded_at')
        )

        base = {
            'fridge':        slot.fridge.fridge_code,
            'product':       slot.product.name,
            'current_stock': slot.current_stock,
            'minimum_stock': slot.product.minimum_stock,
            'reading_count': len(readings),
        }

        if len(readings) < 3:
            predictions.append({**base,
                'status': 'insufficient_data',
                'trend': None, 'daily_rate': None,
                'days_until_stockout': None, 'depletion_date': None, 'r2': None,
            })
            continue

        t0 = readings[0].recorded_at
        X = np.array([
            (r.recorded_at - t0).total_seconds() / 3600
            for r in readings
        ]).reshape(-1, 1)
        y = np.array([r.stock_level for r in readings], dtype=float)

        # All readings at the same timestamp — can't fit a line
        if X.max() == 0:
            predictions.append({**base,
                'status': 'insufficient_data',
                'trend': None, 'daily_rate': None,
                'days_until_stockout': None, 'depletion_date': None, 'r2': None,
            })
            continue

        model = LinearRegression().fit(X, y)
        slope_per_hour = float(model.coef_[0])
        slope_per_day  = slope_per_hour * 24
        r2             = round(float(model.score(X, y)), 2)

        hours_now      = (timezone.now() - t0).total_seconds() / 3600
        predicted_now  = float(model.predict([[hours_now]])[0])
        min_stock      = slot.product.minimum_stock

        if slope_per_hour >= 0:
            trend  = 'increasing' if slope_per_hour > 0.01 else 'stable'
            status = 'stable'
            days_until_stockout = None
            depletion_date      = None
        else:
            trend = 'declining'
            if predicted_now <= min_stock:
                days_until_stockout = 0
                depletion_date      = timezone.now().date()
                status              = 'critical'
            else:
                hours_left          = (min_stock - predicted_now) / slope_per_hour
                days_until_stockout = round(hours_left / 24, 1)
                depletion_date      = (timezone.now() + timedelta(hours=hours_left)).date()
                if days_until_stockout <= 2:
                    status = 'critical'
                elif days_until_stockout <= 7:
                    status = 'warning'
                else:
                    status = 'stable'

        predictions.append({**base,
            'status':             status,
            'trend':              trend,
            'daily_rate':         round(abs(slope_per_day), 2),
            'days_until_stockout': days_until_stockout,
            'depletion_date':     depletion_date,
            'r2':                 r2,
        })

    return render(request, 'dairysync/ai_prediction.html', {'predictions': predictions})


# ============================================================
#  ESP32 SENSOR DATA RECEIVER
#  SECURITY: api_key validated via require_api_key decorator
#  Accepts key from X-Api-Key header OR api_key in JSON body
#  (body fallback keeps existing ESP32 firmware working)
# ============================================================

def convert_to_boolean(value):
    """Safely converts ESP32 boolean values (true/false/1/0/open)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    return str(value).strip().lower() in ['true', '1', 'yes', 'open']


def create_alert_and_notify(fridge, alert_type, subject, message):
    """Creates a system alert and sends SMS + email notifications."""
    Alert.objects.create(
        fridge=fridge,
        alert_type=alert_type,
        message=message,
    )
    send_sms_alert(message)
    send_email_alert(subject, message)


@csrf_exempt        # Must stay — ESP32 cannot send Django CSRF tokens
@require_api_key    # SECURITY: validates DEVICE_API_KEY before processing
def receive_sensor_data(request):
    if request.method != 'POST':
        return JsonResponse(
            {'status': 'error', 'message': 'Only POST method allowed'},
            status=405
        )

    try:
        data = json.loads(request.body)

        fridge_code = data.get('fridge_code')
        if not fridge_code:
            return JsonResponse(
                {'status': 'error', 'message': 'fridge_code is required'},
                status=400
            )

        temperature = float(data.get('temperature'))
        humidity    = float(data.get('humidity'))
        voltage     = float(data.get('voltage'))
        door_open   = convert_to_boolean(data.get('door_open'))
        stock_data  = data.get('stock', [])

        fridge = Fridge.objects.get(fridge_code=fridge_code)

        # Update fridge live values
        fridge.temperature = temperature
        fridge.humidity    = humidity
        fridge.voltage     = voltage
        fridge.door_open   = door_open
        fridge.status      = 'online'
        fridge.save()

        # Save sensor reading
        SensorReading.objects.create(
            fridge=fridge,
            temperature=temperature,
            humidity=humidity,
            voltage=voltage,
            door_open=door_open,
        )

        # Temperature alert
        if temperature > 6:
            create_alert_and_notify(
                fridge=fridge,
                alert_type='high_temperature',
                subject='DAIRYSYNC Temperature Alert',
                message=f'High temperature detected in {fridge.fridge_code}: {temperature} °C',
            )

        # Door open alert
        if door_open:
            create_alert_and_notify(
                fridge=fridge,
                alert_type='door_open',
                subject='DAIRYSYNC Door Alert',
                message=f'Fridge door is open for {fridge.fridge_code}',
            )

        # Low voltage alert
        if voltage < 10:
            create_alert_and_notify(
                fridge=fridge,
                alert_type='power_fault',
                subject='DAIRYSYNC Power Fault Alert',
                message=f'Low voltage detected in {fridge.fridge_code}: {voltage}V',
            )

        # Stock data processing
        for item in stock_data:
            slot_number = item.get('slot_number')
            stock_level = int(item.get('stock_level'))

            slot = FridgeSlot.objects.get(fridge=fridge, slot_number=slot_number)
            slot.current_stock = stock_level
            slot.save()

            StockReading.objects.create(
                fridge_slot=slot,
                stock_level=stock_level,
            )

            # Low stock alert + auto restock order
            if stock_level <= slot.product.minimum_stock:
                create_alert_and_notify(
                    fridge=fridge,
                    alert_type='low_stock',
                    subject='DAIRYSYNC Low Stock Alert',
                    message=(
                        f'Low stock for {slot.product.name} '
                        f'in {fridge.fridge_code}. Remaining: {stock_level}'
                    ),
                )

                # Only create one pending order per product per fridge
                already_pending = RestockOrder.objects.filter(
                    fridge=fridge,
                    product=slot.product,
                    status='pending',
                ).exists()

                if not already_pending:
                    RestockOrder.objects.create(
                        fridge=fridge,
                        product=slot.product,
                        quantity_needed=20,
                        status='pending',
                    )

        return JsonResponse({
            'status': 'success',
            'message': 'Sensor data received successfully',
        })

    except Fridge.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Fridge not found'}, status=404)

    except FridgeSlot.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Fridge slot not found'}, status=404)

    except ValueError:
        return JsonResponse({
            'status': 'error',
            'message': 'Invalid number format in temperature, humidity, voltage, or stock level',
        }, status=400)

    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON data'}, status=400)

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)



@login_required
@require_GET
def dashboard_stats(request):
    """
    Lightweight JSON endpoint polled every 15s by the dashboard AJAX.
    Returns stat card counts + recent alerts + fridge status list.
    Designed to be fast — no heavy joins, no pagination overhead.
    """

    # Stat counts
    total_fridges   = Fridge.objects.count()
    online_fridges  = Fridge.objects.filter(status='online').count()
    offline_fridges = Fridge.objects.filter(status='offline').count()
    faulty_fridges  = Fridge.objects.filter(status='faulty').count()
    total_products  = Product.objects.count()
    active_alerts   = Alert.objects.filter(resolved=False).count()
    pending_orders  = RestockOrder.objects.filter(status='pending').count()

    # Recent alerts (last 5) for the alerts table
    recent_alerts = list(
        Alert.objects
        .select_related('fridge')
        .filter(resolved=False)
        .order_by('-created_at')[:5]
        .values(
            'id',
            'fridge__fridge_code',
            'alert_type',
            'message',
            'created_at',
        )
    )

    # Format datetime for JSON
    for alert in recent_alerts:
        alert['created_at'] = alert['created_at'].strftime('%d %b %Y %H:%M')

    # Fridge status list for live indicators
    fridges = list(
        Fridge.objects
        .select_related('institution')
        .values(
            'id',
            'fridge_code',
            'status',
            'temperature',
            'humidity',
            'voltage',
        )
    )

    return JsonResponse({
        'stats': {
            'total_fridges':   total_fridges,
            'online_fridges':  online_fridges,
            'offline_fridges': offline_fridges,
            'faulty_fridges':  faulty_fridges,
            'total_products':  total_products,
            'active_alerts':   active_alerts,
            'pending_orders':  pending_orders,
        },
        'recent_alerts': recent_alerts,
        'fridges':        fridges,
    })


@login_required
@require_GET
def fridge_temperature_history(request, id):
    """
    Returns the last 20 sensor readings for a specific fridge.
    Used by the temperature history chart on the dashboard.

    GET /api/v1/fridges/<id>/history/
    """
    fridge = get_object_or_404(Fridge, id=id)

    readings = (
        SensorReading.objects
        .filter(fridge=fridge)
        .order_by('-recorded_at')[:20]
    )

    # Reverse so chart goes oldest → newest left to right
    readings = list(reversed(list(readings)))

    data = [
        {
            'time':        r.recorded_at.strftime('%H:%M'),
            'temperature': float(r.temperature),
            'humidity':    float(r.humidity),
            'voltage':     float(r.voltage),
        }
        for r in readings
    ]

    return JsonResponse({
        'fridge_code': fridge.fridge_code,
        'readings':    data,
    })


@login_required
@require_GET
def alert_count(request):
    """
    Ultra-lightweight endpoint — returns only the active alert count.
    Polled frequently to detect new alerts for browser notifications.

    GET /api/v1/alert-count/
    """
    count = Alert.objects.filter(resolved=False).count()
    latest_id = (
        Alert.objects
        .filter(resolved=False)
        .order_by('-id')
        .values_list('id', flat=True)
        .first()
    ) or 0

    return JsonResponse({
        'active_alerts':   count,
        'latest_alert_id': latest_id,
    })


# ============================================================
#  CSV EXPORT
# ============================================================

def _csv_response(filename, headers, rows):
    """Return an HttpResponse streaming CSV data."""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow(headers)
    writer.writerows(rows)
    return response


@login_required
def export_institutions(request):
    q = request.GET.get('q', '').strip()
    qs = Institution.objects.all()
    if q:
        qs = qs.filter(
            Q(name__icontains=q) | Q(location__icontains=q) | Q(contact_person__icontains=q)
        )
    rows = qs.values_list('name', 'location', 'contact_person', 'phone')
    return _csv_response(
        'institutions.csv',
        ['Name', 'Location', 'Contact Person', 'Phone'],
        rows,
    )


@login_required
def export_fridges(request):
    q             = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '')
    qs = Fridge.objects.select_related('institution').all()
    if q:
        qs = qs.filter(Q(fridge_code__icontains=q) | Q(institution__name__icontains=q))
    if status_filter:
        qs = qs.filter(status=status_filter)
    rows = [
        (f.fridge_code, f.institution.name, f.status,
         f.temperature, f.humidity, f.voltage,
         'Yes' if f.door_open else 'No',
         f.last_updated.strftime('%Y-%m-%d %H:%M'))
        for f in qs
    ]
    return _csv_response(
        'fridges.csv',
        ['Fridge Code', 'Institution', 'Status', 'Temperature (°C)',
         'Humidity (%)', 'Voltage (V)', 'Door Open', 'Last Updated'],
        rows,
    )


@login_required
def export_products(request):
    q = request.GET.get('q', '').strip()
    qs = Product.objects.all()
    if q:
        qs = qs.filter(Q(name__icontains=q))
    rows = qs.values_list('name', 'price', 'minimum_stock')
    return _csv_response(
        'products.csv',
        ['Product Name', 'Price', 'Minimum Stock'],
        rows,
    )


@login_required
def export_stock(request):
    q = request.GET.get('q', '').strip()
    qs = FridgeSlot.objects.select_related('fridge', 'product', 'fridge__institution').all()
    if q:
        qs = qs.filter(
            Q(fridge__fridge_code__icontains=q) | Q(product__name__icontains=q)
        )
    rows = [
        (s.fridge.fridge_code, s.fridge.institution.name,
         s.product.name, s.slot_number,
         s.current_stock, s.product.minimum_stock)
        for s in qs
    ]
    return _csv_response(
        'stock.csv',
        ['Fridge Code', 'Institution', 'Product', 'Slot', 'Current Stock', 'Minimum Stock'],
        rows,
    )


@login_required
def export_restock_orders(request):
    q             = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '')
    qs = RestockOrder.objects.select_related('fridge', 'product', 'fridge__institution').order_by('-created_at')
    if q:
        qs = qs.filter(
            Q(fridge__fridge_code__icontains=q) | Q(product__name__icontains=q)
        )
    if status_filter:
        qs = qs.filter(status=status_filter)
    rows = [
        (o.fridge.fridge_code, o.fridge.institution.name,
         o.product.name, o.quantity_needed, o.status,
         o.created_at.strftime('%Y-%m-%d %H:%M'))
        for o in qs
    ]
    return _csv_response(
        'restock_orders.csv',
        ['Fridge Code', 'Institution', 'Product', 'Qty Needed', 'Status', 'Created At'],
        rows,
    )


@login_required
def export_readings(request):
    q = request.GET.get('q', '').strip()
    qs = SensorReading.objects.select_related('fridge').order_by('-recorded_at')
    if q:
        qs = qs.filter(Q(fridge__fridge_code__icontains=q))
    rows = [
        (r.fridge.fridge_code, r.temperature, r.humidity, r.voltage,
         'Yes' if r.door_open else 'No',
         r.recorded_at.strftime('%Y-%m-%d %H:%M'))
        for r in qs
    ]
    return _csv_response(
        'sensor_readings.csv',
        ['Fridge Code', 'Temperature (°C)', 'Humidity (%)', 'Voltage (V)', 'Door Open', 'Recorded At'],
        rows,
    )


@login_required
def export_alerts(request):
    q               = request.GET.get('q', '').strip()
    type_filter     = request.GET.get('type', '')
    resolved_filter = request.GET.get('resolved', '')
    qs = Alert.objects.select_related('fridge').order_by('-created_at')
    if q:
        qs = qs.filter(Q(fridge__fridge_code__icontains=q) | Q(message__icontains=q))
    if type_filter:
        qs = qs.filter(alert_type=type_filter)
    if resolved_filter in ('0', '1'):
        qs = qs.filter(resolved=(resolved_filter == '1'))
    rows = [
        (a.fridge.fridge_code, a.alert_type, a.message,
         'Yes' if a.resolved else 'No',
         a.created_at.strftime('%Y-%m-%d %H:%M'))
        for a in qs
    ]
    return _csv_response(
        'alerts.csv',
        ['Fridge Code', 'Alert Type', 'Message', 'Resolved', 'Created At'],
        rows,
    )


@login_required
def export_transactions(request):
    q             = request.GET.get('q', '').strip()
    method_filter = request.GET.get('method', '')
    qs = Transaction.objects.select_related('fridge', 'product').order_by('-created_at')
    if q:
        qs = qs.filter(
            Q(fridge__fridge_code__icontains=q) | Q(product__name__icontains=q)
        )
    if method_filter:
        qs = qs.filter(payment_method=method_filter)
    rows = [
        (t.fridge.fridge_code, t.product.name, t.quantity,
         t.amount, t.payment_method,
         t.created_at.strftime('%Y-%m-%d %H:%M'))
        for t in qs
    ]
    return _csv_response(
        'transactions.csv',
        ['Fridge Code', 'Product', 'Quantity', 'Amount', 'Payment Method', 'Created At'],
        rows,
    )