import csv
import hmac
import json
import logging
from datetime import timedelta
from decimal import Decimal

import numpy as np
from django.utils import timezone
from sklearn.linear_model import LinearRegression

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Avg, Q, Sum, Count, Case, When, IntegerField
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
    Transaction,
    NotificationPreference,
    Feedback,
)

from .forms import (
    InstitutionForm,
    FridgeForm,
    ProductForm,
    FridgeSlotForm,
    TransactionForm,
    NotificationPreferenceForm,
    FeedbackForm,
)

from .serializers import (
    FridgeSerializer,
    ProductSerializer,
    FridgeSlotSerializer,
    SensorReadingSerializer,
    RestockOrderSerializer,
    AlertSerializer,
)

logger = logging.getLogger(__name__)

_PAGE_SIZE = 20


def _paginate(request, qs):
    if not qs.ordered:
        qs = qs.order_by('pk')
    return Paginator(qs, _PAGE_SIZE).get_page(request.GET.get('page', 1))


def _fridge_offline_cutoff():
    timeout = getattr(settings, 'FRIDGE_OFFLINE_TIMEOUT_SECONDS', 300)
    return timezone.now() - timedelta(seconds=timeout)


def mark_stale_fridges_offline():
    return Fridge.objects.filter(
        status='online',
    ).filter(
        Q(last_seen__lt=_fridge_offline_cutoff()) | Q(last_seen__isnull=True),
    ).update(status='offline')


def _is_low_voltage(voltage):
    return voltage < getattr(settings, 'ESP32_MIN_VOLTAGE', 4.5)


# ============================================================
#  SECURITY HELPER — ESP32 API Key decorator
# ============================================================

def require_api_key(view_func):
    """
    Protect ESP32 endpoints with the X-Api-Key HTTP header.

    The JSON-body api_key value is retained only for backward
    compatibility with older ESP32 firmware.
    """
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        expected_key = str(
            getattr(settings, 'ESP32_API_KEY', '') or ''
        ).strip()

        if not expected_key:
            logger.error('ESP32_API_KEY is not configured in Django settings.')
            return JsonResponse(
                {
                    'status': 'error',
                    'message': 'Device authentication is not configured.',
                },
                status=503,
            )

        supplied_header_key = str(
            request.headers.get('X-Api-Key', '') or ''
        ).strip()

        supplied_body_key = ''
        if request.body:
            try:
                body_data = json.loads(request.body.decode('utf-8'))
                if isinstance(body_data, dict):
                    supplied_body_key = str(
                        body_data.get('api_key', '') or ''
                    ).strip()
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass

        header_is_valid = (
            bool(supplied_header_key)
            and hmac.compare_digest(supplied_header_key, expected_key)
        )
        body_is_valid = (
            bool(supplied_body_key)
            and hmac.compare_digest(supplied_body_key, expected_key)
        )

        if not supplied_header_key and not supplied_body_key:
            return JsonResponse(
                {
                    'status': 'error',
                    'message': 'Missing API key.',
                },
                status=401,
            )

        if not (header_is_valid or body_is_valid):
            return JsonResponse(
                {
                    'status': 'error',
                    'message': 'Invalid API key.',
                },
                status=403,
            )

        return view_func(request, *args, **kwargs)

    return wrapped


# ============================================================
#  REST API ENDPOINTS
# ============================================================

@api_view(['GET'])
def api_fridges(request):
    mark_stale_fridges_offline()
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
    mark_stale_fridges_offline()
    # Core counts via a single annotated query
    counts = Fridge.objects.aggregate(
        total_fridges=Count('id'),
        online_fridges=Count(Case(When(status='online',  then=1), output_field=IntegerField())),
        offline_fridges=Count(Case(When(status='offline', then=1), output_field=IntegerField())),
        faulty_fridges=Count(Case(When(status='faulty',  then=1), output_field=IntegerField())),
    )
    total_fridges   = counts['total_fridges']
    online_fridges  = counts['online_fridges']
    offline_fridges = counts['offline_fridges']
    faulty_fridges  = counts['faulty_fridges']

    total_products     = Product.objects.count()
    total_institutions = Institution.objects.count()
    active_alerts      = Alert.objects.filter(resolved=False).count()
    pending_orders     = RestockOrder.objects.filter(status='pending').count()

    fridge_health_pct = round(online_fridges / total_fridges * 100) if total_fridges else 0
    offline_pct       = round(offline_fridges / total_fridges * 100) if total_fridges else 0
    faulty_pct        = round(faulty_fridges  / total_fridges * 100) if total_fridges else 0

    agg = Fridge.objects.filter(status='online').aggregate(
        avg_temp=Avg('temperature'),
        avg_humidity=Avg('humidity'),
    )
    avg_temp     = round(agg['avg_temp'], 1)     if agg['avg_temp']     else None
    avg_humidity = round(agg['avg_humidity'], 1) if agg['avg_humidity'] else None

    total_revenue = Transaction.objects.filter(voided=False).aggregate(
        total=Sum('amount')
    )['total'] or 0

    # 7-day daily revenue trend
    today = timezone.now().date()
    revenue_labels = []
    revenue_data   = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        day_total = Transaction.objects.filter(
            voided=False,
            created_at__date=day,
        ).aggregate(total=Sum('amount'))['total'] or 0
        revenue_labels.append(day.strftime('%d %b'))
        revenue_data.append(float(day_total))

    fridges             = Fridge.objects.select_related('institution').all()
    recent_alerts       = Alert.objects.select_related('fridge').filter(resolved=False).order_by('-created_at')[:5]
    recent_transactions = Transaction.objects.select_related('fridge', 'product').filter(voided=False).order_by('-created_at')[:5]

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
        'offline_pct':         offline_pct,
        'faulty_pct':          faulty_pct,
        'avg_temp':            avg_temp,
        'avg_humidity':        avg_humidity,
        'total_revenue':       total_revenue,
        'fridges':             fridges,
        'recent_alerts':       recent_alerts,
        'recent_transactions': recent_transactions,
        'revenue_labels':      json.dumps(revenue_labels),
        'revenue_data':        json.dumps(revenue_data),
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
    mark_stale_fridges_offline()
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
@require_POST
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
@require_POST
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
@require_POST
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
    if not request.POST:
        fridge_id = request.GET.get('fridge')
        if fridge_id:
            form.initial['fridge'] = fridge_id
    if form.is_valid():
        slot = form.save()
        messages.success(request, 'Fridge slot added successfully.')
        return redirect('fridge_detail', id=slot.fridge_id)
    return render(request, 'dairysync/form.html', {'form': form, 'title': 'Add Fridge Slot'})


@login_required
def edit_fridge_slot(request, id):
    slot = get_object_or_404(FridgeSlot, id=id)
    form = FridgeSlotForm(request.POST or None, instance=slot)
    if form.is_valid():
        slot = form.save()
        messages.success(request, 'Fridge slot updated successfully.')
        return redirect('fridge_detail', id=slot.fridge_id)
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
    voided_filter = request.GET.get('voided', '')
    qs = Transaction.objects.select_related('fridge', 'product').order_by('-created_at')
    if q:
        qs = qs.filter(
            Q(fridge__fridge_code__icontains=q) | Q(product__name__icontains=q)
        )
    if method_filter:
        qs = qs.filter(payment_method=method_filter)
    if voided_filter == '1':
        qs = qs.filter(voided=True)
    elif voided_filter == '0' or voided_filter == '':
        qs = qs.filter(voided=False)
    return render(request, 'dairysync/transactions.html', {
        'page_obj':      _paginate(request, qs),
        'q':             q,
        'method_filter': method_filter,
        'voided_filter': voided_filter,
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
def void_transaction(request, id):
    """Mark a transaction as voided rather than hard-deleting it."""
    txn = get_object_or_404(Transaction, id=id)
    if txn.voided:
        messages.warning(request, 'Transaction is already voided.')
    else:
        txn.voided    = True
        txn.voided_at = timezone.now()
        txn.voided_by = request.user
        txn.save(update_fields=['voided', 'voided_at', 'voided_by'])
        messages.success(request, 'Transaction voided and preserved in records.')
    return redirect('transaction_list')


# ============================================================
#  FRIDGE DETAIL
# ============================================================

@login_required
def fridge_detail(request, id):
    mark_stale_fridges_offline()

    fridge = get_object_or_404(
        Fridge.objects.select_related(
            "institution"
        ).prefetch_related(
            "slots__product"
        ),
        id=id,
    )

    recent_readings = list(
        SensorReading.objects
        .filter(fridge=fridge)
        .order_by("-recorded_at")[:20]
    )
    recent_readings.reverse()

    alerts = (
        Alert.objects
        .filter(fridge=fridge, resolved=False)
        .order_by("-created_at")
    )

    return render(
        request,
        "dairysync/fridge_detail.html",
        {
            "fridge": fridge,
            "slots": fridge.slots.all(),
            "recent_readings": recent_readings,
            "alerts": alerts,
        },
    )


# ============================================================
#  ALERTS & RESTOCK
# ============================================================

@login_required
@require_POST
def resolve_alert(request, id):
    alert = get_object_or_404(Alert, id=id)
    alert.resolved = True
    alert.save()
    messages.success(request, 'Alert marked as resolved.')
    return redirect('alert_list')


@login_required
@require_POST
def bulk_resolve_alerts(request):
    """Resolve all currently unresolved alerts in one query."""
    count = Alert.objects.filter(resolved=False).update(resolved=True)
    messages.success(request, f'{count} alert{" was" if count == 1 else "s were"} resolved.')
    return redirect('alert_list')


@login_required
@require_POST
def approve_order(request, id):
    order = get_object_or_404(RestockOrder, id=id)
    order.status = 'approved'
    order.save()
    messages.success(request, f'Restock order for {order.product.name} approved.')
    return redirect('restock_order_list')


@login_required
@require_POST
def deliver_order(request, id):
    """Mark a restock order as delivered and replenish stock in the relevant fridge slot."""
    with transaction.atomic():
        order = get_object_or_404(
            RestockOrder.objects.select_for_update().select_related('fridge', 'product'), id=id
        )
        if order.status == 'delivered':
            messages.warning(request, 'Order is already marked as delivered.')
            return redirect('restock_order_list')

        order.status = 'delivered'
        order.save(update_fields=['status'])

        # Replenish the matching fridge slot (if it exists)
        try:
            slot = FridgeSlot.objects.select_for_update().get(
                fridge=order.fridge,
                product=order.product,
            )
            slot.current_stock += order.quantity_needed
            slot.save(update_fields=['current_stock'])
            StockReading.objects.create(fridge_slot=slot, stock_level=slot.current_stock)
        except FridgeSlot.DoesNotExist:
            pass  # Slot may not exist; order is still marked delivered

    messages.success(
        request,
        f'Order for {order.product.name} delivered — stock updated for {order.fridge.fridge_code}.'
    )
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
#  NOTIFICATION PREFERENCES
# ============================================================

@login_required
def notification_preferences(request):
    pref, _ = NotificationPreference.objects.get_or_create(user=request.user)
    if request.method == 'POST':
        form = NotificationPreferenceForm(request.POST, instance=pref)
        if form.is_valid():
            form.save()
            messages.success(request, 'Notification preferences saved.')
            return redirect('notification_preferences')
    else:
        form = NotificationPreferenceForm(instance=pref)
    return render(request, 'dairysync/notification_preferences.html', {'form': form})


# ============================================================
#  FEEDBACK
# ============================================================

@login_required
def submit_feedback(request):
    if request.method == 'POST':
        form = FeedbackForm(request.POST)
        if form.is_valid():
            fb = form.save(commit=False)
            fb.user = request.user
            fb.save()
            messages.success(request, 'Thank you for your feedback!')
            return redirect('dashboard')
    else:
        form = FeedbackForm()
    return render(request, 'dairysync/feedback.html', {'form': form})


@login_required
def feedback_list(request):
    if not request.user.is_staff:
        messages.error(request, 'Access denied.')
        return redirect('dashboard')
    feedbacks = Feedback.objects.select_related('user').all()
    return render(request, 'dairysync/feedback_list.html', {'feedbacks': feedbacks})


@login_required
@require_POST
def update_feedback_status(request, pk):
    if not request.user.is_staff:
        return redirect('dashboard')
    fb = get_object_or_404(Feedback, pk=pk)
    fb.status = request.POST.get('status', fb.status)
    fb.save()
    return redirect('feedback_list')


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
    from django.db.models import Prefetch

    slots = (
        FridgeSlot.objects
        .select_related('fridge', 'product')
        .prefetch_related(
            Prefetch(
                'stockreading_set',
                queryset=StockReading.objects.order_by('recorded_at'),
                to_attr='ordered_readings',
            )
        )
    )

    for slot in slots:
        if not slot.product:
            continue

        readings = slot.ordered_readings

        base = {
            'fridge':        slot.fridge.fridge_code,
            'product':       slot.product.name,
            'current_stock': slot.current_stock,
            'minimum_stock': slot.low_stock_threshold,
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

        hours_now     = (timezone.now() - t0).total_seconds() / 3600
        predicted_now = float(model.predict([[hours_now]])[0])
        min_stock     = slot.low_stock_threshold

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
            'status':              status,
            'trend':               trend,
            'daily_rate':          round(abs(slope_per_day), 2),
            'days_until_stockout': days_until_stockout,
            'depletion_date':      depletion_date,
            'r2':                  r2,
        })

    return render(request, 'dairysync/ai_prediction.html', {'predictions': predictions})


# ============================================================
#  ESP32 SENSOR DATA RECEIVER
# ============================================================

def convert_to_boolean(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    return str(value).strip().lower() in ['true', '1', 'yes', 'open']


_ALERT_TYPE_PREF_FIELD = {
    'high_temperature': 'notify_high_temperature',
    'low_stock':        'notify_low_stock',
    'door_open':        'notify_door_open',
    'power_fault':      'notify_power_fault',
    'motor_fault':      'notify_motor_fault',
}


def create_alert_and_notify(fridge, alert_type, subject, message):
    """
    Create an alert only if no unresolved alert of the same type already exists
    for this fridge (prevents notification spam on every sensor poll).
    """
    already_active = Alert.objects.filter(
        fridge=fridge, alert_type=alert_type, resolved=False
    ).exists()
    if already_active:
        return  # Already notified — wait until the alert is resolved before re-alerting

    Alert.objects.create(fridge=fridge, alert_type=alert_type, message=message)

    pref_field = _ALERT_TYPE_PREF_FIELD.get(alert_type)
    prefs = NotificationPreference.objects.select_related('user').all()

    email_recipients = []
    sms_recipients   = []

    for pref in prefs:
        if pref_field and not getattr(pref, pref_field, True):
            continue
        if pref.email_enabled:
            email = pref.get_email()
            if email:
                email_recipients.append(email)
        if pref.sms_enabled:
            phone = pref.get_phone()
            if phone:
                sms_recipients.append(phone)

    if email_recipients:
        send_email_alert(subject, message, recipients=email_recipients)
    else:
        send_email_alert(subject, message)

    if sms_recipients:
        send_sms_alert(message, recipients=sms_recipients)
    else:
        send_sms_alert(message)


@csrf_exempt
@require_api_key
@require_POST
def receive_sensor_data(request):
    """
    Receive periodic ESP32 fridge readings.

    Expected JSON:
    {
        "fridge_code": "F001",
        "temperature": 4.5,
        "humidity": 60.0,
        "voltage": 5.0,
        "door_open": false,
        "stock": [
            {"slot_number": 1, "stock_level": 10}
        ]
    }
    """
    try:
        data = json.loads(request.body.decode('utf-8'))

        if not isinstance(data, dict):
            return JsonResponse(
                {
                    'status': 'error',
                    'message': 'JSON body must be an object.',
                },
                status=400,
            )

        required_fields = (
            'fridge_code',
            'temperature',
            'humidity',
            'voltage',
            'door_open',
        )
        missing_fields = [
            field for field in required_fields
            if field not in data
        ]

        if missing_fields:
            return JsonResponse(
                {
                    'status': 'error',
                    'message': (
                        'Missing required fields: '
                        + ', '.join(missing_fields)
                    ),
                },
                status=400,
            )

        fridge_code = str(data.get('fridge_code', '')).strip()
        if not fridge_code:
            return JsonResponse(
                {
                    'status': 'error',
                    'message': 'fridge_code is required.',
                },
                status=400,
            )

        temperature = float(data['temperature'])
        humidity = float(data['humidity'])
        voltage = float(data['voltage'])
        door_open = convert_to_boolean(data['door_open'])

        if not (-50 <= temperature <= 100):
            return JsonResponse(
                {
                    'status': 'error',
                    'message': 'temperature is outside the accepted range.',
                },
                status=400,
            )

        if not (0 <= humidity <= 100):
            return JsonResponse(
                {
                    'status': 'error',
                    'message': 'humidity must be between 0 and 100.',
                },
                status=400,
            )

        if not (0 <= voltage <= 30):
            return JsonResponse(
                {
                    'status': 'error',
                    'message': 'voltage is outside the accepted range.',
                },
                status=400,
            )

        stock_data = data.get('stock', [])
        if stock_data is None:
            stock_data = []

        if not isinstance(stock_data, list):
            return JsonResponse(
                {
                    'status': 'error',
                    'message': 'stock must be a list.',
                },
                status=400,
            )

        normalized_stock_data = []
        seen_slots = set()

        for item in stock_data:
            if not isinstance(item, dict):
                return JsonResponse(
                    {
                        'status': 'error',
                        'message': 'Each stock item must be an object.',
                    },
                    status=400,
                )

            if 'slot_number' not in item or 'stock_level' not in item:
                return JsonResponse(
                    {
                        'status': 'error',
                        'message': (
                            'Each stock item requires slot_number '
                            'and stock_level.'
                        ),
                    },
                    status=400,
                )

            slot_number = int(item['slot_number'])
            stock_level = int(item['stock_level'])

            if not (1 <= slot_number <= 6):
                return JsonResponse(
                    {
                        'status': 'error',
                        'message': 'slot_number must be between 1 and 6.',
                    },
                    status=400,
                )

            if stock_level < 0:
                return JsonResponse(
                    {
                        'status': 'error',
                        'message': 'stock_level cannot be negative.',
                    },
                    status=400,
                )

            if slot_number in seen_slots:
                return JsonResponse(
                    {
                        'status': 'error',
                        'message': (
                            f'Duplicate stock entry for slot {slot_number}.'
                        ),
                    },
                    status=400,
                )

            seen_slots.add(slot_number)
            normalized_stock_data.append(
                {
                    'slot_number': slot_number,
                    'stock_level': stock_level,
                }
            )

        with transaction.atomic():
            fridge = (
                Fridge.objects
                .select_for_update()
                .get(fridge_code=fridge_code)
            )

            now = timezone.now()

            fridge.temperature = temperature
            fridge.humidity = humidity
            fridge.voltage = voltage
            fridge.door_open = door_open
            fridge.status = 'online'
            fridge.last_seen = now
            fridge.save(
                update_fields=[
                    'temperature',
                    'humidity',
                    'voltage',
                    'door_open',
                    'status',
                    'last_seen',
                    'last_updated',
                ]
            )

            SensorReading.objects.create(
                fridge=fridge,
                temperature=temperature,
                humidity=humidity,
                voltage=voltage,
                door_open=door_open,
            )

            if temperature > fridge.temp_threshold:
                create_alert_and_notify(
                    fridge=fridge,
                    alert_type='high_temperature',
                    subject='DAIRYSYNC Temperature Alert',
                    message=(
                        f'High temperature detected in {fridge.fridge_code}: '
                        f'{temperature} °C '
                        f'(threshold: {fridge.temp_threshold} °C)'
                    ),
                )

            if door_open:
                create_alert_and_notify(
                    fridge=fridge,
                    alert_type='door_open',
                    subject='DAIRYSYNC Door Alert',
                    message=(
                        f'Fridge door is open for '
                        f'{fridge.fridge_code}'
                    ),
                )

            if _is_low_voltage(voltage):
                create_alert_and_notify(
                    fridge=fridge,
                    alert_type='power_fault',
                    subject='DAIRYSYNC Power Fault Alert',
                    message=(
                        f'Low voltage detected in '
                        f'{fridge.fridge_code}: {voltage}V'
                    ),
                )

            for item in normalized_stock_data:
                slot = (
                    FridgeSlot.objects
                    .select_for_update()
                    .select_related('product')
                    .get(
                        fridge=fridge,
                        slot_number=item['slot_number'],
                    )
                )

                slot.current_stock = item['stock_level']
                slot.save(update_fields=['current_stock'])

                StockReading.objects.create(
                    fridge_slot=slot,
                    stock_level=slot.current_stock,
                )

                if (
                    slot.product
                    and slot.current_stock <= slot.low_stock_threshold
                ):
                    create_alert_and_notify(
                        fridge=fridge,
                        alert_type='low_stock',
                        subject='DAIRYSYNC Low Stock Alert',
                        message=(
                            f'Low stock for {slot.product.name} '
                            f'in {fridge.fridge_code}. '
                            f'Remaining: {slot.current_stock}'
                        ),
                    )

                    RestockOrder.objects.get_or_create(
                        fridge=fridge,
                        product=slot.product,
                        status='pending',
                        defaults={
                            'quantity_needed':
                                slot.product.restock_quantity,
                        },
                    )

        return JsonResponse(
            {
                'status': 'success',
                'message': 'Sensor data received successfully.',
                'fridge_code': fridge_code,
            },
            status=201,
        )

    except UnicodeDecodeError:
        return JsonResponse(
            {
                'status': 'error',
                'message': 'Request body must use UTF-8 encoding.',
            },
            status=400,
        )

    except json.JSONDecodeError:
        return JsonResponse(
            {
                'status': 'error',
                'message': 'Invalid JSON data.',
            },
            status=400,
        )

    except (TypeError, ValueError):
        return JsonResponse(
            {
                'status': 'error',
                'message': (
                    'Invalid number format in temperature, humidity, '
                    'voltage, slot_number, or stock_level.'
                ),
            },
            status=400,
        )

    except Fridge.DoesNotExist:
        return JsonResponse(
            {
                'status': 'error',
                'message': 'Fridge not found.',
            },
            status=404,
        )

    except FridgeSlot.DoesNotExist:
        return JsonResponse(
            {
                'status': 'error',
                'message': 'Fridge slot not found.',
            },
            status=404,
        )

    except Exception:
        logger.exception('Unexpected error in receive_sensor_data')
        return JsonResponse(
            {
                'status': 'error',
                'message': 'Unable to process sensor data.',
            },
            status=500,
        )


@csrf_exempt
@require_api_key
@require_POST
def dispense_product_api(request):
    """
    Confirm a physical dispense and deduct stock exactly once
    for the received request.

    Expected JSON:
    {
        "fridge_code": "F001",
        "slot_number": 1,
        "quantity": 1,
        "product_detected": true
    }
    """
    try:
        data = json.loads(request.body.decode('utf-8'))

        if not isinstance(data, dict):
            return JsonResponse(
                {
                    'status': 'error',
                    'message': 'JSON body must be an object.',
                },
                status=400,
            )

        required_fields = (
            'fridge_code',
            'slot_number',
            'product_detected',
        )
        missing_fields = [
            field for field in required_fields
            if field not in data
        ]

        if missing_fields:
            return JsonResponse(
                {
                    'status': 'error',
                    'message': (
                        'Missing required fields: '
                        + ', '.join(missing_fields)
                    ),
                },
                status=400,
            )

        fridge_code = str(data.get('fridge_code', '')).strip()
        if not fridge_code:
            return JsonResponse(
                {
                    'status': 'error',
                    'message': 'fridge_code is required.',
                },
                status=400,
            )

        slot_number = int(data['slot_number'])
        quantity = int(data.get('quantity', 1))
        product_detected = convert_to_boolean(
            data['product_detected']
        )

        if not (1 <= slot_number <= 6):
            return JsonResponse(
                {
                    'status': 'error',
                    'message': 'slot_number must be between 1 and 6.',
                },
                status=400,
            )

        if quantity < 1:
            return JsonResponse(
                {
                    'status': 'error',
                    'message': 'quantity must be at least 1.',
                },
                status=400,
            )

        if not product_detected:
            return JsonResponse(
                {
                    'status': 'ignored',
                    'message': (
                        'Stock was not reduced because product '
                        'detection was not confirmed.'
                    ),
                },
                status=200,
            )

        with transaction.atomic():
            fridge = (
                Fridge.objects
                .select_for_update()
                .get(fridge_code=fridge_code)
            )

            slot = (
                FridgeSlot.objects
                .select_for_update()
                .select_related('product')
                .get(
                    fridge=fridge,
                    slot_number=slot_number,
                )
            )

            if not slot.product:
                return JsonResponse(
                    {
                        'status': 'error',
                        'message': 'No product is assigned to this slot.',
                    },
                    status=400,
                )

            if slot.current_stock < quantity:
                return JsonResponse(
                    {
                        'status': 'error',
                        'message': 'Insufficient stock for dispense.',
                        'current_stock': slot.current_stock,
                    },
                    status=409,
                )

            slot.current_stock -= quantity
            slot.save(update_fields=['current_stock'])

            StockReading.objects.create(
                fridge_slot=slot,
                stock_level=slot.current_stock,
            )

            transaction_record = Transaction.objects.create(
                product=slot.product,
                fridge=fridge,
                quantity=quantity,
                amount=Decimal(str(slot.product.price)) * quantity,
                payment_method='manual',
            )

            fridge.status = 'online'
            fridge.last_seen = timezone.now()
            fridge.save(
                update_fields=[
                    'status',
                    'last_seen',
                    'last_updated',
                ]
            )

            if slot.current_stock <= slot.low_stock_threshold:
                create_alert_and_notify(
                    fridge=fridge,
                    alert_type='low_stock',
                    subject='DAIRYSYNC Low Stock Alert',
                    message=(
                        f'Low stock for {slot.product.name} '
                        f'in {fridge.fridge_code}. '
                        f'Remaining: {slot.current_stock}'
                    ),
                )

                RestockOrder.objects.get_or_create(
                    fridge=fridge,
                    product=slot.product,
                    status='pending',
                    defaults={
                        'quantity_needed':
                            slot.product.restock_quantity,
                    },
                )

        return JsonResponse(
            {
                'status': 'success',
                'message': 'Dispense confirmed and stock deducted.',
                'fridge_code': fridge_code,
                'slot_number': slot_number,
                'quantity': quantity,
                'current_stock': slot.current_stock,
                'transaction_id': transaction_record.pk,
            },
            status=201,
        )

    except UnicodeDecodeError:
        return JsonResponse(
            {
                'status': 'error',
                'message': 'Request body must use UTF-8 encoding.',
            },
            status=400,
        )

    except json.JSONDecodeError:
        return JsonResponse(
            {
                'status': 'error',
                'message': 'Invalid JSON data.',
            },
            status=400,
        )

    except (TypeError, ValueError):
        return JsonResponse(
            {
                'status': 'error',
                'message': 'Invalid slot_number or quantity.',
            },
            status=400,
        )

    except Fridge.DoesNotExist:
        return JsonResponse(
            {
                'status': 'error',
                'message': 'Fridge not found.',
            },
            status=404,
        )

    except FridgeSlot.DoesNotExist:
        return JsonResponse(
            {
                'status': 'error',
                'message': 'Fridge slot not found.',
            },
            status=404,
        )

    except Exception:
        logger.exception('Unexpected error in dispense_product_api')
        return JsonResponse(
            {
                'status': 'error',
                'message': 'Unable to process the dispense request.',
            },
            status=500,
        )


# ============================================================
#  REAL-TIME / AJAX ENDPOINTS
# ============================================================

@login_required
@require_GET
def dashboard_stats(request):
    """
    Lightweight JSON endpoint polled every 15s by the dashboard AJAX.
    All Fridge counts derived from a single aggregated query.
    """
    mark_stale_fridges_offline()
    counts = Fridge.objects.aggregate(
        total_fridges=Count('id'),
        online_fridges=Count(Case(When(status='online',  then=1), output_field=IntegerField())),
        offline_fridges=Count(Case(When(status='offline', then=1), output_field=IntegerField())),
        faulty_fridges=Count(Case(When(status='faulty',  then=1), output_field=IntegerField())),
    )

    total_products = Product.objects.count()
    active_alerts  = Alert.objects.filter(resolved=False).count()
    pending_orders = RestockOrder.objects.filter(status='pending').count()

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
    for alert in recent_alerts:
        alert['created_at'] = alert['created_at'].strftime('%d %b %Y %H:%M')

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
            'last_seen',
            'last_updated',
        )
    )
    # Add staleness flag to each fridge
    for f in fridges:
        f['is_stale'] = not f['last_seen'] or f['last_seen'] < _fridge_offline_cutoff()
        f['last_updated'] = f['last_updated'].strftime('%d %b %Y %H:%M')
        f['last_seen'] = f['last_seen'].strftime('%d %b %Y %H:%M') if f['last_seen'] else None

    return JsonResponse({
        'stats': {
            'total_fridges':   counts['total_fridges'],
            'online_fridges':  counts['online_fridges'],
            'offline_fridges': counts['offline_fridges'],
            'faulty_fridges':  counts['faulty_fridges'],
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
    fridge = get_object_or_404(Fridge, id=id)

    limit = min(int(request.GET.get('limit', 20)), 100)
    readings = (
        SensorReading.objects
        .filter(fridge=fridge)
        .order_by('-recorded_at')[:limit]
    )
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
    mark_stale_fridges_offline()
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
    rows = qs.values_list('name', 'price', 'minimum_stock', 'restock_quantity')
    return _csv_response(
        'products.csv',
        ['Product Name', 'Price', 'Minimum Stock', 'Restock Quantity'],
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
         s.product.name if s.product else 'No product assigned', s.slot_number,
         s.current_stock, s.low_stock_threshold)
        for s in qs
    ]
    return _csv_response(
        'stock.csv',
        ['Fridge Code', 'Institution', 'Product', 'Slot', 'Current Stock', 'Low Stock Threshold'],
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
         'Yes' if t.voided else 'No',
         t.created_at.strftime('%Y-%m-%d %H:%M'))
        for t in qs
    ]
    return _csv_response(
        'transactions.csv',
        ['Fridge Code', 'Product', 'Quantity', 'Amount', 'Payment Method', 'Voided', 'Created At'],
        rows,
    )
