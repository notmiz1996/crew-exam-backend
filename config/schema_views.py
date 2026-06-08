# config/schema_views.py

"""
自定义 drf-spectacular 视图子类
在所有视图的 类级别 显式设置 schema = None，绕过 EndpointEnumerator 的类属性检查
"""
from drf_spectacular.views import (
    SpectacularAPIView as BaseSpectacularAPIView,
    SpectacularSwaggerView as BaseSpectacularSwaggerView,
    SpectacularRedocView as BaseSpectacularRedocView,
)

from rest_framework.renderers import JSONRenderer

class SpectacularAPIView(BaseSpectacularAPIView):
    schema = None
    renderer_classes = [JSONRenderer]  # 确保渲染为 JSON

    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)
        response['Content-Disposition'] = 'inline'
        return response


class SpectacularSwaggerView(BaseSpectacularSwaggerView):
    """Swagger UI 端点——排除自身被 schema 生成器扫描"""
    schema = None


class SpectacularRedocView(BaseSpectacularRedocView):
    """ReDoc 端点——排除自身被 schema 生成器扫描"""
    schema = None