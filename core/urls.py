from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenVerifyView,
)

from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)

from DairyApp import views

urlpatterns = [

    # ── Django Admin ──────────────────────────────────────────
    path('admin/', admin.site.urls),

    # ── Django Auth (login / logout) ──────────────────────────
    path('accounts/', include('django.contrib.auth.urls')),

    # ── DairyApp (all existing app routes) ───────────────────
    path('', include('DairyApp.urls')),

    # ── JWT Token Endpoints ───────────────────────────────────
    # POST /api/v1/auth/token/          → get access + refresh tokens
    # POST /api/v1/auth/token/refresh/  → renew access token
    # POST /api/v1/auth/token/verify/   → check token is still valid
    path('api/v1/auth/token/',         TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/v1/auth/token/refresh/', TokenRefreshView.as_view(),    name='token_refresh'),
    path('api/v1/auth/token/verify/',  TokenVerifyView.as_view(),     name='token_verify'),

    # ── Versioned REST API (/api/v1/) ─────────────────────────
    path('api/v1/fridges/',        views.api_fridges,        name='api_v1_fridges'),
    path('api/v1/products/',       views.api_products,       name='api_v1_products'),
    path('api/v1/stock/',          views.api_stock,          name='api_v1_stock'),
    path('api/v1/readings/',       views.api_readings,       name='api_v1_readings'),
    path('api/v1/alerts/',         views.api_alerts,         name='api_v1_alerts'),
    path('api/v1/restock-orders/', views.api_restock_orders, name='api_v1_restock_orders'),

    # ── API Documentation ─────────────────────────────────────
    # /api/schema/      → raw OpenAPI JSON (download for Postman)
    # /api/docs/        → Swagger interactive UI
    # /api/docs/redoc/  → ReDoc clean docs
    path('api/schema/',         SpectacularAPIView.as_view(),                              name='schema'),
    path('api/docs/',           SpectacularSwaggerView.as_view(url_name='schema'),         name='swagger-ui'),
    path('api/docs/redoc/',     SpectacularRedocView.as_view(url_name='schema'),           name='redoc'),

]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)