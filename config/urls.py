# config/urls.py

"""
根 URL 配置：Admin + DRF API 路由
"""
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('exam.urls')),
]