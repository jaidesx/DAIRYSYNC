import json

from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.template.loader import get_template
from xhtml2pdf import pisa
from django.shortcuts import get_object_or_404
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
)

from rest_framework.decorators import api_view
from rest_framework.response import Response

from .serializers import (
    InstitutionSerializer,
    FridgeSerializer,
    ProductSerializer,
    FridgeSlotSerializer,
    SensorReadingSerializer,
    StockReadingSerializer,
    RestockOrderSerializer,
    AlertSerializer,
)

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

@login_required
def dashboard(request):
    total_fridges = Fridge.objects.count()
    online_fridges = Fridge.objects.filter(status='online').count()
    offline_fridges = Fridge.objects.filter(status='offline').count()
    faulty_fridges = Fridge.objects.filter(status='faulty').count()

    total_products = Product.objects.count()
    active_alerts = Alert.objects.filter(resolved=False).count()
    pending_orders = RestockOrder.objects.filter(status='pending').count()

    recent_alerts = Alert.objects.order_by('-created_at')[:5]
    recent_transactions = Transaction.objects.order_by('-created_at')[:5]

    context = {
        'total_fridges': total_fridges,
        'online_fridges': online_fridges,
        'offline_fridges': offline_fridges,
        'faulty_fridges': faulty_fridges,
        'total_products': total_products,
        'active_alerts': active_alerts,
        'pending_orders': pending_orders,
        'recent_alerts': recent_alerts,
        'recent_transactions': recent_transactions,
    }

    return render(request, 'dairysync/dashboard.html', context)


@login_required
def institution_list(request):
    institutions = Institution.objects.all()
    return render(request, 'dairysync/institutions.html', {'institutions': institutions})


@login_required
def fridge_list(request):
    fridges = Fridge.objects.select_related('institution').all()
    return render(request, 'dairysync/fridges.html', {'fridges': fridges})


@login_required
def product_list(request):
    products = Product.objects.all()
    return render(request, 'dairysync/products.html', {'products': products})


@login_required
def stock_list(request):
    slots = FridgeSlot.objects.select_related('fridge', 'product', 'fridge__institution').all()
    return render(request, 'dairysync/stock.html', {'slots': slots})


@login_required
def restock_order_list(request):
    orders = RestockOrder.objects.select_related('fridge', 'product', 'fridge__institution').order_by('-created_at')
    return render(request, 'dairysync/restock_orders.html', {'orders': orders})


@login_required
def readings_list(request):
    readings = SensorReading.objects.select_related('fridge').order_by('-recorded_at')[:50]
    return render(request, 'dairysync/readings.html', {'readings': readings})


@login_required
def alert_list(request):
    alerts = Alert.objects.select_related('fridge').order_by('-created_at')
    return render(request, 'dairysync/alerts.html', {'alerts': alerts})


@login_required
def add_institution(request):
    form = InstitutionForm(request.POST or None)

    if form.is_valid():
        form.save()
        return redirect('institution_list')

    return render(request, 'dairysync/form.html', {
        'form': form,
        'title': 'Add Institution'
    })


@login_required
def add_fridge(request):
    form = FridgeForm(request.POST or None)

    if form.is_valid():
        form.save()
        return redirect('fridge_list')

    return render(request, 'dairysync/form.html', {
        'form': form,
        'title': 'Add Fridge'
    })


@login_required
def add_product(request):
    form = ProductForm(request.POST or None)

    if form.is_valid():
        form.save()
        return redirect('product_list')

    return render(request, 'dairysync/form.html', {
        'form': form,
        'title': 'Add Product'
    })


@login_required
def add_fridge_slot(request):
    form = FridgeSlotForm(request.POST or None)

    if form.is_valid():
        form.save()
        return redirect('stock_list')

    return render(request, 'dairysync/form.html', {
        'form': form,
        'title': 'Add Fridge Slot'
    })


@login_required
def edit_institution(request, id):
    institution = get_object_or_404(Institution, id=id)
    form = InstitutionForm(request.POST or None, instance=institution)

    if form.is_valid():
        form.save()
        return redirect('institution_list')

    return render(request, 'dairysync/form.html', {
        'form': form,
        'title': 'Edit Institution'
    })


@login_required
def delete_institution(request, id):
    institution = get_object_or_404(Institution, id=id)
    institution.delete()
    return redirect('institution_list')


@login_required
def edit_fridge(request, id):
    fridge = get_object_or_404(Fridge, id=id)
    form = FridgeForm(request.POST or None, instance=fridge)

    if form.is_valid():
        form.save()
        return redirect('fridge_list')

    return render(request, 'dairysync/form.html', {
        'form': form,
        'title': 'Edit Fridge'
    })


@login_required
def delete_fridge(request, id):
    fridge = get_object_or_404(Fridge, id=id)
    fridge.delete()
    return redirect('fridge_list')


@login_required
def edit_product(request, id):
    product = get_object_or_404(Product, id=id)
    form = ProductForm(request.POST or None, instance=product)

    if form.is_valid():
        form.save()
        return redirect('product_list')

    return render(request, 'dairysync/form.html', {
        'form': form,
        'title': 'Edit Product'
    })


@login_required
def delete_product(request, id):
    product = get_object_or_404(Product, id=id)
    product.delete()
    return redirect('product_list')


@login_required
def approve_order(request, id):
    order = get_object_or_404(RestockOrder, id=id)
    order.status = 'approved'
    order.save()
    return redirect('restock_order_list')


@login_required
def resolve_alert(request, id):
    alert = get_object_or_404(Alert, id=id)
    alert.resolved = True
    alert.save()
    return redirect('alert_list')


@csrf_exempt
def receive_sensor_data(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)

            fridge_code = data.get('fridge_code')
            temperature = float(data.get('temperature'))
            humidity = float(data.get('humidity'))
            voltage = float(data.get('voltage'))
            door_open = bool(data.get('door_open'))
            stock_data = data.get('stock', [])

            fridge = Fridge.objects.get(fridge_code=fridge_code)

            fridge.temperature = temperature
            fridge.humidity = humidity
            fridge.voltage = voltage
            fridge.door_open = door_open
            fridge.status = 'online'
            fridge.save()

            SensorReading.objects.create(
                fridge=fridge,
                temperature=temperature,
                humidity=humidity,
                voltage=voltage,
                door_open=door_open
            )

            if temperature > 6:

                message = f"High temperature detected in {fridge.fridge_code}: {temperature} °C"

                Alert.objects.create(
                    fridge=fridge,
                    alert_type='high_temperature',
                    message=message
                )

                send_sms_alert(message)

                send_email_alert(
                    "DAIRYSYNC Temperature Alert",
                    message
                )

            if door_open:
                Alert.objects.create(
                    fridge=fridge,
                    alert_type='door_open',
                    message='Fridge door is open'
                )

            if voltage < 10:
                Alert.objects.create(
                    fridge=fridge,
                    alert_type='power_fault',
                    message=f'Low voltage detected: {voltage}V'
                )

            for item in stock_data:
                slot_number = item.get('slot_number')
                stock_level = int(item.get('stock_level'))

                slot = FridgeSlot.objects.get(
                    fridge=fridge,
                    slot_number=slot_number
                )

                slot.current_stock = stock_level
                slot.save()

                StockReading.objects.create(
                    fridge_slot=slot,
                    stock_level=stock_level
                )

                if stock_level <= slot.product.minimum_stock:

                    message = f"Low stock for {slot.product.name} in {fridge.fridge_code}. Remaining: {stock_level}"

                    Alert.objects.create(
                        fridge=fridge,
                        alert_type='low_stock',
                        message=message
                    )

                    send_sms_alert(message)

                    send_email_alert(
                        "DAIRYSYNC Low Stock Alert",
                        message
                    )

                    existing_pending_order = RestockOrder.objects.filter(
                        fridge=fridge,
                        product=slot.product,
                        status='pending'
                    ).exists()

                    if not existing_pending_order:
                        RestockOrder.objects.create(
                            fridge=fridge,
                            product=slot.product,
                            quantity_needed=20,
                            status='pending'
                        )
                    if not existing_pending_order:
                        RestockOrder.objects.create(
                            fridge=fridge,
                            product=slot.product,
                            quantity_needed=20,
                            status='pending'
                        )

            return JsonResponse({
                'status': 'success',
                'message': 'Sensor data received successfully'
            })

        except Fridge.DoesNotExist:
            return JsonResponse({
                'status': 'error',
                'message': 'Fridge not found'
            }, status=404)

        except FridgeSlot.DoesNotExist:
            return JsonResponse({
                'status': 'error',
                'message': 'Fridge slot not found'
            }, status=404)

        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            }, status=400)

    return JsonResponse({
        'status': 'error',
        'message': 'Only POST method allowed'
    }, status=405)

@login_required
def generate_qr_code(request, id):
    fridge = get_object_or_404(Fridge, id=id)
    generate_fridge_qr(fridge)
    return redirect('fridge_list')

@login_required
def download_system_report(request):
    fridges = Fridge.objects.all()
    alerts = Alert.objects.order_by('-created_at')[:20]
    orders = RestockOrder.objects.order_by('-created_at')[:20]
    readings = SensorReading.objects.order_by('-recorded_at')[:20]

    template = get_template('dairysync/pdf_report.html')

    html = template.render({
        'fridges': fridges,
        'alerts': alerts,
        'orders': orders,
        'readings': readings,
    })

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="DAIRYSYNC_Report.pdf"'

    pisa.CreatePDF(html, dest=response)

    return response

@login_required
def ai_stock_prediction(request):
    predictions = []

    slots = FridgeSlot.objects.select_related('fridge', 'product').all()

    for slot in slots:
        readings = StockReading.objects.filter(
            fridge_slot=slot
        ).order_by('-recorded_at')[:5]

        if readings.count() >= 2:
            stock_values = [reading.stock_level for reading in readings]
            average_stock = sum(stock_values) / len(stock_values)

            if average_stock <= slot.product.minimum_stock:
                prediction = "Stock likely to run out soon"
            elif average_stock <= slot.product.minimum_stock + 5:
                prediction = "Stock reducing, prepare restock"
            else:
                prediction = "Stock is stable"
        else:
            prediction = "Not enough data"

        predictions.append({
            'fridge': slot.fridge.fridge_code,
            'product': slot.product.name,
            'current_stock': slot.current_stock,
            'minimum_stock': slot.product.minimum_stock,
            'prediction': prediction,
        })

    return render(request, 'dairysync/ai_prediction.html', {
        'predictions': predictions
    })
