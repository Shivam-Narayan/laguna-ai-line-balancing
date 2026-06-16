from . import views
from django.urls import path

urlpatterns = [
    path('export/', views.export_data, name='export-data'),
    path('export_email/', views.send_csv_via_email, name='export-data-email'),
    path('upload_absenteeism_data/', views.upload_absenteesim_data, name='Upload abasenteeism data'),
    path('export_absenteeism_data/', views.export_absenteeism_data, name='Export abasenteeism data'),
    path('preporcess_data/', views.absenteeism_data_preprocessing, name='Absenteeism Data Preprocessing'),
    path('absenteeism_prediction/', views.absenteeism_prediction, name='Absenteeism Prediction'),
    path('absenteeism_prediction_data/', views.absenteeism_prediction_data, name='Absenteeism Prediction Data'),
    path('upload_prediction_data/', views.upload_prediction_data, name='Upload Prediction data'),
    path('get_absenteeism_forecast/',  views.get_absenteeism_forecast, name='get absenteeism forecast'),
    path('get_today_absenteeism_report/',  views.get_today_absenteeism_report, name='get_today_absenteeism_report'),
]


absenteeism_endpoints = [
    f"/absenteeism/{pattern.pattern}" for pattern in urlpatterns
]