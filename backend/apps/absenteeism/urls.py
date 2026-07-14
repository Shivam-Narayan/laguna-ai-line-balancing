from django.urls import path
from . import views

urlpatterns = [
    path('export/default/', views.export_data, name='export-data'),
    path('export/email/', views.send_csv_via_email, name='export-data-email'),
    path('upload/', views.upload_absenteesim_data, name='upload-absenteeism-data'),
    path('export/csv/', views.export_absenteeism_data, name='export-absenteeism-data'),
    path('preprocess/', views.absenteeism_data_preprocessing, name='absenteeism-data-preprocessing'),
    path('predictions/generate/', views.absenteeism_prediction, name='absenteeism-prediction'),
    path('predictions/', views.absenteeism_prediction_data, name='absenteeism-prediction-data'),
    path('predictions/upload/', views.upload_prediction_data, name='upload-prediction-data'),
    path('forecasts/', views.get_absenteeism_forecast, name='get-absenteeism-forecast'),
    path('reports/today/', views.get_today_absenteeism_report, name='get-today-absenteeism-report'),
]