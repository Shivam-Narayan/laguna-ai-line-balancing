from django.contrib import admin
from django.urls import path, include


urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('apps.accounts.urls')),
    path('data/', include('apps.dataEngine.urls')),
    path('absenteeism/', include('apps.absenteeism.urls')),
    path('manning-sheet/', include('apps.manning_sheet.urls')),
]