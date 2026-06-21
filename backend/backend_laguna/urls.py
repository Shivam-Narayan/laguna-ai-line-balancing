from django.contrib import admin
from django.http import HttpResponse
from django.views.generic import RedirectView
from django.urls import path, include
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

urlpatterns = [
    path('admin/', admin.site.urls),

    path('test/', lambda request: HttpResponse('Routing works'), name='test'),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/schema/swagger-ui/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/schema/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
    # Convenience routes for Swagger UI
    path('swagger/', RedirectView.as_view(url='/api/schema/swagger-ui/', permanent=False), name='swagger-redirect'),
    path('swagger-ui/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui-alias'),

    # Application includes (placed after Swagger routes)
    path('', include('apps.accounts.urls')),
    path('data/', include('apps.data_engine.urls')),
    path('absenteeism/', include('apps.absenteeism.urls')),
    path('manning-sheet/', include('apps.manning_sheet.urls')),
]