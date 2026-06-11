from django.urls import path
from . import views

urlpatterns = [

    # ── Dashboard ─────────────────────────────────────────────
    path('', views.dashboard, name='dashboard'),

    # ── List Views ────────────────────────────────────────────
    path('institutions/',   views.institution_list,    name='institution_list'),
    path('fridges/',        views.fridge_list,         name='fridge_list'),
    path('products/',       views.product_list,        name='product_list'),
    path('stock/',          views.stock_list,          name='stock_list'),
    path('restock-orders/', views.restock_order_list,  name='restock_order_list'),
    path('readings/',       views.readings_list,       name='readings_list'),
    path('alerts/',         views.alert_list,          name='alert_list'),
    path('ai-prediction/',  views.ai_stock_prediction, name='ai_stock_prediction'),

    # ── Add Views ─────────────────────────────────────────────
    path('add-institution/', views.add_institution, name='add_institution'),
    path('add-fridge/',      views.add_fridge,      name='add_fridge'),
    path('add-product/',     views.add_product,     name='add_product'),
    path('add-fridge-slot/',             views.add_fridge_slot,   name='add_fridge_slot'),
    path('fridge-slot/edit/<int:id>/',   views.edit_fridge_slot,  name='edit_fridge_slot'),
    path('fridge-slot/delete/<int:id>/', views.delete_fridge_slot, name='delete_fridge_slot'),
    path('transactions/',                views.transaction_list,  name='transaction_list'),
    path('transactions/add/',            views.add_transaction,   name='add_transaction'),
    path('transactions/void/<int:id>/',  views.void_transaction,  name='void_transaction'),

    # ── Edit / Delete ─────────────────────────────────────────
    path('institution/edit/<int:id>/',   views.edit_institution,   name='edit_institution'),
    path('institution/delete/<int:id>/', views.delete_institution, name='delete_institution'),
    path('fridge/<int:id>/',             views.fridge_detail,      name='fridge_detail'),
    path('fridge/edit/<int:id>/',        views.edit_fridge,        name='edit_fridge'),
    path('fridge/delete/<int:id>/',      views.delete_fridge,      name='delete_fridge'),
    path('product/edit/<int:id>/',       views.edit_product,       name='edit_product'),
    path('product/delete/<int:id>/',     views.delete_product,     name='delete_product'),

    # ── Actions ───────────────────────────────────────────────
    path('order/approve/<int:id>/', views.approve_order,          name='approve_order'),
    path('order/deliver/<int:id>/', views.deliver_order,          name='deliver_order'),
    path('alert/resolve/<int:id>/', views.resolve_alert,          name='resolve_alert'),
    path('alerts/resolve-all/',     views.bulk_resolve_alerts,    name='bulk_resolve_alerts'),
    path('fridge/qr/<int:id>/',     views.generate_qr_code,       name='generate_qr_code'),
    path('download-report/',        views.download_system_report, name='download_system_report'),

    # ── Notifications & Feedback ──────────────────────────────
    path('notifications/preferences/', views.notification_preferences, name='notification_preferences'),
    path('feedback/',                  views.submit_feedback,          name='submit_feedback'),
    path('feedback/list/',             views.feedback_list,            name='feedback_list'),
    path('feedback/<int:pk>/status/',  views.update_feedback_status,   name='update_feedback_status'),

    # ── ESP32 Sensor Data ─────────────────────────────────────
    path('api/sensor-data/', views.receive_sensor_data, name='receive_sensor_data'),

    # ── Real-time / AJAX Endpoints ────────────────────────────
    path('api/v1/dashboard-stats/',            views.dashboard_stats,            name='dashboard_stats'),
    path('api/v1/alert-count/',                views.alert_count,                name='alert_count'),
    path('api/v1/fridges/<int:id>/history/',   views.fridge_temperature_history, name='fridge_temperature_history'),

    # ── CSV Exports ───────────────────────────────────────────
    path('export/institutions/',   views.export_institutions,   name='export_institutions'),
    path('export/fridges/',        views.export_fridges,        name='export_fridges'),
    path('export/products/',       views.export_products,       name='export_products'),
    path('export/stock/',          views.export_stock,          name='export_stock'),
    path('export/restock-orders/', views.export_restock_orders, name='export_restock_orders'),
    path('export/readings/',       views.export_readings,       name='export_readings'),
    path('export/alerts/',         views.export_alerts,         name='export_alerts'),
    path('export/transactions/',   views.export_transactions,   name='export_transactions'),

    # ── REST API ──────────────────────────────────────────────
    path('api/fridges/',        views.api_fridges,        name='api_fridges'),
    path('api/products/',       views.api_products,       name='api_products'),
    path('api/stock/',          views.api_stock,          name='api_stock'),
    path('api/readings/',       views.api_readings,       name='api_readings'),
    path('api/alerts/',         views.api_alerts,         name='api_alerts'),
    path('api/restock-orders/', views.api_restock_orders, name='api_restock_orders'),
]
