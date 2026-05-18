from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),

    path('api/fridges/', views.api_fridges, name='api_fridges'),
path('api/products/', views.api_products, name='api_products'),
path('api/stock/', views.api_stock, name='api_stock'),
path('api/readings/', views.api_readings, name='api_readings'),
path('api/alerts/', views.api_alerts, name='api_alerts'),
path('api/restock-orders/', views.api_restock_orders, name='api_restock_orders'),
    path('institutions/', views.institution_list, name='institution_list'),
    path('fridges/', views.fridge_list, name='fridge_list'),
    path('products/', views.product_list, name='product_list'),
    path('stock/', views.stock_list, name='stock_list'),
    path('restock-orders/', views.restock_order_list, name='restock_order_list'),
    path('readings/', views.readings_list, name='readings_list'),
    path('alerts/', views.alert_list, name='alert_list'),

    path('add-institution/', views.add_institution, name='add_institution'),
    path('add-fridge/', views.add_fridge, name='add_fridge'),
    path('add-product/', views.add_product, name='add_product'),
    path('add-fridge-slot/', views.add_fridge_slot, name='add_fridge_slot'),

    path('institution/edit/<int:id>/', views.edit_institution, name='edit_institution'),
    path('institution/delete/<int:id>/', views.delete_institution, name='delete_institution'),

    path('fridge/edit/<int:id>/', views.edit_fridge, name='edit_fridge'),
    path('fridge/delete/<int:id>/', views.delete_fridge, name='delete_fridge'),

    path('product/edit/<int:id>/', views.edit_product, name='edit_product'),
    path('product/delete/<int:id>/', views.delete_product, name='delete_product'),

    path('order/approve/<int:id>/', views.approve_order, name='approve_order'),
    path('alert/resolve/<int:id>/', views.resolve_alert, name='resolve_alert'),

    path('api/sensor-data/', views.receive_sensor_data, name='receive_sensor_data'),
    path('fridge/qr/<int:id>/', views.generate_qr_code, name='generate_qr_code'),
    path('download-report/', views.download_system_report, name='download_system_report'),
    path('ai-prediction/', views.ai_stock_prediction, name='ai_stock_prediction'),
]