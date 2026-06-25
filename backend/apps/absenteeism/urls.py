from . import views
from django.urls import path

urlpatterns = [
    path('export/default/', views.export_data, name='export-data'),
    path('export/email/', views.send_csv_via_email, name='export-data-email'),
    path('upload/', views.upload_absenteesim_data, name='Upload abasenteeism data'),
    path('export/csv/', views.export_absenteeism_data, name='Export abasenteeism data'),
    path('preprocess/', views.absenteeism_data_preprocessing, name='Absenteeism Data Preprocessing'),
    path('predictions/generate/', views.absenteeism_prediction, name='Absenteeism Prediction'),
    path('predictions/', views.absenteeism_prediction_data, name='Absenteeism Prediction Data'),
    path('predictions/upload/', views.upload_prediction_data, name='Upload Prediction data'),
    path('forecasts/',  views.get_absenteeism_forecast, name='get absenteeism forecast'),
    path('reports/today/',  views.get_today_absenteeism_report, name='get_today_absenteeism_report'),
]


absenteeism_endpoints = [
    f"/absenteeism/{pattern.pattern}" for pattern in urlpatterns
]