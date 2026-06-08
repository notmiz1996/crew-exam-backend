# config/urls.py

"""
根 URL 配置：Admin + DRF API 路由 + API 文档
"""
from django.contrib import admin
from django.urls import path, include
from .schema_views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('exam.urls')),

    # ── API 文档（使用自定义子类，类级别 schema=None） ──
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]